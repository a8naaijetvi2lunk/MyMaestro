"""Base SQLite de MyMaestro : ouverture et migrations par palier.

Règle des migrations SQLite embarquées (idempotence, version par palier) :
chaque palier est idempotent (IF NOT EXISTS) et `PRAGMA user_version` est écrit
juste après lui, jamais seulement à la fin. Une base interrompue en cours de
migration se répare d'elle-même au lancement suivant.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

PALIER_1 = """
CREATE TABLE IF NOT EXISTS recettes (
    id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    nom TEXT NOT NULL,
    valeurs TEXT NOT NULL DEFAULT '{}',
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projets (
    id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    titre TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('16:9', '9:16')),
    recette_id TEXT REFERENCES recettes(id) ON DELETE SET NULL,
    chanson TEXT,
    paroles TEXT,
    etat_phases TEXT NOT NULL DEFAULT '{}',
    donnees_module TEXT NOT NULL DEFAULT '{}',
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fiches (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('personnage', 'decor', 'style')),
    nom TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS images_fiche (
    id TEXT PRIMARY KEY,
    fiche_id TEXT NOT NULL REFERENCES fiches(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('portrait_pied', 'gros_plan', 'reference')),
    chemin TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS casting (
    projet_id TEXT NOT NULL REFERENCES projets(id) ON DELETE CASCADE,
    fiche_id TEXT NOT NULL REFERENCES fiches(id) ON DELETE CASCADE,
    PRIMARY KEY (projet_id, fiche_id)
);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    projet_id TEXT NOT NULL REFERENCES projets(id) ON DELETE CASCADE,
    indice INTEGER NOT NULL CHECK (indice >= 0),
    role TEXT NOT NULL CHECK (role IN ('chante', 'coupe')),
    debut_s REAL NOT NULL CHECK (debut_s >= 0),
    images INTEGER NOT NULL CHECK (images > 0),
    fps INTEGER NOT NULL CHECK (fps > 0),
    paroles TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    prompt_image TEXT NOT NULL DEFAULT '',
    prompt_video TEXT NOT NULL DEFAULT '',
    moteur_image TEXT,
    moteur_video TEXT,
    image_depart TEXT,
    prise_active_id TEXT,
    UNIQUE (projet_id, indice)
);
CREATE TABLE IF NOT EXISTS plans_fiches (
    plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    fiche_id TEXT NOT NULL REFERENCES fiches(id) ON DELETE CASCADE,
    PRIMARY KEY (plan_id, fiche_id)
);
CREATE TABLE IF NOT EXISTS prises (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    numero INTEGER NOT NULL CHECK (numero >= 1),
    moteur TEXT NOT NULL,
    graine INTEGER,
    reglages TEXT NOT NULL DEFAULT '{}',
    fichier_brut TEXT,
    statut TEXT NOT NULL,
    erreur TEXT,
    sortie_active_id TEXT,
    cree_le TEXT NOT NULL,
    UNIQUE (plan_id, numero)
);
CREATE TABLE IF NOT EXISTS sorties (
    id TEXT PRIMARY KEY,
    prise_id TEXT NOT NULL REFERENCES prises(id) ON DELETE CASCADE,
    etape TEXT NOT NULL CHECK (etape IN ('flashvsr', 'dlss5')),
    ordre INTEGER NOT NULL CHECK (ordre >= 1),
    reglages TEXT NOT NULL DEFAULT '{}',
    fichier TEXT,
    statut TEXT NOT NULL,
    erreur TEXT,
    cree_le TEXT NOT NULL,
    UNIQUE (prise_id, ordre)
);
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    projet_id TEXT NOT NULL REFERENCES projets(id) ON DELETE CASCADE,
    piste TEXT NOT NULL,
    plan_id TEXT REFERENCES plans(id) ON DELETE CASCADE,
    fichier_audio TEXT,
    position_s REAL NOT NULL CHECK (position_s >= 0),
    entree_s REAL NOT NULL DEFAULT 0 CHECK (entree_s >= 0),
    sortie_s REAL NOT NULL,
    verrou_chanson INTEGER NOT NULL DEFAULT 0 CHECK (verrou_chanson IN (0, 1)),
    volume REAL NOT NULL DEFAULT 1.0,
    fondu_entree_s REAL NOT NULL DEFAULT 0,
    fondu_sortie_s REAL NOT NULL DEFAULT 0,
    CHECK (sortie_s > entree_s)
);
CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    projet_id TEXT NOT NULL REFERENCES projets(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('refaire', 'passe_dlss5', 'bruitage', 'changer_moteur')),
    plan_id TEXT REFERENCES plans(id) ON DELETE CASCADE,
    clip_id TEXT REFERENCES clips(id) ON DELETE CASCADE,
    reglages TEXT NOT NULL DEFAULT '{}',
    statut TEXT NOT NULL DEFAULT 'programmee',
    cree_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    voie TEXT NOT NULL CHECK (voie IN ('gpu', 'cloud')),
    connecteur TEXT NOT NULL,
    modele TEXT,
    projet_id TEXT REFERENCES projets(id) ON DELETE CASCADE,
    donnees TEXT NOT NULL DEFAULT '{}',
    statut TEXT NOT NULL CHECK (statut IN ('en_file', 'en_cours', 'termine', 'echec', 'annule')),
    tentatives INTEGER NOT NULL DEFAULT 0,
    erreur TEXT,
    resultat TEXT,
    cree_le TEXT NOT NULL,
    demarre_le TEXT,
    termine_le TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_statut ON jobs (statut, voie);
