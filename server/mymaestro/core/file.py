"""File persistante des jobs (SQLite) : voie GPU (un job à la fois) et voie cloud (en parallèle).

Tentatives : un job en échec est remis en file tant que ses tentatives restent sous
`tentatives_max` (2 : « nouvelle tentative, puis échec », spec §7). Au démarrage,
`reprendre_apres_crash` remet en file les jobs restés « en_cours » : jamais de statut fantôme.
Prérequis : `donnees["apres"]` liste les jobs qui doivent être terminés avant celui-ci ; si l'un
échoue, est annulé ou n'existe pas, le job est annulé au lieu de tourner sur une entrée manquante.

Rappels : `_verrou_fin` (réentrant) couvre transition finale ET rappels dans terminer, echouer, annuler,
eligibles et reprendre_apres_crash, pour que la fin d'un lancement ne soit vue qu'une fois. Ordre des verrous :
_verrou_gpu → _verrou_fin → Base._verrou. Ne jamais appeler ces méthodes depuis une base.transaction() ouverte ;
un rappel n'appelle jamais une méthode de l'Ordonnanceur qui prend _verrou_gpu.

Verrous de module (Director) : ils se prennent AVANT `_verrou_fin` (ordre complet : verrous de module du Director
→ _verrou_gpu → _verrou_fin → Base._verrou), avant d'ouvrir une base.transaction(), et ne sont jamais tenus pendant
un appel à terminer, echouer, annuler ou eligibles. Il s'agit de `_VERROU_LANCEMENT` (video.py, un seul lancement de
la phase vidéo), `_VERROU_PRISES` (timeline.py, choix de prise ou de sortie, nettoyage et lancement d'un export) et
`_VERROU_LANCEMENT_ACTIONS` (actions.py, un seul « Lancer la file » à la fois).
"""

from __future__ import annotations

import functools
import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ..contrat.modeles import Job, Regime, StatutJob, Voie
from .db import Base
from .depot import horodatage, nouvel_id

JOURNAL = logging.getLogger("mymaestro.file")

MOTIF_INTERRUPTION = "interrompu par un arrêt de MyMaestro"


@dataclass
class JobFile:
    id: str
    voie: Voie
    connecteur: str
    modele: str | None
    projet_id: str | None
    phase: str | None
    ordre: int
    regime: Regime
    donnees: dict[str, Any]
    statut: StatutJob
    tentatives: int
    erreur: str | None
    resultat: dict[str, Any] | None
    libelle: str
    progression: float
    demarre_le: str | None = None
    termine_le: str | None = None

    @property
    def apres(self) -> list[str]:
        return list(self.donnees.get("apres", []))

    def public(self) -> Job:
        return Job(
            id=self.id, voie=self.voie, connecteur=self.connecteur, modele=self.modele, statut=self.statut,
            tentatives=self.tentatives, progression=self.progression, libelle=self.libelle, erreur=self.erreur,
            phase=self.phase, ordre=self.ordre, regime=self.regime, projet_id=self.projet_id,
        )


def _sous_verrou_fin(methode):
    """Exécute la méthode (transition finale + rappels) sous `File._verrou_fin`."""

    @functools.wraps(methode)
    def enveloppe(self, *args, **kwargs):
        with self._verrou_fin:
            return methode(self, *args, **kwargs)

    return enveloppe


def _depuis_ligne(ligne: sqlite3.Row) -> JobFile:
    return JobFile(
        id=ligne["id"], voie=Voie(ligne["voie"]), connecteur=ligne["connecteur"], modele=ligne["modele"],
        projet_id=ligne["projet_id"], phase=ligne["phase"], ordre=ligne["ordre"], regime=Regime(ligne["regime"]),
        donnees=json.loads(ligne["donnees"]), statut=StatutJob(ligne["statut"]), tentatives=ligne["tentatives"],
        erreur=ligne["erreur"], resultat=json.loads(ligne["resultat"]) if ligne["resultat"] else None,
        libelle=ligne["libelle"], progression=ligne["progression"],
        demarre_le=ligne["demarre_le"], termine_le=ligne["termine_le"],
    )


