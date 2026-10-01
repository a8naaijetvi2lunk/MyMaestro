"""Exécute un traitement DLSS 5 Visual Enhancer sans interface.

Lancé par le Python embarqué de DLSS5 (son fichier ._pth place déjà le dossier de DLSS5
dans sys.path, d'où l'import direct du paquet `src`) :

    python.exe dlss5_runner.py <demande.json>

demande = {"operation": "neural_rendering" | "interpolation", "entree": "...",
           "sortie_dossier": "...", "options": {...}}

Sortie standard : une ligne JSON par événement.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path


def emettre(evenement: dict) -> None:
    sys.stdout.write(json.dumps(evenement, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main(chemin_demande: str) -> int:
    # Le Python embarqué de DLSS5 a un fichier ._pth : il tourne en mode isolé et ignore
    # PYTHONIOENCODING. Sans cette ligne, stdout reste en cp1252 et « → », « × » ou « é »
    # cassent les événements JSON (perdus, ou UnicodeEncodeError dans le bloc d'erreur).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    demande = json.loads(Path(chemin_demande).read_text(encoding="utf-8"))
    operation = demande["operation"]
    sortie = Path(demande["sortie_dossier"])
    sortie.mkdir(parents=True, exist_ok=True)
    options = demande.get("options", {})

    def progression(valeur: float, description: str) -> None:
        emettre({"type": "progression", "valeur": float(valeur), "description": str(description)})

    debut = time.perf_counter()
    try:
        if operation == "neural_rendering":
            from src.neural_rendering.video.models import ConversionOptions
            from src.neural_rendering.video.processor import convert_video

            resultat = convert_video(demande["entree"], ConversionOptions(**options), progression, output_dir=sortie)
        elif operation == "interpolation":
            from src.frame_interpolation.models import FrameInterpolationOptions
            from src.frame_interpolation.processor import interpolate_video

            resultat = interpolate_video(
                demande["entree"], FrameInterpolationOptions(**options), progression, output_dir=sortie
            )
        else:
            raise ValueError(f"opération inconnue : {operation}")
    except Exception as exc:  # noqa: BLE001 — l'appelant lit l'erreur sur stdout
        emettre({"type": "erreur", "message": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()})
        return 1
    emettre({"type": "resultat", "duree_s": round(time.perf_counter() - debut, 1), "resultat": asdict(resultat)})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
