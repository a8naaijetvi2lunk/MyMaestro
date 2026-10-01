"""Tests du garde-fou du dépôt propre (scripts/verifier_depot_propre.py).

Les chaînes piégées sont assemblées à l'exécution : ce fichier fait partie du
périmètre public et ne doit lui-même déclencher aucun motif.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verifier_depot_propre.py"


@pytest.fixture(scope="module")
def garde():
    spec = importlib.util.spec_from_file_location("verifier_depot_propre", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PIEGES = {
    "chemin de disque local": "p = '" + "D" + ":" + "\\" + "dossier'",
    "profil Windows": "p = '" + "C" + ":/" + "Users/quelquun'",
    "chemin Git Bash local": "p = '/" + "d/" + "maestro/app'",
    "nom d'utilisateur de la machine": "u = '" + "br" + "00" + "t'",
    "nom personnel": "# choix d'" + "Yv" + "es",
    "outil personnel": "# " + "Dev" + "Brain",
    "lien de notes personnelles": "# voir " + "[" + "[note]" + "]",
    "clé Anthropic": "k = '" + "sk-" + "ant-" + "a" * 12 + "'",
    "jeton GitHub": "t = '" + "gh" + "p_" + "a" * 24 + "'",
    "jeton Hugging Face": "t = '" + "h" + "f_" + "a" * 32 + "'",
    "clé privée": "-----BEGIN " + "RSA PRIVATE KEY-----",
}


def test_un_piege_par_motif(garde, tmp_path):
    assert set(PIEGES) == set(garde.MOTIFS)
    for i, contenu in enumerate(PIEGES.values()):
        (tmp_path / f"piege{i}.txt").write_text(contenu + "\n", encoding="utf-8")
    violations = garde.verifier(tmp_path)
    for motif in PIEGES:
        assert any(motif in v for v in violations), motif
    assert len(violations) == len(PIEGES)


def test_format_chemin_ligne_motif(garde, tmp_path):
    (tmp_path / "a.py").write_text("ok\n" + PIEGES["nom personnel"] + "\n", encoding="utf-8")
    violations = garde.verifier(tmp_path)
    assert len(violations) == 1
    assert violations[0].startswith("a.py:2: ")


def test_dossier_propre(garde, tmp_path):
    (tmp_path / "a.py").write_text("print('bonjour')\n", encoding="utf-8")
    (tmp_path / "sous").mkdir()
    (tmp_path / "sous" / "b.md").write_text("# Titre\n", encoding="utf-8")
    assert garde.verifier(tmp_path) == []


def test_binaire_et_verrous_ignores(garde, tmp_path):
    (tmp_path / "image.bin").write_bytes(b"\xff\xfe\x00" + PIEGES["chemin de disque local"].encode())
    for sous_dossier, nom in (("server", "uv.lock"), ("ui", "package-lock.json")):
        (tmp_path / sous_dossier).mkdir()
        (tmp_path / sous_dossier / nom).write_text(PIEGES["profil Windows"], encoding="utf-8")
    assert garde.verifier(tmp_path) == []


def test_cible_absente_ou_fichier_donne_code_2(garde, tmp_path):
    assert garde.main([str(tmp_path / "absent")]) == 2
    fichier = tmp_path / "f.txt"
    fichier.write_text("x", encoding="utf-8")
    assert garde.main([str(fichier)]) == 2
    with pytest.raises(NotADirectoryError):
        garde.verifier(fichier)


def test_lien_de_notes_seulement_dans_les_documents(garde, tmp_path):
    (tmp_path / "code.py").write_text("x = [" + "[1, 2]" + "]\n", encoding="utf-8")
    assert garde.verifier(tmp_path) == []
    (tmp_path / "doc.md").write_text("voir [" + "[x]" + "]\n", encoding="utf-8")
    assert garde.verifier(tmp_path) == ["doc.md:1: lien de notes personnelles"]


def test_chemin_de_disque_avec_barre_oblique(garde, tmp_path):
    (tmp_path / "a.py").write_text("p = '" + "D" + ":/" + "dossier'\n", encoding="utf-8")
    assert garde.verifier(tmp_path) == ["a.py:1: chemin de disque local"]


def test_encodages_utf16_et_cp1252(garde, tmp_path):
    piege = "chemin = '" + "D" + ":\\" + "dossier'\n"
    (tmp_path / "a.ps1").write_bytes(b"\xff\xfe" + piege.encode("utf-16-le"))
    (tmp_path / "b.bat").write_bytes(("REM é\n" + piege).encode("cp1252"))
    assert sorted(garde.verifier(tmp_path)) == [
        "a.ps1:1: chemin de disque local",
        "b.bat:2: chemin de disque local",
    ]


def test_dossiers_ignores_hors_depot(garde, tmp_path):
    for nom in (".venv", "node_modules", "moteurs", "data", "dist-release"):
        (tmp_path / nom).mkdir()
        (tmp_path / nom / "x.txt").write_text("C" + ":\\" + "Users\\q\n", encoding="utf-8")
    assert garde.verifier(tmp_path) == []


def test_mode_depot_ne_controle_que_les_fichiers_suivis(garde, tmp_path, monkeypatch):
    (tmp_path / "suivi.txt").write_text("D" + ":/" + "x\n", encoding="utf-8")
    (tmp_path / "libre.txt").write_text("D" + ":/" + "x\n", encoding="utf-8")
    monkeypatch.setattr(garde, "_fichiers_suivis", lambda racine: ["suivi.txt"])
    assert garde.verifier(tmp_path, depot=True) == ["suivi.txt:1: chemin de disque local"]
