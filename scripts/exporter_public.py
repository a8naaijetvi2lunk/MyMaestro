"""Exporte le périmètre public (git archive HEAD, export-ignore respecté).

Usage : python scripts/exporter_public.py <dossier_cible>

Le dossier cible doit être vide ou absent. Le script ne crée aucun dépôt Git.
"""

import io
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verifier_depot_propre import verifier  # noqa: E402


def _git(racine: Path, *args: str) -> list[str]:
    resultat = subprocess.run(
        ["git", *args], cwd=racine, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return [ligne for ligne in resultat.stdout.splitlines() if ligne.strip()]


def exporter(cible: Path, racine: Path | None = None) -> int:
    cible = Path(cible)
    if cible.exists() and (not cible.is_dir() or any(cible.iterdir())):
        print(f"Le dossier cible n'est pas un dossier vide : {cible}")
        return 1
    racine = Path(racine) if racine else Path(__file__).resolve().parent.parent
    ignores = _git(racine, "ls-files", "-ci", "--exclude-standard")
    if ignores:
        print("Fichiers suivis mais ignorés (ils disparaîtraient du dépôt public) :")
        for f in ignores:
            print(f"  {f}")
        return 1
    modifies = _git(racine, "status", "--porcelain")
    if modifies:
        print("Attention : l'export part de HEAD, ces modifications non commitées sont ignorées :")
        for ligne in modifies:
            print(f"  {ligne}")
    cible.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=racine,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(cible, filter="data")
    nombre = sum(1 for p in cible.rglob("*") if p.is_file())
    print(f"{nombre} fichier(s) exporté(s) dans {cible}")
    violations = verifier(cible)
    for v in violations:
        print(v)
    if violations:
        print(f"{len(violations)} violation(s).")
        return 1
    print("Export propre.")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print("Usage : python scripts/exporter_public.py <dossier_cible>")
        return 2
    return exporter(Path(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
