"""Manifeste épinglé des moteurs et détection de leur état d'installation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from mymaestro import config
from mymaestro.installation import manifeste as m

VARIABLES = ("MYMAESTRO_MAESTRO_APP", "MYMAESTRO_DLSS5", "MYMAESTRO_BONSAI", "MYMAESTRO_FFMPEG")


@pytest.fixture(autouse=True)
def environnement_propre(monkeypatch, tmp_path):
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(config, "DOSSIER_MOTEURS", tmp_path / "moteurs")
    monkeypatch.setattr(m, "_ffmpeg_externe", lambda dossier: False)
    return tmp_path / "moteurs"


def _ecrire_installation(dossier: Path, moteur: m.MoteurManifeste, version: str | None = None) -> None:
    for relatif in moteur.controle:
        cible = dossier / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text("x", encoding="utf-8")
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / m.FICHIER_VERSION).write_text(
        json.dumps({"id": moteur.id, "version": version or moteur.version, "installe_le": "2026-09-30"}),
        encoding="utf-8",
    )


def test_manifeste_charge_cinq_moteurs_ordonnes():
    moteurs = m.charger_manifeste()
    assert list(moteurs) == ["ffmpeg", "maestro", "dlss5", "bonsai", "claude"]
    assert all(moteur.id == cle for cle, moteur in moteurs.items())
    assert moteurs["ffmpeg"].requis and moteurs["maestro"].requis
    assert not moteurs["claude"].requis


def test_chaque_fichier_a_une_empreinte_ou_des_controles_de_contenu():
    for moteur in m.charger_manifeste().values():
        for fichier in moteur.fichiers:
            if fichier.sha256 is not None:
                assert re.fullmatch(r"[0-9a-f]{64}", fichier.sha256), fichier.nom
            else:
                assert fichier.controles_contenu, fichier.nom
                assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in fichier.controles_contenu.values())


def test_chaque_etape_extraire_cite_un_fichier_declare():
    for moteur in m.charger_manifeste().values():
        noms = {fichier.nom for fichier in moteur.fichiers}
        for etape in moteur.etapes:
            if etape["type"] == "extraire":
                assert etape["fichier"] in noms, (moteur.id, etape)


def test_ffmpeg_sur_le_path_sans_dossier_moteur_est_externe(monkeypatch):
    monkeypatch.setattr(m, "_ffmpeg_externe", lambda dossier: True)
    assert m.detecter(m.charger_manifeste()["ffmpeg"]) == m.EtatInstallation.EXTERNE


def test_ffmpeg_externe_ignore_le_dossier_des_moteurs(monkeypatch, tmp_path):
    ffmpeg_local = tmp_path / "moteurs" / "ffmpeg" / "ffmpeg.exe"
    ffmpeg_local.parent.mkdir(parents=True)
    ffmpeg_local.write_text("x", encoding="utf-8")
    monkeypatch.undo()  # retire la doublure de la fixture pour exercer la vraie _ffmpeg_externe
    monkeypatch.setattr(config, "DOSSIER_MOTEURS", tmp_path / "moteurs")
    monkeypatch.setattr("mymaestro.outils.ffmpeg.trouver", lambda outil: str(ffmpeg_local))
    assert m._ffmpeg_externe(m.dossier_moteur("ffmpeg")) is False


def test_dossier_absent(environnement_propre):
    assert m.detecter(m.charger_manifeste()["dlss5"]) == m.EtatInstallation.ABSENT


def test_dossier_sans_fichier_de_version_est_incomplet(environnement_propre):
    (environnement_propre / "dlss5").mkdir(parents=True)
    assert m.detecter(m.charger_manifeste()["dlss5"]) == m.EtatInstallation.INCOMPLET


def test_bonne_version_et_controles_presents(environnement_propre):
    moteur = m.charger_manifeste()["dlss5"]
    _ecrire_installation(environnement_propre / "dlss5", moteur)
    assert m.detecter(moteur) == m.EtatInstallation.INSTALLE


def test_controle_manquant_est_incomplet(environnement_propre):
    moteur = m.charger_manifeste()["bonsai"]
    _ecrire_installation(environnement_propre / "bonsai", moteur)
    (environnement_propre / "bonsai" / "bin" / "llama-server.exe").unlink()
    assert m.detecter(moteur) == m.EtatInstallation.INCOMPLET


def test_autre_version(environnement_propre):
    moteur = m.charger_manifeste()["dlss5"]
    _ecrire_installation(environnement_propre / "dlss5", moteur, version="v6.0")
    assert m.detecter(moteur) == m.EtatInstallation.VERSION_DIFFERENTE


def test_fichier_de_version_illisible_est_incomplet(environnement_propre):
    (environnement_propre / "dlss5").mkdir(parents=True)
    (environnement_propre / "dlss5" / m.FICHIER_VERSION).write_text("pas du json", encoding="utf-8")
    assert m.detecter(m.charger_manifeste()["dlss5"]) == m.EtatInstallation.INCOMPLET


@pytest.mark.parametrize(
    "moteur_id, variable",
    [("maestro", "MYMAESTRO_MAESTRO_APP"), ("dlss5", "MYMAESTRO_DLSS5"), ("bonsai", "MYMAESTRO_BONSAI"), ("ffmpeg", "MYMAESTRO_FFMPEG")],
)
def test_variable_d_environnement_donne_externe(monkeypatch, tmp_path, moteur_id, variable):
    monkeypatch.setenv(variable, str(tmp_path / "ailleurs"))
    assert m.detecter(m.charger_manifeste()[moteur_id]) == m.EtatInstallation.EXTERNE


def test_dossier_maestro_est_le_parent_de_app(environnement_propre, monkeypatch, tmp_path):
    assert m.dossier_moteur("maestro") == environnement_propre / "maestro"
    monkeypatch.setenv("MYMAESTRO_MAESTRO_APP", str(tmp_path / "fork" / "app"))
    assert m.dossier_moteur("maestro") == tmp_path / "fork"


def test_claude_detecte_par_sa_version(monkeypatch):
    moteur = m.charger_manifeste()["claude"]
    monkeypatch.setattr(m, "_claude_repond", lambda: True)
    assert m.detecter(moteur) == m.EtatInstallation.INSTALLE
    monkeypatch.setattr(m, "_claude_repond", lambda: False)
    assert m.detecter(moteur) == m.EtatInstallation.ABSENT


def test_modele_de_conversation_embarque_a_la_bonne_empreinte():
    chemin = Path(m.__file__).parent / "bonsai2-chat-template.jinja"
    contenu = chemin.read_bytes()
    assert len(contenu) == 9099
    assert hashlib.sha256(contenu).hexdigest() == "57a6ca85b8310fedc758ab39fa3edfc5ec61d70f6c82c7c5302f2b844b7fe584"


def test_modele_de_conversation_protege_de_la_conversion_de_fins_de_ligne():
    regles = (Path(m.__file__).parent / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "bonsai2-chat-template.jinja -text" in regles


@pytest.mark.parametrize("moteur_id", ["maestro", "dlss5", "bonsai", "ffmpeg"])
def test_dossier_de_config_json_hors_des_moteurs_est_externe(monkeypatch, tmp_path, moteur_id):
    fichier = tmp_path / "config.json"
    fichier.write_text(json.dumps({"moteurs": {moteur_id: str(tmp_path / "installation-existante" / moteur_id)}}), encoding="utf-8")
    monkeypatch.setattr(config, "FICHIER_CONFIG", fichier)
    assert m.detecter(m.charger_manifeste()[moteur_id]) == m.EtatInstallation.EXTERNE


def test_ffmpeg_de_dlss5_installe_par_mymaestro_n_est_pas_externe(monkeypatch, tmp_path):
    ffmpeg_dlss5 = tmp_path / "moteurs" / "dlss5" / "bin" / "ffmpeg" / "bin" / "ffmpeg.exe"
    ffmpeg_dlss5.parent.mkdir(parents=True)
    ffmpeg_dlss5.write_text("x", encoding="utf-8")
    monkeypatch.undo()  # retire la doublure de la fixture pour exercer la vraie _ffmpeg_externe
    monkeypatch.setattr(config, "DOSSIER_MOTEURS", tmp_path / "moteurs")
    monkeypatch.setattr("mymaestro.outils.ffmpeg.trouver", lambda outil: str(ffmpeg_dlss5))
    assert m.detecter(m.charger_manifeste()["ffmpeg"]) == m.EtatInstallation.ABSENT
