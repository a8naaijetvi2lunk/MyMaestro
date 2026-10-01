"""Écrit le schéma OpenAPI de MyMaestro (par défaut dans server/openapi.json).

Usage : `uv run python -m mymaestro.exporter_openapi [destination]` depuis server/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .app import creer_app

DESTINATION_PAR_DEFAUT = Path(__file__).resolve().parents[1] / "openapi.json"


def exporter(destination: Path) -> Path:
    schema = creer_app().openapi()
    destination.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination


if __name__ == "__main__":
    cible = Path(sys.argv[1]) if len(sys.argv) > 1 else DESTINATION_PAR_DEFAUT
    print(exporter(cible))