CREATE INDEX IF NOT EXISTS idx_plans_projet ON plans (projet_id, indice);
CREATE INDEX IF NOT EXISTS idx_clips_projet ON clips (projet_id, piste);
"""

Palier = str | Callable[[sqlite3.Connection], None]


def colonnes(connexion: sqlite3.Connection, table: str) -> set[str]:
    return {ligne[1] for ligne in connexion.execute(f"PRAGMA table_info({table})")}


def _ajouter_colonne(connexion: sqlite3.Connection, table: str, colonne: str, definition: str) -> None:
    """ALTER TABLE ADD COLUMN n'a pas de IF NOT EXISTS en SQLite : on vérifie d'abord (idempotence)."""
    if colonne not in colonnes(connexion, table):
        connexion.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}")


def _palier_2(connexion: sqlite3.Connection) -> None:
    """File GPU/cloud : phase, ordre, régime, libellé et progression des jobs."""
    _ajouter_colonne(connexion, "jobs", "phase", "TEXT")
    _ajouter_colonne(connexion, "jobs", "ordre", "INTEGER NOT NULL DEFAULT 0")
    _ajouter_colonne(connexion, "jobs", "regime", "TEXT NOT NULL DEFAULT 'phases'")
    _ajouter_colonne(connexion, "jobs", "libelle", "TEXT NOT NULL DEFAULT ''")
    _ajouter_colonne(connexion, "jobs", "progression", "REAL NOT NULL DEFAULT 0")
    connexion.execute("CREATE INDEX IF NOT EXISTS idx_jobs_file ON jobs (voie, statut, ordre)")


def _palier_3(connexion: sqlite3.Connection) -> None:
    """Director : prompt son par plan, durée de la chanson du projet."""
    _ajouter_colonne(connexion, "plans", "prompt_son", "TEXT NOT NULL DEFAULT ''")
    _ajouter_colonne(connexion, "projets", "duree_chanson_s", "REAL")


PALIERS: tuple[Palier, ...] = (PALIER_1, _palier_2, _palier_3)

TABLES_ATTENDUES = frozenset(
    {
        "recettes",
        "projets",
        "fiches",
        "images_fiche",
        "casting",
        "plans",
        "plans_fiches",
        "prises",
        "sorties",
        "clips",
        "actions",
        "jobs",
    }
)


def ouvrir(chemin: Path | str) -> sqlite3.Connection:
    """Ouvre (et crée si besoin) la base, active les clés étrangères, migre puis répare le schéma."""
    texte = str(chemin)
    if texte != ":memory:":
        Path(texte).parent.mkdir(parents=True, exist_ok=True)
    connexion = sqlite3.connect(texte, check_same_thread=False)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA foreign_keys = ON")
    if texte != ":memory:":
        connexion.execute("PRAGMA journal_mode = WAL")
    try:
        if version(connexion) > 0:
            # Base déjà versionnée : réparer d'abord, sinon un palier ALTER TABLE tombe sur une table absente.
            reparer_schema(connexion)
        migrer(connexion)
        reparer_schema(connexion)
    except BaseException:
        connexion.close()
        raise
    return connexion


def version(connexion: sqlite3.Connection) -> int:
    return int(connexion.execute("PRAGMA user_version").fetchone()[0])


def _appliquer(connexion: sqlite3.Connection, palier: Palier) -> None:
    if callable(palier):
        palier(connexion)
    else:
        connexion.executescript(palier)


def migrer(connexion: sqlite3.Connection, paliers: tuple[Palier, ...] | list[Palier] = PALIERS) -> int:
    """Applique les paliers manquants un par un ; la version suit chaque palier réussi."""
    actuelle = version(connexion)
    for numero, palier in enumerate(paliers, start=1):
        if numero <= actuelle:
            continue
        _appliquer(connexion, palier)
        connexion.execute(f"PRAGMA user_version = {numero:d}")
        connexion.commit()
    return version(connexion)


def tables_manquantes(connexion: sqlite3.Connection) -> set[str]:
    presentes = {ligne[0] for ligne in connexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return set(TABLES_ATTENDUES) - presentes


def reparer_schema(connexion: sqlite3.Connection, paliers: tuple[Palier, ...] | list[Palier] = PALIERS) -> set[str]:
    """3e règle (addendum) : ne pas se fier au seul user_version. Si une table attendue
    manque, rejouer tous les paliers (idempotents) pour la recréer. Renvoie les tables réparées."""
    manquantes = tables_manquantes(connexion)
    if manquantes:
        for palier in paliers:
            _appliquer(connexion, palier)
        connexion.commit()
    return manquantes


class Base:
    """Connexion SQLite unique partagée entre les fils (API, file, ordonnanceur), sérialisée par un verrou."""

    def __init__(self, chemin: Path | str) -> None:
        self.connexion = ouvrir(chemin)
        self._verrou = threading.RLock()
        self._profondeur = 0

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Accès exclusif à la connexion ; commit à la sortie normale, rollback sur exception.
        Réentrant : seule la transaction la plus externe valide ou annule (imbrication atomique)."""
        with self._verrou:
            self._profondeur += 1
            try:
                yield self.connexion
                if self._profondeur == 1:
                    self.connexion.commit()
            except BaseException:
                if self._profondeur == 1:
                    self.connexion.rollback()
                raise
            finally:
                self._profondeur -= 1

    def fermer(self) -> None:
        with self._verrou:
            self.connexion.close()
