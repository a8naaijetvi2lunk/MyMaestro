"""Configuration : variable d'environnement, puis data/config.json, puis défaut."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mymaestro import config
from mymaestro.core import empreintes
from mymaestro.outils import ffmpeg


@pytest.fixture
def fichier_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    chemin = tmp_path / "config.json"
    monkeypatch.setattr(config, "FICHIER_CONFIG", chemin)
    return chemin


def test_reglage_env_puis_config_puis_defaut(fichier_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYMAESTRO_TEST_REGLAGE", raising=False)
    assert config.reglage("MYMAESTRO_TEST_REGLAGE", "cle", "defaut") == "defaut"
    fichier_config.write_text(json.dumps({"cle": "fichier"}), encoding="utf-8")
    assert config.reglage("MYMAESTRO_TEST_REGLAGE", "cle", "defaut") == "fichier"
    monkeypatch.setenv("MYMAESTRO_TEST_REGLAGE", "env")
    assert config.reglage("MYMAESTRO_TEST_REGLAGE", "cle", "defaut") == "env"


def test_reglage_variable_vide_ignoree(fichier_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fichier_config.write_text(json.dumps({"cle": "fichier"}), encoding="utf-8")
    monkeypatch.setenv("MYMAESTRO_TEST_REGLAGE", "")
    assert config.reglage("MYMAESTRO_TEST_REGLAGE", "cle", "defaut") == "fichier"


def test_chemin_moteur_env_config_defaut(fichier_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYMAESTRO_TEST_MOTEUR", raising=False)
    assert config.chemin_moteur("MYMAESTRO_TEST_MOTEUR", "dlss5") == config.RACINE / "moteurs" / "dlss5"
    ailleurs = tmp_path / "ailleurs"
    fichier_config.write_text(json.dumps({"moteurs": {"dlss5": str(ailleurs)}}), encoding="utf-8")
    assert config.chemin_moteur("MYMAESTRO_TEST_MOTEUR", "dlss5") == ailleurs
    depuis_env = tmp_path / "env"
    monkeypatch.setenv("MYMAESTRO_TEST_MOTEUR", str(depuis_env))
    assert config.chemin_moteur("MYMAESTRO_TEST_MOTEUR", "dlss5") == depuis_env


def test_chemin_moteur_relatif_resolu_depuis_la_racine(fichier_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYMAESTRO_TEST_MOTEUR", raising=False)
    fichier_config.write_text(json.dumps({"moteurs": {"dlss5": "outils/dlss5"}}), encoding="utf-8")
    assert config.chemin_moteur("MYMAESTRO_TEST_MOTEUR", "dlss5") == config.RACINE / "outils" / "dlss5"


def test_conversions_tolerantes(caplog: pytest.LogCaptureFixture) -> None:
    assert config._flottant("12,5".replace(",", "."), 55) == 12.5
    assert config._entier("7", 1) == 7
    with caplog.at_level("WARNING"):
        assert config._flottant("beaucoup", 55) == 55
        assert config._flottant(None, 55) == 55
        assert config._entier("x", 3) == 3
    assert "beaucoup" in caplog.text


def test_marge_memoire_invalide_donne_le_defaut(fichier_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MYMAESTRO_MARGE_MEMOIRE_GO", raising=False)
    fichier_config.write_text(json.dumps({"marge_memoire_go": "beaucoup"}), encoding="utf-8")
    assert config._marge_memoire_go() == 55.0
    fichier_config.write_text(json.dumps({"marge_memoire_go": 0}), encoding="utf-8")
    assert config._marge_memoire_go() == 0.0


def test_config_illisible_journalisee_une_seule_fois(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    invalide = tmp_path / "illisible.json"
    invalide.write_text("{pas du json", encoding="utf-8")
    with caplog.at_level("WARNING"):
        config.lire_config(invalide)
        config.lire_config(invalide)
    assert len([r for r in caplog.records if "illisible.json" in r.getMessage()]) == 1


def test_lire_config_absent_invalide_ou_liste(tmp_path: Path) -> None:
    assert config.lire_config(tmp_path / "absent.json") == {}
    invalide = tmp_path / "invalide.json"
    invalide.write_text("{pas du json", encoding="utf-8")
    assert config.lire_config(invalide) == {}
    liste = tmp_path / "liste.json"
    liste.write_text("[1, 2]", encoding="utf-8")
    assert config.lire_config(liste) == {}
    avec_bom = tmp_path / "bom.json"
    avec_bom.write_bytes(bytes([0xEF, 0xBB, 0xBF]) + b'{"cle": 1}')
    assert config.lire_config(avec_bom) == {"cle": 1}


def test_ecrire_config_par_defaut_cree_sans_ecraser(tmp_path: Path) -> None:
    chemin = tmp_path / "data" / "config.json"
    assert config.ecrire_config_par_defaut(chemin) == chemin
    contenu = json.loads(chemin.read_text(encoding="utf-8"))
    assert contenu == {
        "moteurs": {},
        "marge_memoire_go": 55,
        "vram_mo": None,
        "applications_a_fermer": config.APPLICATIONS_A_FERMER_DEFAUT,
    }
    chemin.write_text('{"a": 1}', encoding="utf-8")
    config.ecrire_config_par_defaut(chemin)
    assert json.loads(chemin.read_text(encoding="utf-8")) == {"a": 1}


def test_ffmpeg_trouve_le_dossier_configure_avant_le_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ffmpeg.exe").write_bytes(b"")
    monkeypatch.setattr(config, "FFMPEG_DOSSIER", tmp_path)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda outil: str(tmp_path / "path" / "ffmpeg.exe"))
    assert ffmpeg.trouver("ffmpeg") == str(tmp_path / "ffmpeg.exe")


def test_ffmpeg_introuvable_cite_les_emplacements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "FFMPEG_DOSSIER", tmp_path / "vide")
    monkeypatch.setattr(ffmpeg, "REPLI_DLSS5", tmp_path / "repli")
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda outil: None)
    with pytest.raises(FileNotFoundError) as erreur:
        ffmpeg.trouver("ffmpeg")
    message = str(erreur.value)
    assert str(tmp_path / "vide") in message and "PATH" in message and str(tmp_path / "repli") in message


def test_empreintes_publiees_identiques_aux_mesures_completes() -> None:
    complet = config.RACINE / "docs" / "mesures" / "tache0.json"
    if not complet.exists():
        pytest.skip("docs/mesures/tache0.json absent (dépôt public)")
    assert empreintes.FICHIER_MESURES.name == "empreintes_mesurees.json"
    assert empreintes.charger() == empreintes.charger(complet)
    assert empreintes.charger() != dict(empreintes.DEFAUTS)
