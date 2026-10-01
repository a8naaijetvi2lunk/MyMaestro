"""Le fichier .sha256 de la release doit être vérifiable par `sha256sum -c` (LF, pas CRLF)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import pytest  # noqa: E402
from construire_release import _ecrire_somme, construire, version_valide  # noqa: E402


@pytest.mark.parametrize("version", ["0.1.0", "1.2.3", "1.0.0-rc.1", "2.0.0.beta2"])
def test_versions_acceptees(version):
    assert version_valide(version)


@pytest.mark.parametrize("version", ["", "1.0", "v1.0.0", "1.0.0 ", "..\\x", "1.0.0/../..", "a.b.c", "1.0.0-"])
def test_versions_refusees(version):
    assert not version_valide(version)


def test_construire_refuse_une_version_invalide(capsys):
    assert construire("../evil") == 1
    assert "version" in capsys.readouterr().out.lower()


def test_somme_ecrite_en_lf(tmp_path):
    archive = tmp_path / "MyMaestro-v0.0.0.zip"
    archive.write_bytes(b"contenu")
    somme = _ecrire_somme(archive)
    brut = (tmp_path / "MyMaestro-v0.0.0.zip.sha256").read_bytes()
    assert brut == f"{somme}  {archive.name}\n".encode()
    assert b"\r" not in brut
