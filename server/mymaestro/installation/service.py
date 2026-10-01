"""Service d'installation des moteurs : détection, une installation à la fois dans un fil, événements `installation` sur le
bus SSE. Les étapes réussies sont notées dans <dossier>/.mymaestro-etapes.json : « Réessayer » reprend à la première étape
non faite."""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from mymaestro import config
from mymaestro.connectors.claude import executable_claude
from mymaestro.contrat.modeles import EtatMoteurInstalle, EtatMoteurs, MoteurVideo
from mymaestro.core.grilles import Definition, definition_par_defaut, definitions_permises
from mymaestro.installation.etapes import ContexteEtape, executer_etape, lancer_reel
from mymaestro.installation.manifeste import (
    FICHIER_VERSION,
    EtatInstallation,
    MoteurManifeste,
    charger_manifeste,
    detecter,
    dossier_moteur,
)
from mymaestro.installation.telechargement import ErreurInstallation, InstallationAnnulee, espace_libre_mo, telecharger

FICHIER_ETAPES = ".mymaestro-etapes.json"
DELAI_ARRET_S = 30.0
DUREE_CACHE_CLAUDE_S = 30.0  # validité de la sonde de Claude (`--version`, connexion) pour GET /api/moteurs
INTERVALLE_EVENEMENTS_S = 0.25 # au plus un événement de progression par quart de seconde
LLM_BONSAI = {"fournisseur": "bonsai", "modele": config.BONSAI_MODELE}
ETATS_UTILISABLES = (EtatInstallation.INSTALLE, EtatInstallation.EXTERNE)
MOTEURS_PILOTES = ("maestro", "dlss5", "bonsai", "claude")  # codex suit maestro ; export est toujours réel

journal = logging.getLogger("mymaestro")


def mode_demo() -> bool:
    """Vrai si `MYMAESTRO_MOTEURS_REELS` est posée et ne désigne aucun moteur (« aucun ») : tout est simulé."""
    valeur = os.environ.get("MYMAESTRO_MOTEURS_REELS")
    return valeur is not None and not config._moteurs_reels(valeur)


def moteurs_reels(manifeste: dict[str, MoteurManifeste] | None = None) -> frozenset[str]:
    """Moteurs à piloter pour de vrai : ceux qui sont INSTALLE ou EXTERNE (`codex` suit `maestro`)."""
    manifeste = manifeste if manifeste is not None else charger_manifeste()
    reels = {id_ for id_ in MOTEURS_PILOTES if id_ in manifeste and detecter(manifeste[id_]) in ETATS_UTILISABLES}
    if "maestro" in reels:
        reels.add("codex")
    return frozenset(reels)


def moteur_absent(moteur_id: str) -> bool:
    """Vrai si le moteur n'est ni installé ni externe (et qu'on n'est pas en mode démo, où tout est simulé)."""
    valeur = os.environ.get("MYMAESTRO_MOTEURS_REELS")
    if valeur is not None:
        return not mode_demo() and moteur_id not in config._moteurs_reels(valeur)
    manifeste = charger_manifeste()
    return moteur_id in manifeste and detecter(manifeste[moteur_id]) not in ETATS_UTILISABLES


def claude_absent() -> bool:
    """Vrai si Claude n'est ni installé ni externe (et qu'on n'est pas en mode démo, où il est simulé)."""
    return moteur_absent("claude")


def adapter_reglages(module_id: str, valeurs: dict[str, Any]) -> dict[str, Any]:
    """Réglages par défaut d'un module selon les moteurs installés (Director musique) : sans Claude, l'écriture et les trois
    étapes de prompts passent sur Bonsai ; sans DLSS5, sa passe est inactive. Renvoie une copie si quelque chose change."""
    if module_id != "director_musique":
        return valeurs
    sans_claude, sans_dlss5 = claude_absent(), moteur_absent("dlss5")
    h3 = (valeurs.get("rendu") or {}).get("h3", Definition.P544.value)
    h3_refuse = Definition(h3) not in definitions_permises(MoteurVideo.H3)  # carte sous 12 Go : 544p n'est plus permis
    if not (sans_claude or sans_dlss5 or h3_refuse):
        return valeurs
    resultat = copy.deepcopy(valeurs)
    if h3_refuse:
        resultat.setdefault("rendu", {})["h3"] = definition_par_defaut(MoteurVideo.H3).value
    if sans_claude:
        llm = resultat.setdefault("llm", {})
        for cle in ("ecriture", "prompts_image", "prompts_video", "prompts_son"):
            llm.setdefault(cle, {}).update(LLM_BONSAI)
    if sans_dlss5:
        resultat.setdefault("postprod", {}).setdefault("dlss5", {})["actif"] = False
    return resultat


