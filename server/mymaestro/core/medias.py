"""Médias sur disque : chemins bornés (spec §7 : chemins résolus et bornés) et écriture en flux."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path, PurePath
import uuid


class CheminInterdit(ValueError):
    """Chemin qui sort du dossier autorisé, ou qui le désigne lui-même."""


class TropVolumineux(ValueError):
    """Fichier au-delà de la taille autorisée."""


class FichierVide(ValueError):
    """Aucun octet reçu."""


def chemin_sur(racine: Path, relatif: str) -> Path:
    """Chemin absolu de `relatif` sous `racine` ; refusé s'il en sort (« .. », chemin absolu, autre lecteur)."""
    # Refus par analyse du texte AVANT toute résolution : resolve() accède au disque (UNC = connexion réseau).
    pur = PurePath(relatif)
    if pur.is_absolute() or pur.drive or pur.root or ".." in pur.parts:
        raise CheminInterdit(relatif)
    base = Path(racine).resolve()
    try:
        cible = (base / relatif).resolve()
    except (ValueError, OSError):
        raise CheminInterdit(relatif) from None
    if cible == base or not cible.is_relative_to(base):
        raise CheminInterdit(relatif)
    return cible


async def ecrire_flux(flux: AsyncIterator[bytes], cible: Path, taille_max: int) -> int:
    """Écrit un flux dans `cible` via un fichier partiel renommé à la fin : jamais de fichier tronqué."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    partiel = cible.with_name(f"{cible.name}.{uuid.uuid4().hex}.partiel")
    total = 0
    try:
        with partiel.open("wb") as sortie:
            async for morceau in flux:
                total += len(morceau)
                if total > taille_max:
                    raise TropVolumineux(f"plus de {taille_max} octets")
                sortie.write(morceau)
        if total == 0:
            raise FichierVide(str(cible))
        partiel.replace(cible)
    finally:
        partiel.unlink(missing_ok=True)
    return total
