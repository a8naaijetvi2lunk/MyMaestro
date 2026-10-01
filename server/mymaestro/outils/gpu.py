"""Carte graphique : nom et VRAM, lus par nvidia-smi (ou forcés par la config), mis en cache pour la session.

Contient aussi la lecture de la VRAM utilisée (échantillonneur des sondes).
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from .. import config

REQUETE = ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]

VRAM_REPLI_MO = 12282  # carte de référence (RTX 4070 Ti 12 Go) quand rien n'est détecté
VRAM_MINIMALE_GO = 12.0  # minimum recommandé, en Go (le contrôle se fait sur VRAM_MINIMALE_MO)
VRAM_MINIMALE_MO = 12 * 1024 - 256  # marge : une carte de 12 Go annonce 11,9 à 12,0 Go selon les modèles


@dataclass(frozen=True)
class Gpu:
    nom: str
    vram_mo: int
    source: str  # « nvidia-smi » ou « config »

    @property
    def vram_go(self) -> float:
        """Comme Maestro (services/hardware_detect.py) : Gio arrondis au dixième."""
        return round(self.vram_mo / 1024, 1)


def lire_sortie_nvidia_smi(texte: str) -> Gpu | None:
    """Première carte de `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`
    (« NVIDIA GeForce RTX 4070 Ti, 12282 ») ; None si illisible."""
    for ligne in texte.splitlines():
        morceaux = [m.strip() for m in ligne.rsplit(",", 1)]
        if len(morceaux) == 2 and morceaux[1].isdigit() and morceaux[0]:
            return Gpu(nom=morceaux[0], vram_mo=int(morceaux[1]), source="nvidia-smi")
    return None


_CARTE: Gpu | None = None  # cache de module : seule une détection réussie y est mémorisée


def vider_cache() -> None:
    global _CARTE
    _CARTE = None


def detecter_gpu() -> Gpu | None:
    """Carte détectée, mémorisée pour la session ; une détection ratée (nvidia-smi absent un instant) n'est pas mémorisée."""
    global _CARTE
    if _CARTE is None:
        _CARTE = detecter_sans_cache()
    return _CARTE


def detecter_sans_cache() -> Gpu | None:
    forcee = config.reglage("MYMAESTRO_VRAM_MO", "vram_mo", None)
    if forcee not in (None, ""):
        try:
            mo = int(forcee)
        except (ValueError, TypeError):
            mo = 0
        if mo >= 1024:  # en dessous, c'est sûrement une valeur en Go ou absurde
            return Gpu(nom="VRAM forcée par la configuration", vram_mo=mo, source="config")
        config.avertir_une_fois("vram_mo %r ignoré : un nombre entier de Mo (1024 ou plus) est attendu", forcee)
    try:
        sortie = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return lire_sortie_nvidia_smi(sortie.stdout) if sortie.returncode == 0 else None


def vram_mo() -> int:
    carte = detecter_gpu()
    return carte.vram_mo if carte else VRAM_REPLI_MO


def vram_go() -> float:
    return round(vram_mo() / 1024, 1)


def parser_vram(texte: str) -> tuple[int, int]:
    """Premier GPU de la sortie nvidia-smi : (Mo utilisés, Mo totaux)."""
    premiere = texte.strip().splitlines()[0]
    utilisee, totale = (int(valeur.strip()) for valeur in premiere.split(","))
    return utilisee, totale


def lire_vram() -> tuple[int, int]:
    sortie = subprocess.run(REQUETE, capture_output=True, text=True, check=True, timeout=10)
    return parser_vram(sortie.stdout)


@dataclass
class EchantillonneurVram:
    """Relève la VRAM utilisée en tâche de fond.

    Usage : `with EchantillonneurVram() as vram: ...` puis `vram.pic_mo`.
    """

    intervalle_s: float = 0.5
    lecteur: Callable[[], tuple[int, int]] = lire_vram
    releves: list[int] = field(default_factory=list)
    _arret: threading.Event = field(default_factory=threading.Event, repr=False)
    _fil: threading.Thread | None = field(default=None, repr=False)

    def _boucle(self) -> None:
        while not self._arret.is_set():
            try:
                self.releves.append(self.lecteur()[0])
            except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
                pass
            self._arret.wait(self.intervalle_s)

    def __enter__(self) -> EchantillonneurVram:
        self._fil = threading.Thread(target=self._boucle, daemon=True)
        self._fil.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._arret.set()
        if self._fil is not None:
            self._fil.join(5)

    @property
    def pic_mo(self) -> int | None:
        return max(self.releves) if self.releves else None
