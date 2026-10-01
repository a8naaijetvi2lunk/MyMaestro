"""Appels HTTP JSON minimalistes (bibliothèque standard) vers les moteurs locaux."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


def get_json(url: str, timeout: float = 10) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def post_json(url: str, corps: dict[str, Any] | None = None, timeout: float = 30) -> Any:
    donnees = json.dumps(corps or {}).encode("utf-8")
    requete = urllib.request.Request(
        url, data=donnees, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(requete, timeout=timeout) as reponse:
        texte = reponse.read().decode("utf-8")
        return json.loads(texte) if texte else None


def attendre(url: str, delai_s: float, intervalle_s: float = 1.0) -> bool:
    """Interroge `url` jusqu'à obtenir un 200, ou jusqu'à l'expiration de `delai_s`."""
    limite = time.monotonic() + delai_s
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(url, timeout=max(1.0, intervalle_s + 2)) as reponse:
                if reponse.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(intervalle_s)
    return False
