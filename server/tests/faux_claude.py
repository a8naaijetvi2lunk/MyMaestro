"""Fausse CLI `claude` pour les tests : trace ses arguments, sa consigne et son dossier, rend une sortie choisie."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

if __name__ == "__main__":
    consigne = sys.stdin.read()
    trace = os.environ.get("FAUX_CLAUDE_TRACE")
    if trace:
        Path(trace).write_text(json.dumps({"argv": sys.argv[1:], "consigne": consigne, "dossier": os.getcwd()}), encoding="utf-8")
    if os.environ.get("FAUX_CLAUDE_LENT"):
        time.sleep(60)
    sys.stdout.write(os.environ.get("FAUX_CLAUDE_SORTIE", json.dumps({"structured_output": {"reponse": "d'accord"}})))
    sys.exit(int(os.environ.get("FAUX_CLAUDE_CODE", "0")))
