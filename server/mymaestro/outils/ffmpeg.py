"""Aides ffmpeg/ffprobe (sous-processus en liste d'arguments, jamais de shell)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from mymaestro import config

# Repli : le ffmpeg livré avec DLSS 5 (lecture seule), qui suit MYMAESTRO_DLSS5.
REPLI_DLSS5 = config.DLSS5_RACINE / "bin" / "ffmpeg" / "bin"


def trouver(outil: str) -> str:
    """Cherche l'outil dans le dossier configuré (moteurs/ffmpeg), puis sur le PATH, puis dans le ffmpeg de DLSS 5."""
    configure = config.FFMPEG_DOSSIER / f"{outil}.exe"
    if configure.exists():
        return str(configure)
    chemin = shutil.which(outil)
    if chemin:
        return chemin
    candidat = REPLI_DLSS5 / f"{outil}.exe"
    if candidat.exists():
        return str(candidat)
    raise FileNotFoundError(
        f"{outil} introuvable (ni dans {config.FFMPEG_DOSSIER}, ni sur le PATH, ni dans {REPLI_DLSS5})"
    )


def decouper_audio(source: Path, debut_s: float, duree_s: float, destination: Path) -> Path:
    """Extrait [debut_s, debut_s + duree_s] de `source` en WAV PCM 48 kHz stéréo."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            trouver("ffmpeg"), "-y", "-v", "error",
            "-ss", f"{debut_s:.3f}", "-t", f"{duree_s:.3f}", "-i", str(source),
            "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(destination),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return destination


def lire_pcm_mono(
    source: Path, taux: int = 16000, debut_s: float | None = None, duree_s: float | None = None
) -> np.ndarray:
    """Décode la piste audio de `source` en mono flottant [-1, 1] au taux demandé."""
    commande = [trouver("ffmpeg"), "-v", "error"]
    if debut_s is not None:
        commande += ["-ss", f"{debut_s:.3f}"]
    if duree_s is not None:
        commande += ["-t", f"{duree_s:.3f}"]
    commande += ["-i", str(source), "-vn", "-ac", "1", "-ar", str(taux), "-f", "s16le", "-"]
    brut = subprocess.run(commande, check=True, capture_output=True, timeout=300).stdout
    return np.frombuffer(brut, dtype="<i2").astype(np.float32) / 32768.0


def sonder(source: Path) -> dict[str, Any]:
    brut = subprocess.run(
        [trouver("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout
    infos = json.loads(brut.decode("utf-8"))
    flux = infos.get("streams", [])
    video = next((f for f in flux if f.get("codec_type") == "video"), None)
    audio = next((f for f in flux if f.get("codec_type") == "audio"), None)
    resultat: dict[str, Any] = {
        "duree_s": float(infos.get("format", {}).get("duration", 0) or 0),
        "audio": audio is not None,
    }
    if video is not None:
        numerateur, _, denominateur = str(video.get("r_frame_rate", "0/1")).partition("/")
        nb_images = str(video.get("nb_frames", ""))
        resultat.update(
            largeur=int(video.get("width", 0)),
            hauteur=int(video.get("height", 0)),
            fps=round(float(numerateur) / float(denominateur or 1), 3),
            images=int(nb_images) if nb_images.isdigit() else None,
            codec=video.get("codec_name"),
        )
    return resultat
