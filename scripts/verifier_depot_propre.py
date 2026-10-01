"""Garde-fou du dépôt propre : refuse tout chemin local, nom personnel ou secret.

Usage : python scripts/verifier_depot_propre.py <dossier> [--depot]

Avec --depot, vérifie aussi qu'aucun fichier suivi n'est ignoré (il
disparaîtrait de l'export `git archive`). Code de sortie 1 s'il y a des
violations, 0 sinon. Bibliothèque standard uniquement.

Les motifs sont écrits de façon à ne pas se reconnaître eux-mêmes : ce script
fait partie du périmètre public et passe son propre contrôle.
"""

import re
import subprocess
import sys
from pathlib import Path

MOTIFS = {
    "chemin de disque local": r"(?i)\b[D-Z]:[\\/]",
    "profil Windows": r"(?i)\bC:[\\/]+Users[\\/]",
    "chemin Git Bash local": r"(?i)(?<![\w.])/[c-z]/(users|maestro|mymaestro|dlls5|bonsai2)\b",
    "nom d'utilisateur de la machine": r"(?i)br0{2}t",
    "nom personnel": r"(?i)\by[v]es\b",
    "outil personnel": r"(?i)dev[b]rain",
    "lien de notes personnelles": r"\[\[[^\]\n]+\]\]",
    "clé Anthropic": r"sk-ant-[A-Za-z0-9_-]{10,}",
    "jeton GitHub": r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    "jeton Hugging Face": r"\bhf_[A-Za-z0-9]{30,}",
    "clé privée": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}

_COMPILES = {nom: re.compile(motif) for nom, motif in MOTIFS.items()}

# Seuls les documents peuvent porter un lien de notes : dans du code, un double crochet est un littéral imbriqué.
_MOTIFS_DOCUMENTS = {"lien de notes personnelles"}
_EXTENSIONS_DOCUMENTS = {".md", ".txt"}

# Fichiers générés, exclus du contrôle.
_IGNORES = {"ui/package-lock.json", "server/uv.lock"}
# Hors mode --depot, on parcourt le dossier tel quel : ces dossiers ne font pas partie du dépôt.
_DOSSIERS_IGNORES = {".git", ".venv", "node_modules", "dist", "dist-release", "__pycache__", ".pytest_cache", "moteurs", "data"}


def _decoder(contenu: bytes) -> str | None:
    """Texte du fichier (UTF-8, UTF-16 avec BOM, puis cp1252), ou None s'il est binaire."""
    try:
        return contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    if contenu.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return contenu.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if b"\x00" in contenu:
        return None
    return contenu.decode("cp1252", errors="replace")


def _fichiers_suivis(racine: Path) -> list[str]:
    resultat = subprocess.run(["git", "ls-files", "-z"], cwd=racine, capture_output=True, check=True)
    return [f for f in resultat.stdout.decode("utf-8").split("\0") if f]


def verifier(dossier: Path, depot: bool = False) -> list[str]:
    """Rend les violations au format `chemin:ligne: motif`.

    Avec `depot`, seuls les fichiers suivis par Git sont contrôlés."""
    dossier = Path(dossier)
    if not dossier.is_dir():
        raise NotADirectoryError(dossier)
    candidats = sorted(dossier / f for f in _fichiers_suivis(dossier)) if depot else sorted(dossier.rglob("*"))
    violations: list[str] = []
    for chemin in candidats:
        if not chemin.is_file():
            continue
        relatif = chemin.relative_to(dossier)
        if not depot and _DOSSIERS_IGNORES & set(relatif.parts):
            continue
        rel = relatif.as_posix()
        if rel in _IGNORES:
            continue
        texte = _decoder(chemin.read_bytes())
        if texte is None:
            continue  # binaire
        document = chemin.suffix.lower() in _EXTENSIONS_DOCUMENTS
        for numero, ligne in enumerate(texte.splitlines(), start=1):
            for nom, motif in _COMPILES.items():
                if nom in _MOTIFS_DOCUMENTS and not document:
                    continue
                if motif.search(ligne):
                    violations.append(f"{rel}:{numero}: {nom}")
    return violations


def _fichiers_suivis_ignores(racine: Path) -> list[str]:
    resultat = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"],
        cwd=racine,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return [ligne for ligne in resultat.stdout.splitlines() if ligne.strip()]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = list(sys.argv[1:] if argv is None else argv)
    depot = "--depot" in args
    args = [a for a in args if a != "--depot"]
    if len(args) != 1:
        print("Usage : python scripts/verifier_depot_propre.py <dossier> [--depot]")
        return 2
    dossier = Path(args[0])
    if not dossier.is_dir():
        print(f"Dossier introuvable : {dossier}")
        return 2
    violations = verifier(dossier, depot=depot)
    if depot:
        racine = Path(__file__).resolve().parent.parent
        violations += [
            f"{f}: fichier suivi mais ignoré (absent de l'export)"
            for f in _fichiers_suivis_ignores(racine)
        ]
    for v in violations:
        print(v)
    if violations:
        print(f"{len(violations)} violation(s).")
        return 1
    print("Dépôt propre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
