"""Contrôle d'une sortie vidéo avant de l'accepter (spec §7) : lisible, nombre d'images attendu, pas noire."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg


@dataclass(frozen=True)
class Verdict:
    valide: bool
    motif: str | None
    images: int | None
    luminance: float | None


def luminance_moyenne(chemin: Path, pas_images: int = 12) -> float | None:
    """Luminance moyenne (YAVG, 0 à 255) d'une image sur `pas_images` ; None si la mesure échoue."""
    try:
        sortie = subprocess.run(
            [
                ffmpeg.trouver("ffmpeg"), "-v", "error", "-i", str(chemin), "-an",
                "-vf", f"select='not(mod(n,{pas_images}))',scale=64:-2,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    valeurs = [float(ligne.split("=", 1)[1]) for ligne in sortie.splitlines() if "signalstats.YAVG=" in ligne]
    return sum(valeurs) / len(valeurs) if valeurs else None


def controler_video(chemin: Path, images_attendues: int | None, tolerance_images: int = 1, seuil_noir: float = 18.0) -> Verdict:
    """Refuse une sortie illisible, tronquée (moins d'images que prévu, à `tolerance_images` près) ou noire."""
    try:
        infos = ffmpeg.sonder(chemin)
    except Exception:  # noqa: BLE001 — ffprobe refuse le fichier : sortie invalide
        return Verdict(False, "Sortie illisible (ffprobe la refuse)", None, None)
    images = infos.get("images")
    if "largeur" not in infos:
        return Verdict(False, "Sortie sans piste vidéo", None, None)
    if images_attendues is not None and images is not None and images < images_attendues - tolerance_images:
        return Verdict(False, f"Sortie tronquée : {images} images au lieu de {images_attendues}", images, None)
    luminance = luminance_moyenne(chemin)
    if luminance is not None and luminance < seuil_noir:
        return Verdict(False, f"Sortie noire (luminance moyenne {luminance:.1f})", images, luminance)
    return Verdict(True, None, images, luminance)
