"""Contexte passé aux modules : de quoi lire et écrire l'état, enfiler des jobs et publier."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config
from .db import Base
from .file import File
from .notify import sans_notification


def _sans_publication(evenement: dict[str, Any]) -> None:
    return None


def _sans_prevol(connecteur: str) -> None:
    return None


@dataclass
class Contexte:
    base: Base
    file: File
    dossier_projets: Path
    publier: Callable[[dict[str, Any]], None] = field(default=_sans_publication)
    dossier_medias: Path = field(default_factory=lambda: config.DOSSIER_MEDIAS)
    prevol: Callable[[str], None] = field(default=_sans_prevol)  # contrôle avant de démarrer un moteur réel (tâche 4)
    notifier: Callable[[str, str], None] = field(default=sans_notification)

    def dossier_projet(self, projet_id: str) -> Path:
        return Path(self.dossier_projets) / projet_id
