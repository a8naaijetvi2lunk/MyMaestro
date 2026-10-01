"""Faux runner DLSS5 pour les tests : même protocole que runners/dlss5_runner.py (une ligne JSON par événement)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path


def emettre(evenement: dict) -> None:
    sys.stdout.write(json.dumps(evenement) + "\n")
    sys.stdout.flush()


def main(chemin: str) -> int:
    demande = json.loads(Path(chemin).read_text(encoding="utf-8"))
    Path(chemin).with_name("options-recues.json").write_text(json.dumps(demande["options"]), encoding="utf-8")
    if os.environ.get("FAUX_DLSS5_ERREUR"):
        emettre({"type": "erreur", "message": os.environ["FAUX_DLSS5_ERREUR"]})
        return 1
    sortie = Path(demande["sortie_dossier"])
    sortie.mkdir(parents=True, exist_ok=True)
    emettre({"type": "progression", "valeur": 0.5, "description": "moitié"})
    if os.environ.get("FAUX_DLSS5_LENT"):
        time.sleep(60)
    cible = sortie / f"{Path(demande['entree']).stem}_DLSS5.mp4"
    shutil.copyfile(demande["entree"], cible)
    emettre({"type": "resultat", "duree_s": 0.1, "resultat": {"output_path": str(cible)}})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
