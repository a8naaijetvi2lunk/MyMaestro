"""Tests de l'export public (scripts/exporter_public.py) sur un petit dépôt Git jetable."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(scope="module")
def export():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("exporter_public", SCRIPTS / "exporter_public.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(racine: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false", *args],
        cwd=racine,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def depot(tmp_path: Path) -> Path:
    racine = tmp_path / "depot"
    racine.mkdir()
    _git(racine, "init", "-q")
    (racine / "a.txt").write_text("bonjour\n", encoding="utf-8")
    (racine / "prive").mkdir()
    (racine / "prive" / "n.txt").write_text("notes\n", encoding="utf-8")
    (racine / ".gitattributes").write_text("prive export-ignore\n", encoding="utf-8")
    _git(racine, "add", "a.txt", "prive/n.txt", ".gitattributes")
    _git(racine, "commit", "-q", "-m", "init")
    return racine


def test_export_propre_sans_dossier_vide(export, depot, tmp_path, capsys):
    cible = tmp_path / "sortie"
    assert export.exporter(cible, racine=depot) == 0
    assert (cible / "a.txt").is_file()
    assert not (cible / "prive").exists()
    assert not [p for p in cible.rglob("*") if p.is_dir() and not any(p.iterdir())]
    assert "modifié" not in capsys.readouterr().out


def test_modifications_non_commitees_avertissent(export, depot, tmp_path, capsys):
    (depot / "a.txt").write_text("change\n", encoding="utf-8")
    (depot / "neuf.txt").write_text("x\n", encoding="utf-8")
    assert export.exporter(tmp_path / "sortie", racine=depot) == 0
    sortie = capsys.readouterr().out
    assert "a.txt" in sortie and "neuf.txt" in sortie
    assert (tmp_path / "sortie" / "a.txt").read_text(encoding="utf-8") == "bonjour\n"


def test_fichier_suivi_mais_ignore_fait_echouer(export, depot, tmp_path, capsys):
    (depot / ".gitignore").write_text("a.txt\n", encoding="utf-8")
    assert export.exporter(tmp_path / "sortie", racine=depot) == 1
    assert "a.txt" in capsys.readouterr().out
    assert not (tmp_path / "sortie").exists()