class File:
    def __init__(self, base: Base, tentatives_max: int = 2) -> None:
        self.base = base
        self.tentatives_max = tentatives_max
        self.rappels: list[Callable[[JobFile], None]] = []
        self._verrou_fin = threading.RLock()

    def ajouter(
        self,
        *,
        voie: Voie,
        connecteur: str,
        modele: str | None = None,
        projet_id: str | None = None,
        phase: str | None = None,
        ordre: int = 0,
        regime: Regime = Regime.PHASES,
        donnees: dict[str, Any] | None = None,
        libelle: str = "",
    ) -> str:
        job_id = nouvel_id("job")
        with self.base.transaction() as cx:
            cx.execute(
                "INSERT INTO jobs (id, voie, connecteur, modele, projet_id, donnees, statut, cree_le, phase, ordre, regime, libelle) "
                "VALUES (?, ?, ?, ?, ?, ?, 'en_file', ?, ?, ?, ?, ?)",
                (
                    job_id, Voie(voie).value, connecteur, modele, projet_id, json.dumps(donnees or {}, ensure_ascii=False),
                    horodatage(), phase, ordre, Regime(regime).value, libelle,
                ),
            )
        return job_id

    def _signaler(self, ids: Iterable[str]) -> None:
        """Rappels de fin de job, hors transaction ; un rappel en erreur est journalisé, les autres passent."""
        for job_id in ids:
            job = self.lire(job_id)
            if job is None:
                continue
            for rappel in list(self.rappels):
                try:
                    rappel(job)
                except Exception:  # noqa: BLE001 — un module fautif ne doit pas bloquer la file
                    JOURNAL.exception("rappel de fin de job en erreur (%s)", job_id)

    def lister_lancement(self, lancement: str) -> list[JobFile]:
        with self.base.transaction() as cx:
            lignes = cx.execute(
                "SELECT * FROM jobs WHERE json_extract(donnees, '$.lancement') = ? ORDER BY ordre, rowid", (lancement,)
            ).fetchall()
        return [_depuis_ligne(ligne) for ligne in lignes]

    def lister_projet(self, projet_id: str) -> list[JobFile]:
        with self.base.transaction() as cx:
            lignes = cx.execute("SELECT * FROM jobs WHERE projet_id = ? ORDER BY ordre, rowid", (projet_id,)).fetchall()
        return [_depuis_ligne(ligne) for ligne in lignes]

    def lire(self, job_id: str) -> JobFile | None:
        with self.base.transaction() as cx:
            ligne = cx.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _depuis_ligne(ligne) if ligne else None

    def ordre_max(self, regime: Regime) -> int:
        """Ordre le plus élevé des jobs d'un régime (0 s'il n'y en a aucun) : un nouveau lot se place à la suite."""
        with self.base.transaction() as cx:
            ligne = cx.execute("SELECT COALESCE(MAX(ordre), 0) FROM jobs WHERE regime = ?", (Regime(regime).value,)).fetchone()
        return int(ligne[0])

    def lister(self, limite: int = 200) -> list[JobFile]:
        with self.base.transaction() as cx:
            # Tête de file d'abord (en cours, puis en file par ordre), puis l'historique du plus récent
            # au plus ancien ; rendu dans l'ordre de la file.
            lignes = cx.execute(
                "SELECT * FROM jobs WHERE rowid IN ("
                "  SELECT rowid FROM jobs ORDER BY statut = 'en_cours' DESC, statut = 'en_file' DESC,"
                "  CASE WHEN statut IN ('en_file', 'en_cours') THEN ordre END,"
                "  CASE WHEN statut IN ('en_file', 'en_cours') THEN rowid ELSE -rowid END LIMIT ?"
                ") ORDER BY ordre, rowid",
                (limite,),
            ).fetchall()
        return [_depuis_ligne(ligne) for ligne in lignes]

    @_sous_verrou_fin
    def eligibles(self, voie: Voie) -> list[JobFile]:
        """Jobs en file de la voie dont tous les prérequis sont terminés (dans l'ordre)."""
        annules: list[str] = []
        with self.base.transaction() as cx:
            lignes = cx.execute(
                "SELECT * FROM jobs WHERE voie = ? AND statut = 'en_file' ORDER BY ordre, rowid", (Voie(voie).value,)
            ).fetchall()
            statuts = {ligne["id"]: ligne["statut"] for ligne in cx.execute("SELECT id, statut FROM jobs")}
            prets: list[JobFile] = []
            for ligne in lignes:
                job = _depuis_ligne(ligne)
                etats = [statuts.get(prerequis) for prerequis in job.apres]
                if any(etat in ("echec", "annule", None) for etat in etats):
                    cx.execute(
                        "UPDATE jobs SET statut = 'annule', erreur = ?, termine_le = ? WHERE id = ?",
                        ("prérequis en échec, annulé ou introuvable", horodatage(), job.id),
                    )
                    statuts[job.id] = "annule"
                    annules.append(job.id)
                elif all(etat == "termine" for etat in etats):
                    prets.append(job)
        self._signaler(annules)
        return prets

    def demarrer(self, job_id: str) -> bool:
        """Réserve le job (en_file → en_cours) ; False s'il n'était plus en file (autre fil, annulation)."""
        with self.base.transaction() as cx:
            curseur = cx.execute(
                "UPDATE jobs SET statut = 'en_cours', tentatives = tentatives + 1, demarre_le = ?, progression = 0 "
                "WHERE id = ? AND statut = 'en_file'",
                (horodatage(), job_id),
            )
        return curseur.rowcount == 1

    def progresser(self, job_id: str, valeur: float) -> None:
        with self.base.transaction() as cx:
            cx.execute(
                "UPDATE jobs SET progression = ? WHERE id = ? AND statut = 'en_cours'", (min(1.0, max(0.0, float(valeur))), job_id)
            )

    @_sous_verrou_fin
    def terminer(self, job_id: str, resultat: dict[str, Any] | None = None) -> None:
        with self.base.transaction() as cx:
            cx.execute(
                "UPDATE jobs SET statut = 'termine', progression = 1, resultat = ?, erreur = NULL, termine_le = ? WHERE id = ?",
                (json.dumps(resultat, ensure_ascii=False) if resultat is not None else None, horodatage(), job_id),
            )
        self._signaler([job_id])

    @_sous_verrou_fin
    def echouer(self, job_id: str, erreur: str) -> StatutJob:
        """Consigne l'échec : remis en file s'il reste une tentative, sinon échec définitif."""
        with self.base.transaction() as cx:
            ligne = cx.execute("SELECT tentatives FROM jobs WHERE id = ?", (job_id,)).fetchone()
            statut = StatutJob.EN_FILE if ligne["tentatives"] < self.tentatives_max else StatutJob.ECHEC
            cx.execute(
                "UPDATE jobs SET statut = ?, erreur = ?, termine_le = ? WHERE id = ?",
                (statut.value, erreur, horodatage() if statut is StatutJob.ECHEC else None, job_id),
            )
        if statut is StatutJob.ECHEC:
            self._signaler([job_id])
        return statut

    @_sous_verrou_fin
    def annuler(self, job_id: str) -> bool:
        with self.base.transaction() as cx:
            curseur = cx.execute(
                "UPDATE jobs SET statut = 'annule', termine_le = ? WHERE id = ? AND statut = 'en_file'", (horodatage(), job_id)
            )
        annule = curseur.rowcount == 1
        if annule:
            self._signaler([job_id])
        return annule

    def relancer(self, job_id: str) -> bool:
        """Relance manuelle d'un job en échec ou annulé : remis en file avec des tentatives neuves.
        Les jobs qui en dépendaient et ont été annulés ne sont pas relancés avec lui."""
        with self.base.transaction() as cx:
            curseur = cx.execute(
                "UPDATE jobs SET statut = 'en_file', tentatives = 0, erreur = NULL, progression = 0, termine_le = NULL "
                "WHERE id = ? AND statut IN ('echec', 'annule')",
                (job_id,),
            )
        return curseur.rowcount == 1

    @_sous_verrou_fin
    def reprendre_apres_crash(self) -> int:
        """Jobs restés « en_cours » après un arrêt brutal : remis en file, ou échec s'ils avaient épuisé leurs tentatives."""
        en_echec: list[str] = []
        with self.base.transaction() as cx:
            lignes = cx.execute("SELECT id, tentatives FROM jobs WHERE statut = 'en_cours'").fetchall()
            for ligne in lignes:
                if ligne["tentatives"] >= self.tentatives_max:
                    cx.execute(
                        "UPDATE jobs SET statut = 'echec', erreur = ?, termine_le = ? WHERE id = ?",
                        (MOTIF_INTERRUPTION, horodatage(), ligne["id"]),
                    )
                    en_echec.append(ligne["id"])
                else:
                    cx.execute(
                        "UPDATE jobs SET statut = 'en_file', erreur = ? WHERE id = ?",
                        (f"{MOTIF_INTERRUPTION}, remis en file", ligne["id"]),
                    )
        self._signaler(en_echec)
        return len(lignes)

    def suspendre_en_cours(self) -> int:
        """Arrêt propre de MyMaestro : les jobs en cours repartent en file SANS tentative perdue (l'arrêt n'est pas
        leur faute ; un vrai plantage, lui, passe par `reprendre_apres_crash` et compte la tentative)."""
        with self.base.transaction() as cx:
            return cx.execute(
                "UPDATE jobs SET statut = 'en_file', tentatives = MAX(tentatives - 1, 0), erreur = ? WHERE statut = 'en_cours'",
                ("interrompu par l'arrêt de MyMaestro, remis en file",),
            ).rowcount

    @_sous_verrou_fin
    def abandonner(self, job_id: str, erreur: str) -> bool:
        """Échec immédiat d'un job réservé, SANS tentative perdue ni nouvelle tentative automatique (le moteur n'est pas
        installé : réessayer tout de suite ne servirait à rien). « Relancer » le remet en file avec des tentatives neuves."""
        with self.base.transaction() as cx:
            curseur = cx.execute(
                "UPDATE jobs SET statut = 'echec', tentatives = MAX(tentatives - 1, 0), erreur = ?, termine_le = ? "
                "WHERE id = ? AND statut = 'en_cours'",
                (erreur, horodatage(), job_id),
            )
        abandonne = curseur.rowcount == 1
        if abandonne:
            self._signaler([job_id])
        return abandonne

    def remettre(self, job_id: str, motif: str) -> bool:
        """Un job interrompu par MyMaestro (arbitre GPU, fermeture) repart en file SANS tentative perdue ; sans effet s'il
        n'est plus « en_cours » (déjà remis par `suspendre_en_cours`, annulé...)."""
        with self.base.transaction() as cx:
            return cx.execute(
                "UPDATE jobs SET statut = 'en_file', tentatives = MAX(tentatives - 1, 0), erreur = ? "
                "WHERE id = ? AND statut = 'en_cours'",
                (motif, job_id),
            ).rowcount == 1