class ServiceInstallation:
    def __init__(
        self,
        publier: Callable[[dict[str, Any]], None],
        manifeste: dict[str, MoteurManifeste] | None = None,
        *,
        lancer: Callable[[list[str], Path, threading.Event], subprocess.CompletedProcess] | None = None,
    ) -> None:
        self._publier = publier
        self._manifeste = manifeste if manifeste is not None else charger_manifeste()
        self._lancer = lancer or lancer_reel
        self._verrou = threading.Lock()
        self._fil: threading.Thread | None = None
        self._en_cours: str | None = None
        self._annule = threading.Event()
        self._redemarrage_requis = False  # une installation a réussi depuis le démarrage : les connecteurs sont encore ceux d'avant
        self._suivi: dict[str, dict[str, Any]] = {}  # dernière progression ou dernier message d'échec, par moteur
        self._dernier_evenement = 0.0
        self._cache_claude: tuple[float, EtatInstallation, bool] | None = None  # (instant, état détecté, connecté)
        self._connexion_attendue = False  # « Se connecter » cliqué : la connexion se termine dans le terminal, hors de notre vue

    # --- état -----------------------------------------------------------------------------------------

    def etat(self) -> EtatMoteurs:
        with self._verrou:
            en_cours = self._en_cours
            redemarrage = self._redemarrage_requis
            suivi = {cle: dict(valeur) for cle, valeur in self._suivi.items()}
        moteurs: list[EtatMoteurInstalle] = []
        for moteur in self._manifeste.values():
            connecte: bool | None = False if moteur.id == "claude" else None
            if moteur.id == en_cours:
                etat = EtatInstallation.EN_COURS
            elif moteur.id == "claude":
                etat, connecte = self._etat_claude(moteur)
            else:
                etat = detecter(moteur)
            reste = suivi.get(moteur.id, {}) if etat in (EtatInstallation.EN_COURS, EtatInstallation.INCOMPLET, EtatInstallation.ABSENT) else {}
            moteurs.append(
                EtatMoteurInstalle(
                    id=moteur.id, libelle=moteur.libelle, requis=moteur.requis, etat=etat.value, version_attendue=moteur.version,
                    espace_mo=moteur.espace_mo, note=moteur.note, progression=reste.get("progression"), etape=reste.get("etape"),
                    message=reste.get("message"), journal=self._dernier_journal(moteur.id), connecte=connecte,
                )
            )
        manquants = any(m.requis and m.etat not in (*(e.value for e in ETATS_UTILISABLES), EtatInstallation.VERSION_DIFFERENTE.value) for m in moteurs)
        return EtatMoteurs(moteurs=moteurs, requis_manquants=manquants, mode_demo=mode_demo(), en_cours=en_cours, redemarrage_requis=redemarrage)

    def _etat_claude(self, moteur: MoteurManifeste) -> tuple[EtatInstallation, bool]:
        """État de Claude (`--version`) et connexion (`auth status`), sondés au plus toutes les 30 s : ces deux lancements de
        processus coûtent cher à chaque GET /api/moteurs. Le cache est invalidé à la fin d'une installation et au clic sur
        « Se connecter » ; tant qu'une connexion est attendue et pas encore constatée, seule la connexion est resondée."""
        with self._verrou:
            cache = self._cache_claude
            attendue = self._connexion_attendue
        maintenant = time.monotonic()
        valide = cache is not None and maintenant - cache[0] < DUREE_CACHE_CLAUDE_S
        if valide and not (attendue and not cache[2]):
            return cache[1], cache[2]
        instant, etat = (cache[0], cache[1]) if valide else (maintenant, detecter(moteur))
        connecte = self._claude_connecte() if etat in ETATS_UTILISABLES else False
        with self._verrou:
            self._cache_claude = (instant, etat, connecte)
            if connecte:
                self._connexion_attendue = False
        return etat, connecte

    @staticmethod
    def _dernier_journal(moteur_id: str) -> str | None:
        try:
            trouves = sorted(config.DOSSIER_JOURNAUX.glob(f"installation-{moteur_id}-*.log"))
        except OSError:
            return None
        return str(trouves[-1]) if trouves else None

    @staticmethod
    def _claude_connecte() -> bool:
        """`claude auth status --json` → `loggedIn` ; tout échec vaut False."""
        executable = executable_claude()
        if not executable:
            return False
        try:
            resultat = subprocess.run(
                [executable, "auth", "status", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=20, check=False,
            )
            return bool(json.loads(resultat.stdout).get("loggedIn"))
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            return False

    # --- installation ---------------------------------------------------------------------------------

    def installer(self, moteur_id: str) -> None:
        """Démarre l'installation dans un fil (une seule à la fois). KeyError si le moteur est inconnu ; ErreurInstallation
        s'il est externe ou installé, si une installation est en cours ou si l'espace disque manque."""
        moteur = self._manifeste[moteur_id]
        with self._verrou:
            if self._en_cours is not None:
                raise ErreurInstallation("une installation est déjà en cours")
            etat = detecter(moteur)
            if etat is EtatInstallation.EXTERNE:
                raise ErreurInstallation(f"{moteur.libelle} est un moteur externe : MyMaestro ne l'installe pas")
            if etat is EtatInstallation.INSTALLE:
                raise ErreurInstallation(f"{moteur.libelle} est déjà installé")
            dossier = dossier_moteur(moteur.id)
            necessaire = max(0, moteur.espace_mo - self._deja_telecharge_mo(moteur, dossier))
            libre = espace_libre_mo(dossier)
            if libre < necessaire:
                raise ErreurInstallation(f"espace disque insuffisant pour {moteur.libelle} : {necessaire} Mo nécessaires, {libre} Mo libres")
            self._en_cours = moteur.id
            self._annule.clear()
            self._suivi[moteur.id] = {"progression": 0.0, "etape": "preparation", "message": "Démarrage de l'installation"}
            self._fil = threading.Thread(target=self._executer, args=(moteur, dossier), name=f"installation-{moteur.id}", daemon=True)
            self._fil.start()

    def annuler(self) -> None:
        self._annule.set()

    def connecter_claude(self) -> None:
        """Ouvre un terminal : `cmd /c start "" cmd /k <claude> auth login` (connexion par le navigateur)."""
        executable = executable_claude()
        if not executable:
            raise ErreurInstallation("Claude n'est pas installé : installe-le d'abord")
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", executable, "auth", "login"])
        with self._verrou:
            self._cache_claude = None
            self._connexion_attendue = True

    def arreter(self) -> None:
        """Fermeture de MyMaestro : annule et attend le fil (au plus 30 s)."""
        self._annule.set()
        fil = self._fil
        if fil is not None and fil.is_alive():
            fil.join(DELAI_ARRET_S)

    # --- fil d'installation ---------------------------------------------------------------------------

    @staticmethod
    def _destination(moteur: MoteurManifeste, fichier_nom: str, dossier: Path) -> Path:
        """Les archives citées par une étape `extraire` vont dans .telechargements/ ; les autres fichiers (le modèle GGUF)
        sont posés directement à leur place, relative au dossier du moteur."""
        archive = any(e.get("type") == "extraire" and e.get("fichier") == fichier_nom for e in moteur.etapes)
        return (dossier / ".telechargements" / fichier_nom) if archive else (dossier / fichier_nom)

    def _deja_telecharge_mo(self, moteur: MoteurManifeste, dossier: Path) -> int:
        """Tout ce que le dossier du moteur contient déjà : archives et `.partiel`, mais aussi ce que les étapes ont posé
        (extraction, venv, modèles préchargés). Une reprise ne redemande ainsi que le reste."""
        octets = 0
        for racine, _, fichiers in os.walk(dossier):
            for nom in fichiers:
                try:
                    octets += (Path(racine) / nom).stat().st_size
                except OSError:
                    pass
        return octets // (1024 * 1024)

    def _evenement(self, moteur_id: str, etape: str, progression: float | None, message: str, etat: str, *, force: bool = False) -> None:
        maintenant = time.monotonic()
        if not force and maintenant - self._dernier_evenement < INTERVALLE_EVENEMENTS_S:
            with self._verrou:
                self._suivi[moteur_id] = {"progression": progression, "etape": etape, "message": message}
            return
        self._dernier_evenement = maintenant
        with self._verrou:
            self._suivi[moteur_id] = {"progression": progression, "etape": etape, "message": message}
        self._publier({"type": "installation", "moteur": moteur_id, "etape": etape, "progression": progression, "message": message, "etat": etat})

    @staticmethod
    def _etapes_faites(dossier: Path, version: str) -> set[int]:
        try:
            contenu = json.loads((dossier / FICHIER_ETAPES).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        if not isinstance(contenu, dict) or contenu.get("version") != version:
            return set()
        return {i for i in contenu.get("faites", []) if isinstance(i, int)}

    @staticmethod
    def _noter_etapes(dossier: Path, version: str, faites: set[int]) -> None:
        (dossier / FICHIER_ETAPES).write_text(json.dumps({"version": version, "faites": sorted(faites)}), encoding="utf-8")

    def _executer(self, moteur: MoteurManifeste, dossier: Path) -> None:
        etat_final, message_final = EtatInstallation.INSTALLE, "Installation terminée : redémarre MyMaestro pour l'utiliser"
        try:
            dossier.mkdir(parents=True, exist_ok=True)
            (dossier / FICHIER_VERSION).unlink(missing_ok=True)  # réinstallation : le moteur est INCOMPLET jusqu'à la fin (spec §5)
            telechargements = dossier / ".telechargements"
            telechargements.mkdir(parents=True, exist_ok=True)
            self._telecharger(moteur, dossier)
            ctx = ContexteEtape(
                moteur=moteur, dossier=dossier, telechargements=telechargements, annule=self._annule,
                progression=lambda etape, fraction, message: self._evenement(moteur.id, etape, fraction, message, EtatInstallation.EN_COURS.value),
                lancer=self._lancer,
            )
            faites = self._etapes_faites(dossier, moteur.version)
            for indice, etape in enumerate(moteur.etapes):
                if indice in faites:
                    continue
                if self._annule.is_set():
                    raise InstallationAnnulee("installation annulée")
                self._evenement(moteur.id, str(etape.get("type")), None, f"Étape {indice + 1}/{len(moteur.etapes)}", EtatInstallation.EN_COURS.value, force=True)
                executer_etape(etape, ctx)
                faites.add(indice)
                self._noter_etapes(dossier, moteur.version, faites)
            (dossier / FICHIER_VERSION).write_text(
                json.dumps({"id": moteur.id, "version": moteur.version, "installe_le": datetime.now().isoformat(timespec="seconds")}),
                encoding="utf-8",
            )
            (dossier / FICHIER_ETAPES).unlink(missing_ok=True)
            shutil.rmtree(telechargements, ignore_errors=True)  # archives devenues inutiles (~1,3 Go pour l'ensemble des moteurs)
        except InstallationAnnulee as erreur:
            etat_final, message_final = EtatInstallation.INCOMPLET, str(erreur)
        except ErreurInstallation as erreur:
            etat_final, message_final = EtatInstallation.INCOMPLET, str(erreur)
        except Exception as erreur:  # noqa: BLE001 - l'échec est affiché dans l'écran, jamais perdu dans le fil
            journal.exception("installation de %s en erreur", moteur.id)
            etat_final, message_final = EtatInstallation.INCOMPLET, f"erreur inattendue : {erreur}"
        with self._verrou:
            self._en_cours = None
            self._cache_claude = None  # Claude vient peut-être d'être installé : l'état se resonde
            if etat_final is EtatInstallation.INSTALLE:
                self._redemarrage_requis = True
            self._suivi[moteur.id] = {"progression": 1.0 if etat_final is EtatInstallation.INSTALLE else None, "etape": "fin", "message": message_final}
        self._publier({
            "type": "installation", "moteur": moteur.id, "etape": "fin", "progression": 1.0 if etat_final is EtatInstallation.INSTALLE else None,
            "message": message_final, "etat": etat_final.value,
        })

    def _telecharger(self, moteur: MoteurManifeste, dossier: Path) -> None:
        total = sum(f.taille or 0 for f in moteur.fichiers)
        acquis = 0
        for fichier in moteur.fichiers:
            base = acquis

            def progression(recus: int, taille: int | None, *, nom: str = fichier.nom, base: int = base) -> None:
                fraction = (base + recus) / total if total else None
                mo = f"{recus / 1048576:.0f} Mo" + (f" / {taille / 1048576:.0f} Mo" if taille else "")
                self._evenement(moteur.id, "telechargement", fraction, f"Téléchargement de {nom} ({mo})", EtatInstallation.EN_COURS.value)

            telecharger(fichier, self._destination(moteur, fichier.nom, dossier), progression, self._annule)
            acquis += fichier.taille or 0
        if moteur.fichiers:
            self._evenement(moteur.id, "telechargement", 1.0, "Téléchargements terminés", EtatInstallation.EN_COURS.value, force=True)
