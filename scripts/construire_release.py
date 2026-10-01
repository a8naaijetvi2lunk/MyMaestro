"""Construit l'archive de release (interface construite incluse).

Usage : python scripts/construire_release.py --version 0.1.0

Étapes : arbre propre exigé, export public (garde-fou compris), construction
de l'interface, zip + somme SHA-256 dans dist-release/. Aucun envoi.
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exporter_public import exporter  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def _arbre_propre() -> bool:
    resultat = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=RACINE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    modifies = [ligne for ligne in resultat.stdout.splitlines() if ligne.strip()]
    for ligne in modifies:
        print(f"  {ligne}")
    return not modifies


def _npm(dossier: Path, *args: str) -> None:
    npm = shutil.which("npm") or "npm"
    subprocess.run([npm, *args], cwd=dossier, check=True)


def _zipper(export: Path, zip_chemin: Path, version: str) -> None:
    racine_zip = f"MyMaestro-v{version}"
    with zipfile.ZipFile(zip_chemin, "w", zipfile.ZIP_DEFLATED) as zf:
        for fichier in sorted(export.rglob("*")):
            relatif = fichier.relative_to(export)
            if not fichier.is_file() or "node_modules" in relatif.parts:
                continue
            zf.write(fichier, f"{racine_zip}/{relatif.as_posix()}")


def _ecrire_somme(zip_chemin: Path) -> str:
    """Écrit le .sha256 en LF (sha256sum -c refuse le CRLF) et renvoie la somme."""
    somme = hashlib.sha256(zip_chemin.read_bytes()).hexdigest()
    zip_chemin.with_name(zip_chemin.name + ".sha256").write_bytes(
        f"{somme}  {zip_chemin.name}\n".encode("utf-8")
    )
    return somme


MOTIF_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?$")


def version_valide(version: str) -> bool:
    """`fullmatch` : un saut de ligne final ne passe pas (le `$` seul l'accepterait)."""
    return MOTIF_VERSION.fullmatch(version) is not None


def construire(version: str) -> int:
    if not version_valide(version):
        print(f"Version « {version} » refusée : attendu X.Y.Z, éventuellement suivi d'un suffixe (par exemple 0.1.0 ou 1.0.0-rc.1).")
        return 1
    if not _arbre_propre():
        print("Arbre non propre : commitez ou écartez ces modifications avant la release.")
        return 1
    sortie = RACINE / "dist-release"
    sortie.mkdir(exist_ok=True)
    zip_chemin = sortie / f"MyMaestro-v{version}.zip"
    temporaire = Path(tempfile.mkdtemp(prefix="mymaestro-release-"))
    try:
        export = temporaire / "export"
        if exporter(export) != 0:
            print("Export refusé par le garde-fou.")
            return 1
        _npm(export / "ui", "ci")
        _npm(export / "ui", "run", "build")
        if not (export / "ui" / "dist" / "index.html").is_file():
            print("ui/dist/index.html absent après la construction.")
            return 1
        _zipper(export, zip_chemin, version)
    finally:
        shutil.rmtree(temporaire, ignore_errors=True)
    somme = _ecrire_somme(zip_chemin)
    print(f"Archive : {zip_chemin} ({zip_chemin.stat().st_size} octets)")
    print(f"SHA-256 : {somme}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--version", required=True)
    args = parseur.parse_args()
    return construire(args.version)


if __name__ == "__main__":
    sys.exit(main())
