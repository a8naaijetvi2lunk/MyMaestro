"""Ordonnanceur : applique les décisions de l'arbitre sur la voie GPU et sert la voie cloud.

Une étape exécute au plus un job. `vider()` enchaîne les étapes sans fil (tests, pas à pas) ;
`lancer()` fait tourner un fil GPU et `fils_cloud` fils cloud jusqu'à `arreter()`. Tout
changement est publié sur le bus, que l'API relaie en SSE.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..connectors.base import Connecteur, MoteurInterrompu
from ..connectors.registre import message_non_installe
from ..contrat.modeles import EtatFile, EtatMoteur, StatutJob, Voie
from . import arbitre
from .empreintes import VRAM_BUREAU_MO, VRAM_TOTALE_MO
from .file import File, JobFile


class Bus:
    """Diffusion des événements aux abonnés (une file d'attente par abonné)."""

    def __init__(self, capacite: int = 1000) -> None:
        self._abonnes: list[queue.Queue] = []
        self._verrou = threading.Lock()
        self._capacite = capacite

    def abonner(self) -> queue.Queue:
        abonnement: queue.Queue = queue.Queue(maxsize=self._capacite)
        with self._verrou:
            self._abonnes.append(abonnement)
        return abonnement

    def desabonner(self, abonnement: queue.Queue) -> None:
        with self._verrou:
            if abonnement in self._abonnes:
                self._abonnes.remove(abonnement)

    def publier(self, evenement: dict[str, Any]) -> None:
        with self._verrou:
            abonnes = list(self._abonnes)
        for abonnement in abonnes:
            try:
                abonnement.put_nowait(evenement)
            except queue.Full:
                pass  # abonné trop lent : il rattrapera l'état par GET /api/file


class Ordonnanceur:
    def __init__(
        self,
        file: File,
        connecteurs: Mapping[str, Connecteur],
        *,
        bus: Bus | None = None,
        vram_totale_mo: int = VRAM_TOTALE_MO,
        vram_bureau_mo: int = VRAM_BUREAU_MO,
        fils_cloud: int = 2,
        pause_s: float = 0.5,
        simule_autorise: bool = True,
    ) -> None:
        """`simule_autorise` : faux hors mode démo (figé à la construction) → un job sur un moteur simulé échoue au lieu de
        s'exécuter. Vrai par défaut : connecteurs injectés (tests) ou mode démo."""
        self.simule_autorise = simule_autorise
        self.file = file
        self.connecteurs = dict(connecteurs)
        self.bus = bus or Bus()
        self.vram_totale_mo = vram_totale_mo
        self.vram_bureau_mo = vram_bureau_mo
        self.fils_cloud = fils_cloud
        self.pause_s = pause_s
        self.dernier_modele: str | None = None
        self._arret = threading.Event()
        self._pause = threading.Event()
        self._fils: list[threading.Thread] = []
        self._verrou_gpu = threading.Lock()
        self._echec_liberation: str | None = None  # dernier échec d'arrêt de Bonsai déjà publié (pas de répétition)
        self._gpu_libere = False  # Bonsai vient d'être arrêté pour le cloud : `vider()` retente la voie cloud

    def _publier(self, type_: str, **donnees: Any) -> None:
        self.bus.publier({"type": type_, **donnees})

    def etape_gpu(self) -> JobFile | None:
        if self._arret.is_set():  # fermeture : on ne réserve plus rien
            return None
        with self._verrou_gpu:
            decision = arbitre.choisir(
                self.file.eligibles(Voie.GPU), self.connecteurs, self.dernier_modele, self.vram_totale_mo, self.vram_bureau_mo
            )
            if decision is None:
                self._liberer_gpu_pour_le_cloud()
                return None
            return self._executer(decision.job, decision.preparations)

    def _liberer_gpu_pour_le_cloud(self) -> None:
        """Aucun job GPU à servir : Bonsai inactif s'arrête si un job cloud (Codex) n'attend que la libération du GPU."""
        bonsai = self.connecteurs.get("bonsai")
        if bonsai is None or bonsai.etat is EtatMoteur.ARRETE:
            return
        if any(self.connecteurs[job.connecteur].attend_le_gpu() for job in self.file.eligibles(Voie.CLOUD)):
            try:
                bonsai.arreter()
            except Exception as exc:  # noqa: BLE001 — l'échec est publié UNE fois tant qu'il se répète, puis on retente
                message = f"Arrêt de Bonsai impossible : {type(exc).__name__}: {exc}"
                if message != self._echec_liberation:
                    self._echec_liberation = message
                    self._publier("erreur_ordonnanceur", message=message)
                return
            self._echec_liberation = None
            self._gpu_libere = True
            self._publier("preparation", connecteur="bonsai", action="arreter")

    def etape_cloud(self) -> JobFile | None:
        for job in self.file.eligibles(Voie.CLOUD):
            if self._arret.is_set():  # fermeture : on ne réserve plus rien (liste lue avant l'arrêt)
                return None
            connecteur = self.connecteurs[job.connecteur]
            if not connecteur.peut_executer():
                continue  # il attend (Codex pendant que Bonsai tient le GPU) : pas de tentative perdue
            # Démarrage via les préparations : dans le try, après la réservation, un refus compte comme une tentative.
            preparations = (arbitre.Preparation(job.connecteur, "demarrer"),) if connecteur.etat is EtatMoteur.ARRETE else ()
            execute = self._executer(job, preparations)
            if execute is not None:
                return execute
        return None

    def _executer(self, job: JobFile, preparations: Sequence[Any] = ()) -> JobFile | None:
        if not self.file.demarrer(job.id):
            return None  # déjà pris par un autre fil ou annulé entre-temps
        if self._arret.is_set():  # fermeture en cours : rien ne démarre, le job repart en file intact
            self._remettre(job, "fermeture de MyMaestro : remis en file")
            return None
        connecteur = self.connecteurs[job.connecteur]
        if connecteur.simule and not self.simule_autorise:
            # Hors mode démo, un moteur simulé n'est pas installé : aucun job ne s'y exécute (un résultat fabriqué passerait pour vrai).
            message = message_non_installe(job.connecteur)
            if self.file.abandonner(job.id, message):
                self._publier("job", id=job.id, statut=StatutJob.ECHEC.value, erreur=message)
            return self.file.lire(job.id)
        self._publier("job", id=job.id, statut=StatutJob.EN_COURS.value)

        def progression(valeur: float) -> None:
            self.file.progresser(job.id, valeur)
            self._publier("progression", id=job.id, valeur=valeur)

        try:
            # Préparations de l'arbitre dans le try : un refus de démarrer compte comme une tentative (spec §7).
            for preparation in preparations:
                getattr(self.connecteurs[preparation.connecteur], preparation.action)()
                self._publier("preparation", connecteur=preparation.connecteur, action=preparation.action)
            resultat = connecteur.executer(job, progression)
            self.file.terminer(job.id, resultat)
        except MoteurInterrompu as exc:  # arrêté par MyMaestro : pas de libération, pas de tentative perdue
            self._remettre(job, str(exc))
        except Exception as exc:  # noqa: BLE001 — tout échec moteur est consigné, la file continue
            if self._arret.is_set():  # l'échec vient de la fermeture de MyMaestro, pas du job
                self._remettre(job, f"fermeture de MyMaestro : remis en file ({type(exc).__name__}: {exc})")
                return self.file.lire(job.id)
            if connecteur.voie is Voie.GPU:
                try:
                    connecteur.liberer()  # nouvelle tentative après libération de la VRAM (spec §7)
                except Exception:  # noqa: BLE001
                    pass
            statut = self.file.echouer(job.id, f"{type(exc).__name__}: {exc}")
            self._publier("job", id=job.id, statut=statut.value, erreur=str(exc))
        else:
            if connecteur.voie is Voie.GPU:
                self.dernier_modele = job.modele
            self._publier("job", id=job.id, statut=StatutJob.TERMINE.value)
        return self.file.lire(job.id)

    def _remettre(self, job: JobFile, motif: str) -> None:
        if self.file.remettre(job.id, motif):
            self._publier("job", id=job.id, statut=StatutJob.EN_FILE.value)

    def vider(self, limite: int = 1000) -> int:
        """Enchaîne les étapes (cloud d'abord, puis GPU) jusqu'à épuisement ; renvoie le nombre d'étapes."""
        etapes = 0
        while etapes < limite:
            job = self.etape_cloud() or self.etape_gpu()
            if job is None:
                if self._gpu_libere:
                    self._gpu_libere = False
                    continue
                break
            etapes += 1
        return etapes

    def _boucle(self, etape: Callable[[], JobFile | None]) -> None:
        while not self._arret.is_set():
            if self._pause.is_set():
                self._arret.wait(self.pause_s)
                continue
            try:
                job = etape()
            except Exception as exc:  # noqa: BLE001 — la boucle ne doit jamais mourir
                self._publier("erreur_ordonnanceur", message=f"{type(exc).__name__}: {exc}")
                job = None
            if job is None:
                self._arret.wait(self.pause_s)

    def lancer(self) -> None:
        """Démarre les fils de la file, ou lève la pause s'ils tournent déjà."""
        self._pause.clear()
        if not self.fils_actifs:
            self._arret.clear()
            self._fils = [threading.Thread(target=self._boucle, args=(self.etape_gpu,), name="file-gpu", daemon=True)]
            self._fils += [
                threading.Thread(target=self._boucle, args=(self.etape_cloud,), name=f"file-cloud-{i}", daemon=True)
                for i in range(self.fils_cloud)
            ]
            for fil in self._fils:
                fil.start()
        self._publier("file", en_marche=True)

    def mettre_en_pause(self) -> None:
        """Le job en cours se termine ; aucun autre ne démarre avant `lancer()`."""
        self._pause.set()
        self._publier("file", en_marche=False)

    def arreter(self, delai_s: float = 10) -> None:
        self._arret.set()
        for fil in self._fils:
            fil.join(delai_s)
        self._fils = []
        self._publier("file", en_marche=False)

    @property
    def fils_actifs(self) -> bool:
        return any(fil.is_alive() for fil in self._fils)

    @property
    def en_marche(self) -> bool:
        return self.fils_actifs and not self._pause.is_set()

    def etat(self) -> EtatFile:
        occupe = arbitre.moteur_charge(self.connecteurs) or next(
            (nom for nom, c in self.connecteurs.items() if c.voie is Voie.GPU and c.etat is not EtatMoteur.ARRETE), None
        )
        return EtatFile(
            gpu_occupe_par=occupe,
            en_marche=self.en_marche,
            vram_totale_mo=self.vram_totale_mo,
            jobs=[job.public() for job in self.file.lister()],
            connecteurs=[connecteur.etat_public() for connecteur in self.connecteurs.values()],
        )
