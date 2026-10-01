import sqlite3

import pytest

from mymaestro.core import db


def test_ouvrir_cree_toutes_les_tables():
    connexion = db.ouvrir(":memory:")
    noms = {ligne[0] for ligne in connexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert db.TABLES_ATTENDUES <= noms
    assert db.version(connexion) == len(db.PALIERS)


def test_migrer_deux_fois_est_sans_effet():
    connexion = db.ouvrir(":memory:")
    assert db.migrer(connexion) == len(db.PALIERS)
    assert db.migrer(connexion) == len(db.PALIERS)


def test_palier_en_echec_ne_fait_pas_avancer_la_version():
    connexion = sqlite3.connect(":memory:")
    paliers_ok = ("CREATE TABLE IF NOT EXISTS a (x INTEGER);",)
    assert db.migrer(connexion, paliers_ok) == 1
    paliers_casses = paliers_ok + (
        "CREATE TABLE IF NOT EXISTS b (y INTEGER); INSERT INTO table_inexistante VALUES (1);",
    )
    with pytest.raises(sqlite3.OperationalError):
        db.migrer(connexion, paliers_casses)
    assert db.version(connexion) == 1
    paliers_repares = paliers_ok + ("CREATE TABLE IF NOT EXISTS b (y INTEGER);",)
    assert db.migrer(connexion, paliers_repares) == 2


def test_cles_etrangeres_actives():
    connexion = db.ouvrir(":memory:")
    with pytest.raises(sqlite3.IntegrityError):
        connexion.execute(
            "INSERT INTO plans (id, projet_id, indice, role, debut_s, images, fps) "
            "VALUES ('p', 'projet-inconnu', 0, 'chante', 0, 124, 24)"
        )


def test_base_sur_disque_rouverte(tmp_path):
    chemin = tmp_path / "sous-dossier" / "base.sqlite3"
    premiere = db.ouvrir(chemin)
    premiere.close()
    assert chemin.exists()
    seconde = db.ouvrir(chemin)
    assert db.version(seconde) == len(db.PALIERS)
    seconde.close()


def test_palier_2_ajoute_les_colonnes_de_file():
    connexion = db.ouvrir(":memory:")
    assert {"phase", "ordre", "regime", "libelle", "progression"} <= db.colonnes(connexion, "jobs")
    assert db.version(connexion) == len(db.PALIERS)


def test_palier_2_est_idempotent():
    connexion = db.ouvrir(":memory:")
    db.PALIERS[1](connexion)
    assert db.version(connexion) == len(db.PALIERS)


def test_table_disparue_recreee_a_l_ouverture(tmp_path):
    chemin = tmp_path / "base.sqlite3"
    connexion = db.ouvrir(chemin)
    connexion.execute("DROP TABLE jobs")
    connexion.commit()
    assert db.tables_manquantes(connexion) == {"jobs"}
    connexion.close()
    rouverte = db.ouvrir(chemin)
    assert db.tables_manquantes(rouverte) == set()
    assert "progression" in db.colonnes(rouverte, "jobs")
    rouverte.close()


def test_transaction_annulee_sur_erreur():
    base = db.Base(":memory:")
    with pytest.raises(ValueError):
        with base.transaction() as cx:
            cx.execute("INSERT INTO fiches (id, type, nom, cree_le) VALUES ('f', 'style', 'n', 'x')")
            raise ValueError("échec simulé")
    with base.transaction() as cx:
        assert cx.execute("SELECT COUNT(*) FROM fiches").fetchone()[0] == 0
    base.fermer()


def test_base_v1_sans_jobs_reparee_a_l_ouverture(tmp_path):
    chemin = tmp_path / "base.sqlite3"
    brut = sqlite3.connect(chemin)
    db.migrer(brut, db.PALIERS[:1])
    brut.execute("DROP TABLE jobs")
    brut.commit()
    brut.close()
    cx = db.ouvrir(chemin)
    assert db.tables_manquantes(cx) == set()
    assert db.version(cx) == len(db.PALIERS)
    assert "progression" in db.colonnes(cx, "jobs")
    cx.close()


def _fiche(cx, id_):
    cx.execute("INSERT INTO fiches (id, type, nom, cree_le) VALUES (?, 'style', 'n', 'x')", (id_,))


def _ids(base):
    with base.transaction() as cx:
        return {r[0] for r in cx.execute("SELECT id FROM fiches")}


def test_transaction_imbriquee_annulee_en_bloc():
    base = db.Base(":memory:")
    with pytest.raises(ValueError):
        with base.transaction() as cx:
            _fiche(cx, "externe")
            with base.transaction() as interne:
                _fiche(interne, "interne")
            raise ValueError("échec externe")
    assert _ids(base) == set()
    base.fermer()


def test_transaction_imbriquee_reussie_valide_tout():
    base = db.Base(":memory:")
    with base.transaction() as cx:
        _fiche(cx, "externe")
        with base.transaction() as interne:
            _fiche(interne, "interne")
    assert _ids(base) == {"externe", "interne"}
    base.fermer()
