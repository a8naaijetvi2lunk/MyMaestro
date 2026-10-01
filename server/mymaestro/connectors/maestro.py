"""Connecteurs réels vers Maestro (spec §4.2) : une instance dédiée sur le port 7870, partagée par le connecteur GPU
`maestro` (analyse audio, Qwen, H3, LTX, FlashVSR, MMAudio) et le connecteur cloud `codex` (gpt-image-2, qui passe
par le processus Maestro).

Pièges tenus : `WGP_GGUF_LLAMACPP_CUDA=0` au lancement ; fenêtre explicite (`sliding_window_size =
video_length`, recouvrement 18 pour H3) et `settings_version: 2.52` à chaque rendu ; chemins de référence absolus ;
mémoire engagée vérifiée avant le démarrage ; un Maestro lancé à la main bloque le démarrage. Chaque sortie vidéo est
contrôlée (nombre d'images, image noire) avant d'être acceptée.
"""

from __future__ import annotations

import http.client
import logging
import os
import shutil
import subprocess
import threading
import time
import urllib.error
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import config
from ..contrat.modeles import EtatMoteur, Voie
from ..outils import controle, ffmpeg, systeme
from ..outils.http import get_json, post_json
from .base import Connecteur, Empreinte, ErreurMoteur, MoteurInterrompu

if TYPE_CHECKING:
    from ..core.file import JobFile

ESPACE = "mymaestro"
STATUTS_FINAUX = ("completed", "failed", "cancelled")
ERREURS_RESEAU = (OSError, ValueError, http.client.HTTPException)  # HTTPError et URLError sont des OSError
NEGATIF_BRUITAGE = "music, melody, singing, speech, voice"
DELAI_RENDU_S = 3 * 3600  # un plan H3 de 10 s prend environ 13 min : trois heures, c'est une panne
DELAI_ANALYSE_S = 1800
MESSAGE_DEMARRAGE_INTERROMPU = "Démarrage de Maestro interrompu par un arrêt"
DELAI_ATTENTE_JOBS_S = 6 * 60  # au moins deux images Codex (1 à 2 min chacune) qui tournent hors du verrou de génération


def _fichier_pid() -> Path:
    """PID du Maestro lancé par MyMaestro : s'il survit à un plantage, le démarrage suivant le reconnaît (et lui seul)."""
    return config.DOSSIER_DONNEES / f"maestro-{config.MAESTRO_PORT}.pid"


def _lancer_maestro(journal: Path) -> subprocess.Popen:
    journal.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "WGP_GGUF_LLAMACPP_CUDA": "0", "SERVER_PORT": str(config.MAESTRO_PORT), "PYTHONIOENCODING": "utf-8"}
    with journal.open("a", encoding="utf-8") as sortie:
        # Nouveau groupe de processus : un Ctrl+C dans la console de MyMaestro ne tue pas Maestro avant la fermeture propre.
        processus = subprocess.Popen(
            [str(config.MAESTRO_PYTHON), "-u", "launch.py"], cwd=config.MAESTRO_APP, env=env, stdout=sortie, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
    fichier = _fichier_pid()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(str(processus.pid), encoding="utf-8")
    return processus


def _arreter_orphelin() -> None:
    """Un MyMaestro tué sans fermeture propre laisse son Maestro dédié sur le port 7870 : on l'arrête (lui seul, reconnu à son
    PID enregistré) au lieu de le prendre pour un Maestro manuel."""
    fichier = _fichier_pid()
    try:
        pid = int(fichier.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    try:
        # Le port 7870 ouvert prouve que notre instance vit encore, donc que son PID n'a pas été réattribué (à un Maestro
        # manuel sur 7860, par exemple) : sans lui, le fichier est seulement périmé.
        if systeme.port_ouvert(config.MAESTRO_PORT) and pid in systeme.processus_maestro():
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            limite = time.monotonic() + 30
            while systeme.port_ouvert(config.MAESTRO_PORT) and time.monotonic() < limite:
                time.sleep(0.5)
            logging.getLogger("mymaestro").warning("Maestro orphelin (PID %s, port %s) arrêté au démarrage", pid, config.MAESTRO_PORT)
    finally:
        fichier.unlink(missing_ok=True)


def _prealables_maestro(*, marge_memoire: bool = True) -> None:
    """Avant de lancer Maestro : notre orphelin arrêté, aucun Maestro manuel, port libre, puis la marge de mémoire engagée.
    `marge_memoire=False` (installeur : préchargement des modèles, aucune génération) ne saute QUE ce dernier contrôle."""
    _arreter_orphelin()
    if systeme.maestro_manuel_actif():
        raise ErreurMoteur("Un Maestro lancé à la main occupe déjà le GPU (port 7860 ou processus lancé depuis le dossier de Maestro) : ferme-le d'abord")
    if systeme.port_ouvert(config.MAESTRO_PORT):
        raise ErreurMoteur(f"Le port {config.MAESTRO_PORT} est déjà pris : une autre instance de Maestro tourne")
    if not marge_memoire:
        return
    try:
        systeme.exiger_marge(config.MARGE_MEMOIRE_MAESTRO_GO)
    except systeme.MemoireInsuffisante as exc:
        raise ErreurMoteur(str(exc)) from None


def _oublier_pid(processus: subprocess.Popen) -> None:
    fichier = _fichier_pid()
    try:
        if int(fichier.read_text(encoding="utf-8").strip()) == processus.pid:
            fichier.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _tuer(processus: subprocess.Popen | None) -> None:
    """Arrête un processus et ses enfants (Maestro lance un sous-processus Python) ; sans effet s'il est déjà mort."""
    if processus is None:
        return
    if processus.poll() is None:
        subprocess.run(["taskkill", "/PID", str(processus.pid), "/T", "/F"], capture_output=True, check=False)
        try:
            processus.wait(30)
        except subprocess.TimeoutExpired:
            processus.kill()
    _oublier_pid(processus)


class ProcessusMaestro:
    """Instance dédiée de Maestro, partagée par les fils GPU et cloud.

    Cycle de vie : arrêté → démarrage (processus lancé, port pas encore ouvert) → prêt. `lance()` dit si un processus
    existe, démarrage compris (l'arbitre doit le voir pour l'arrêter avant Bonsai, la fermeture pour ne pas l'oublier) ;
    `actif()` dit s'il répond. Le démarrage s'attend HORS du verrou, en surveillant la mort du processus et une demande
    d'arrêt ; les autres fils attendent sa fin sur la condition. Avant `release-model` ou l'arrêt, la porte se ferme :
    aucun nouveau job n'est soumis, et ceux en vol (images Codex comprises) finissent, dans la limite de `attente_jobs_s`.
    Tous les jobs de cette instance passent par ici : le compte des jobs en vol suffit, sans interroger /api/v1/jobs.
    """

    def __init__(
        self,
        *,
        url: str = f"http://127.0.0.1:{config.MAESTRO_PORT}",
        lancer: Callable[[], subprocess.Popen | None] | None = None,
        prealables: Callable[[], None] = _prealables_maestro,
        dossier_sorties: Path | None = None,
        journal: Path | None = None,
        delai_demarrage_s: float = 600,
        intervalle_s: float = 3,
        echecs_max: int = 10,
        attente_jobs_s: float = DELAI_ATTENTE_JOBS_S,
    ) -> None:
        self.url = url
        self.journal = journal or config.DOSSIER_JOURNAUX / f"maestro-{datetime.now():%Y%m%d-%H%M%S}.log"
        self._lancer = lancer or (lambda: _lancer_maestro(self.journal))
        self._prealables = prealables
        self.dossier_sorties = dossier_sorties or config.MAESTRO_APP / "outputs"
        self.delai_demarrage_s = delai_demarrage_s
        self.intervalle_s = intervalle_s
        self.echecs_max = echecs_max
        self.attente_jobs_s = attente_jobs_s
        self._condition = threading.Condition(threading.RLock())
        self._processus: subprocess.Popen | None = None
        self._externe = False  # démarré hors de nous (tests : faux Maestro)
        self._phase = "arrete"  # « arrete », « demarrage » ou « pret »
        self._echec: str | None = None
        self._en_vol = 0
        self._porte_fermee = False
        self._generation = 0  # +1 à chaque démarrage et à chaque arrêt : démarrages et jobs antérieurs constatent l'arrêt

    # --- État ---------------------------------------------------------------------------------------

    def lance(self) -> bool:
        with self._condition:
            if self._phase == "demarrage":  # préalables compris : l'arbitre doit voir un démarrage en cours
                return True
            if self._processus is not None:
                return self._processus.poll() is None
            return self._externe

    def actif(self) -> bool:
        with self._condition:
            return self._phase == "pret" and self.lance()

    def accepte(self) -> bool:
        """Prêt et porte ouverte : un job soumis maintenant partirait sans attendre."""
        with self._condition:
            return self.actif() and not self._porte_fermee

    # --- Démarrage et arrêt -----------------------------------------------------------------------------

    def _verifier_generation(self, generation: int) -> None:
        """Sous la condition : un arrêt décidé depuis le début de ce démarrage l'interrompt."""
        if self._generation != generation:
            raise MoteurInterrompu(MESSAGE_DEMARRAGE_INTERROMPU)

    def demarrer(self) -> None:
        processus: subprocess.Popen | None = None
        with self._condition:
            attendu = False
            while self._phase == "demarrage":
                attendu = True
                self._condition.wait()
            if attendu and not self.actif():
                if self._echec:
                    raise ErreurMoteur(self._echec)
                raise MoteurInterrompu(MESSAGE_DEMARRAGE_INTERROMPU)
            if self.actif():
                return
            self._generation += 1
            generation = self._generation
            self._echec = None
            self._processus, self._externe = None, False
            self._phase = "demarrage"
        try:
            self._prealables()  # hors du verrou : la détection des processus (PowerShell) peut prendre jusqu'à 30 s
            with self._condition:
                self._verifier_generation(generation)
                processus = self._lancer()
                self._processus, self._externe = processus, processus is None
            self._attendre_port(processus, generation)
            with self._condition:
                self._verifier_generation(generation)
                self._phase = "pret"
                self._condition.notify_all()
        except BaseException as exc:
            with self._condition:
                if self._generation == generation:  # sinon `arreter()` a déjà tout remis à zéro
                    self._processus, self._externe = None, False
                    self._phase = "arrete"
                    if not isinstance(exc, MoteurInterrompu):
                        self._echec = str(exc)
                self._condition.notify_all()
            _tuer(processus)
            raise

    def _attendre_port(self, processus: subprocess.Popen | None, generation: int) -> None:
        limite = time.monotonic() + self.delai_demarrage_s
        while True:
            if self._generation != generation:
                raise MoteurInterrompu(MESSAGE_DEMARRAGE_INTERROMPU)
            if processus is not None and processus.poll() is not None:
                raise ErreurMoteur(
                    f"Maestro s'est arrêté pendant son démarrage (code {processus.returncode}, journal : {self.journal})"
                )
            try:
                get_json(f"{self.url}/api/v1/jobs", timeout=2)
                return
            except ERREURS_RESEAU:
                pass
            if time.monotonic() > limite:
                raise ErreurMoteur(f"Maestro n'a pas répondu en {self.delai_demarrage_s:.0f} s (journal : {self.journal})")
            time.sleep(min(1.0, self.intervalle_s))

    def _fermer_porte(self, attente_s: float) -> None:
        """Sous la condition : plus aucun nouveau job ; attend ceux en vol, au plus `attente_s`."""
        self._porte_fermee = True
        limite = time.monotonic() + attente_s
        while self._en_vol > 0:
            reste = limite - time.monotonic()
            if reste <= 0:
                break
            self._condition.wait(reste)

    def arreter(self, attente_s: float | None = None) -> None:
        """Arrête l'instance. Un démarrage en cours est interrompu aussitôt ; les jobs en vol ont `attente_s` pour finir
        (`attente_jobs_s` par défaut, 0 à la fermeture de MyMaestro : ils seront repris sans tentative perdue)."""
        with self._condition:
            if self._phase == "demarrage":
                self._generation += 1  # interrompt le démarrage tout de suite
            self._fermer_porte(self.attente_jobs_s if attente_s is None else attente_s)
            self._generation += 1  # les jobs encore en vol constatent l'arrêt
            processus, self._processus, self._externe = self._processus, None, False
            self._phase = "arrete"
            self._echec = None
            self._porte_fermee = False
            self._condition.notify_all()
        _tuer(processus)

    def liberer(self, tentatives: int = 6, pause_s: float = 5) -> None:
        """release-model, porte fermée : Maestro répond 409 tant qu'un job tourne ou que son verrou n'est pas relâché."""
        with self._condition:
            if not self.actif():
                return
            self._fermer_porte(self.attente_jobs_s)
        try:
            for _ in range(tentatives):
                try:
                    post_json(f"{self.url}/api/v1/system/release-model", {}, timeout=180)
                    return
                except urllib.error.HTTPError as exc:
                    if exc.code != 409:
                        raise ErreurMoteur(f"release-model refusé : HTTP {exc.code}") from None
                except ERREURS_RESEAU as exc:
                    raise ErreurMoteur(f"release-model impossible : {exc}") from None
                time.sleep(pause_s)
            raise ErreurMoteur("release-model : Maestro reste occupé")
        finally:
            with self._condition:
                self._porte_fermee = False
                self._condition.notify_all()

    @contextmanager
    def _job_en_vol(self) -> Iterator[int]:
        """Compte un job soumis à Maestro ; attend que la porte se rouvre avant de soumettre. Rend la génération courante :
        si elle change (arrêt par MyMaestro), le suivi du job s'interrompt."""
        with self._condition:
            while self._porte_fermee:
                self._condition.wait()
            if not self.actif():
                raise MoteurInterrompu("Maestro n'est pas prêt (arrêté pendant l'attente)")
            self._en_vol += 1
            generation = self._generation
        try:
            yield generation
        finally:
            with self._condition:
                self._en_vol -= 1
                self._condition.notify_all()

    # --- Jobs ------------------------------------------------------------------------------------------

    def annuler(self, job_id: str) -> None:
        try:
            post_json(f"{self.url}/api/v1/cancel/{job_id}", {}, timeout=30)
        except ERREURS_RESEAU:
            pass

    def _mort(self) -> bool:
        with self._condition:
            if self._processus is not None and self._processus.poll() is not None:
                self._processus = None
                self._phase = "arrete"
                self._condition.notify_all()
                return True
            return False

    def executer_job(self, route: str, corps: dict[str, Any], progression: Callable[[float], None], delai_s: float = DELAI_RENDU_S) -> dict[str, Any]:
        """Soumet un job et suit /status jusqu'à la fin ; lève ErreurMoteur sur tout échec (le job est alors annulé)."""
        with self._job_en_vol() as generation:
            return self._suivre_job(route, corps, progression, delai_s, generation)

    def _suivre_job(
        self, route: str, corps: dict[str, Any], progression: Callable[[float], None], delai_s: float, generation: int
    ) -> dict[str, Any]:
        try:
            job_id = str(post_json(f"{self.url}{route}", corps, timeout=120)["job_id"])
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ErreurMoteur(f"Maestro refuse la requête : HTTP {exc.code} {detail}") from None
        except (*ERREURS_RESEAU, KeyError, TypeError) as exc:
            if self._generation != generation:  # arrêté par MyMaestro pendant la soumission : pas la faute du job
                raise MoteurInterrompu("Maestro arrêté par MyMaestro pendant la soumission du job") from None
            raise ErreurMoteur(f"Maestro injoignable : {exc}") from None
        limite = time.monotonic() + delai_s
        echecs = 0
        while True:
            if self._generation != generation:
                raise MoteurInterrompu("Maestro arrêté par MyMaestro pendant le rendu")
            if self._mort():
                raise ErreurMoteur(f"Maestro s'est arrêté pendant le rendu (journal : {self.journal})")
            if time.monotonic() > limite:
                self.annuler(job_id)
                raise ErreurMoteur(f"Rendu trop long (plus de {delai_s / 60:.0f} min) : annulé")
            try:
                statut = get_json(f"{self.url}/api/v1/status/{job_id}", timeout=30)
                echecs = 0
            except ERREURS_RESEAU as exc:
                echecs += 1
                if echecs >= self.echecs_max:
                    self.annuler(job_id)
                    raise ErreurMoteur(f"Suivi du job Maestro perdu ({exc}) : job annulé avant de continuer") from None
                time.sleep(self.intervalle_s)
                continue
            etat = statut.get("status")
            if etat in STATUTS_FINAUX:
                if etat != "completed":
                    cause = statut.get("error") or statut.get("oom_info") or statut.get("message") or "sans détail"
                    raise ErreurMoteur(f"Maestro : {etat} — {cause}")
                progression(1.0)
                return statut
            avance = statut.get("progress")
            if isinstance(avance, (int, float)) and not isinstance(avance, bool):
                valeur = float(avance) / 100 if avance > 1 else float(avance)
                progression(max(0.0, min(1.0, valeur)))
            time.sleep(self.intervalle_s)

    def sortie(self, statut: Mapping[str, Any], extensions: tuple[str, ...]) -> Path:
        """Fichier produit par un job, cherché par son NOM EXACT (jamais par préfixe) dans le dossier des sorties."""
        noms = [str(nom) for nom in statut.get("output_files") or []]
        nom = next((n for n in noms if n.lower().endswith(extensions)), None)
        if nom is None:
            raise ErreurMoteur(f"Maestro n'a produit aucun fichier {' ou '.join(extensions)}")
        chemin = Path(nom)
        if chemin.is_absolute() and chemin.is_file():
            return chemin
        direct = self.dossier_sorties / ESPACE / chemin.name
        if direct.is_file():
            return direct
        candidats = [p for p in self.dossier_sorties.rglob(chemin.name) if p.name == chemin.name]
        if not candidats:
            raise ErreurMoteur(f"Sortie introuvable : {chemin.name}")
        return max(candidats, key=lambda p: p.stat().st_mtime)

    def analyser_audio(self, corps: dict[str, Any]) -> dict[str, Any]:
        with self._job_en_vol():
            try:
                resultat = post_json(f"{self.url}/api/v1/audio/analyze", corps, timeout=DELAI_ANALYSE_S)
            except urllib.error.HTTPError as exc:
                raise ErreurMoteur(f"Analyse refusée : HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:300]}") from None
            except ERREURS_RESEAU as exc:
                raise ErreurMoteur(f"Analyse impossible : {exc}") from None
        if not isinstance(resultat, dict):
            raise ErreurMoteur("Analyse : réponse inattendue de Maestro")
        return resultat


# --- Corps des requêtes ------------------------------------------------------------------------------


def corps_video(d: Mapping[str, Any]) -> dict[str, Any]:
    moteur = str(d["moteur"])
    images = int(d["images"])
    corps: dict[str, Any] = {
        "model_type": moteur,
        "prompt": str(d["prompt"]),
        "image_mode": 0,
        "image_prompt_type": "S",
        "image_start": str(d["image_depart"]),
        "resolution": f"{int(d['largeur'])}x{int(d['hauteur'])}",
        "video_length": images,
        "seed": int(d.get("graine") or 42),
        "settings_version": 2.52,
        "generation_mode": "video",
        "repeat_generation": 1,
        "negative_prompt": "",
        "workspace": ESPACE,
        # Sans fenêtre explicite, Maestro prend la fenêtre générique de WanGP (129) : H3 sortirait 141 images.
        "sliding_window_size": images,
    }
    if moteur == "minimax_h3":
        corps.update(num_inference_steps=20, guidance_scale=1.0, sliding_window_overlap=18)
    else:
        corps.update(num_inference_steps=8, guidance_scale=1)
    if d.get("audio"):
        corps.update(audio_prompt_type="A", audio_guide=str(d["audio"]))
    return corps


def corps_image(d: Mapping[str, Any], modele: str) -> dict[str, Any]:
    references = [str(Path(r)) for r in d.get("references") or [] if Path(str(r)).is_absolute() and Path(str(r)).is_file()]
    corps: dict[str, Any] = {
        "model_type": modele,
        "prompt": str(d["prompt"]),
        "image_mode": 1,
        "image_prompt_type": "",
        "num_inference_steps": 8,
        "guidance_scale": 1,
        "resolution": f"{int(d['largeur'])}x{int(d['hauteur'])}",
        "seed": 42,
        "settings_version": 2.52,
        "workspace": ESPACE,
        "video_prompt_type": "KI" if references else "",
    }
    if references:
        corps["image_refs"] = references
    return corps


def corps_bruitage(d: Mapping[str, Any]) -> dict[str, Any]:
    prompt = str(d.get("prompt") or "")
    return {
        "model_type": "mmaudio_v2",
        "sfx_mode": True,
        "prompt": prompt,
        "MMAudio_prompt": prompt,
        "MMAudio_neg_prompt": NEGATIF_BRUITAGE,
        "seed": 42,
        "duration_seconds": round(float(d.get("duree_s") or 5.0), 3),
        "_mmaudio_variant": "v2",
        "guidance_scale": 4.5,
        "sfx_text_weight": 1.0,
        "video_guide": str(d["video"]),
        "workspace": ESPACE,
    }


def _copier(source: Path, destination: str) -> Path:
    cible = Path(destination)
    cible.parent.mkdir(parents=True, exist_ok=True)
    provisoire = cible.with_name(f"{cible.stem}.partiel{cible.suffix}")
    shutil.copyfile(source, provisoire)
    provisoire.replace(cible)
    return cible


def faire_image(processus: ProcessusMaestro, job: JobFile, modele: str, progression: Callable[[float], None]) -> dict[str, Any]:
    d = job.donnees
    statut = processus.executer_job("/api/v1/generate", corps_image(d, modele), progression)
    _copier(processus.sortie(statut, (".png", ".jpg", ".jpeg", ".webp")), str(d["destination"]))
    return {"fichier": str(d["fichier"])}


# --- Connecteurs ------------------------------------------------------------------------------------


class ConnecteurMaestro(Connecteur):
    """Moteur GPU `maestro` ; son état suit le processus partagé (démarré par Codex, il n'est plus « arrêté »)."""

    nom = "maestro"
    voie = Voie.GPU

    def __init__(self, processus: ProcessusMaestro, empreinte: Empreinte) -> None:
        self.processus = processus
        self.empreinte = empreinte
        self._etat = EtatMoteur.ARRETE
        super().__init__()

    @property
    def etat(self) -> EtatMoteur:
        if not self.processus.lance():  # un Maestro en démarrage compte : l'arbitre doit pouvoir l'arrêter
            return EtatMoteur.ARRETE
        return EtatMoteur.DEMARRE if self._etat is EtatMoteur.ARRETE else self._etat

    @etat.setter
    def etat(self, valeur: EtatMoteur) -> None:
        self._etat = valeur

    def demarrer(self) -> None:
        self.processus.demarrer()
        self.etat = EtatMoteur.DEMARRE

    def arreter(self) -> None:
        self.processus.arreter()  # porte fermée : une image Codex en cours finit avant l'arrêt
        self.etat = EtatMoteur.ARRETE

    def arreter_sans_attendre(self) -> None:
        self.processus.arreter(attente_s=0)  # fermeture de MyMaestro : les jobs interrompus sont repris sans tentative perdue
        self.etat = EtatMoteur.ARRETE

    def liberer(self) -> None:
        self.processus.liberer()
        if self._etat is EtatMoteur.CHARGE:
            self.etat = EtatMoteur.DEMARRE

    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        traitements = {
            "analyse": self._analyse,
            "images.plan": self._image,
            "video.plan": self._video,
            "postprod.flashvsr": self._flashvsr,
            "bruitage.plan": self._bruitage,
        }
        tache = str(job.donnees.get("tache", ""))
        traitement = traitements.get(tache)
        if traitement is None:
            raise ErreurMoteur(f"Tâche inconnue pour Maestro : {tache}")
        self.demarrer()  # idempotent et sérialisé : un 2e fil attend que le port soit ouvert
        self.etat = EtatMoteur.CHARGE
        return traitement(job, progression)

    def _analyse(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        d = job.donnees
        paroles = str(d.get("paroles") or "")
        brut = self.processus.analyser_audio(
            {"audio_path": str(d["chanson"]), "transcribe": True, "extract_vocals": True, "lyrics_hint": paroles or None}
        )
        progression(1.0)
        return {"brut": brut, "paroles": paroles}

    def _image(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        return faire_image(self.processus, job, str(job.modele), progression)

    def _video(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        d = job.donnees
        statut = self.processus.executer_job("/api/v1/generate", corps_video(d), progression)
        cible = _copier(self.processus.sortie(statut, (".mp4",)), str(d["destination"]))
        verdict = controle.controler_video(cible, int(d["images"]))
        if not verdict.valide:
            raise ErreurMoteur(str(verdict.motif))
        return {"fichier": str(d["fichier"]), "images": verdict.images, "luminance": verdict.luminance}

    def _flashvsr(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        d = job.donnees
        source = Path(str(d["source"]))
        attendues = ffmpeg.sonder(source).get("images") if source.is_file() else None
        corps = {"video_path": str(source), "method": "flashvsr2", "workspace": ESPACE}
        statut = self.processus.executer_job("/api/v1/tools/upscale", corps, progression)
        cible = _copier(self.processus.sortie(statut, (".mp4",)), str(d["destination"]))
        verdict = controle.controler_video(cible, attendues)
        if not verdict.valide:
            raise ErreurMoteur(str(verdict.motif))
        return {"fichier": str(d["fichier"]), "images": verdict.images}

    def _bruitage(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        d = job.donnees
        statut = self.processus.executer_job("/api/v1/generate", corps_bruitage(d), progression)
        source = self.processus.sortie(statut, (".mp4", ".wav"))
        cible = Path(str(d["destination"]))
        cible.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [ffmpeg.trouver("ffmpeg"), "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "2", "-ar", "48000",
                 "-c:a", "pcm_s16le", str(cible)],
                check=True, capture_output=True, timeout=120,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ErreurMoteur(f"Extraction du son du bruitage impossible : {exc}") from None
        return {"fichier": str(d["fichier"])}


class ConnecteurCodex(Connecteur):
    """Images gpt-image-2 par la CLI Codex, à travers le processus Maestro (voie cloud). Si Maestro ne tourne pas, le
    démarrer prend le GPU : Codex attend alors que Bonsai l'ait libéré (spec §6.3)."""

    nom = "codex"
    voie = Voie.CLOUD
    empreinte = Empreinte(vram_mo=0, residuelle_mo=0)

    def __init__(self, processus: ProcessusMaestro, gpu_libre: Callable[[], bool]) -> None:
        super().__init__()
        self.processus = processus
        self._gpu_libre = gpu_libre

    def peut_executer(self) -> bool:
        # Maestro prêt et porte ouverte, ou pas encore lancé et GPU libre ; en démarrage ou en fermeture, on attend.
        return self.processus.accepte() or (not self.processus.lance() and self._gpu_libre())

    def attend_le_gpu(self) -> bool:
        return not self.processus.lance() and not self._gpu_libre()

    def demarrer(self) -> None:
        self.etat = EtatMoteur.DEMARRE

    def arreter(self) -> None:
        self.etat = EtatMoteur.ARRETE

    def arreter_sans_attendre(self) -> None:
        self.processus.arreter(attente_s=0)  # processus partagé : il ne survit pas à MyMaestro, même si `maestro` est simulé
        self.etat = EtatMoteur.ARRETE

    def liberer(self) -> None:
        return None

    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        if job.donnees.get("tache") != "images.plan":
            raise ErreurMoteur(f"Tâche inconnue pour Codex : {job.donnees.get('tache')}")
        if not self.processus.lance() and not self._gpu_libre():
            raise MoteurInterrompu("Bonsai occupe le GPU : l'image Codex attend son arrêt")
        self.processus.demarrer()
        return faire_image(self.processus, job, "codex_imagegen", progression)
