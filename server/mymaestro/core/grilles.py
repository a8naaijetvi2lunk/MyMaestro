"""Grilles de durée des moteurs vidéo.

Valeurs provisoires reprises de la documentation de Maestro (mesures du 2026-08-17) et
des handlers WanGP (frames_minimum 17, frames_steps 8 pour LTX). La tâche 0
(plan 2) les vérifie sur le matériel ; toute correction se fait ICI et nulle
part ailleurs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from ..contrat.modeles import FormatImage, MoteurVideo
from ..outils import gpu

FPS_MAITRE = 24

# Table _H3_PRUNED_WINDOW_MEMORY_POLICY de Maestro (app/models/minimax_h3/minimax_h3_handler.py, version épinglée) :
# bandes de pixels (min_pixels décroissant) × paliers de VRAM (Go ; None = au-delà) → images max (None = non supporté).
H3_POLITIQUE: tuple[tuple[int, tuple[tuple[float | None, int | None], ...]], ...] = (
    (1_800_000, ((8, None), (12, None), (16, 124), (24, 158), (32, 243), (None, 345))),
    (1_000_000, ((8, None), (12, 124), (16, 124), (24, 243), (None, 345))),
    (800_000, ((8, 124), (12, 124), (23, 243), (24, 345), (None, 345))),
    (500_000, ((8, 124), (12, 243), (None, 345))),
    (0, ((8, 243), (None, 345))),
)
H3_IMAGES_UTILES = 243  # 10,1 s : durée minimale utile d'un plan de clip (décision 3A du projet, rendue générale)


class Definition(StrEnum):
    P480 = "480p"  # 864×480
    P544 = "544p"  # 960×544
    P720 = "720p"  # 1280×704
    P1080 = "1080p"  # 1920×1088


# Dimensions de rendu en paysage (multiples de 32, exigence LTX) ; en portrait, largeur et hauteur sont inversées.
DIMENSIONS: dict[Definition, tuple[int, int]] = {
    Definition.P480: (864, 480),
    Definition.P544: (960, 544),
    Definition.P720: (1280, 704),
    Definition.P1080: (1920, 1088),
}

DEFINITION_PAR_DEFAUT = Definition.P544

# Résolutions de sortie après FlashVSR ×2 et recadrage à l'export (spec §5).
RESOLUTIONS_SORTIE: dict[FormatImage, tuple[int, int]] = {
    FormatImage.PAYSAGE: (1920, 1080),
    FormatImage.PORTRAIT: (1080, 1920),
}

# LTX : plafond de planification provisoire de 32 s par plan (celui du Director de Maestro).
LTX_PLAFOND_S = 32


@dataclass(frozen=True, slots=True)
class Grille:
    moteur: MoteurVideo
    fps: int
    images_min: int
    pas: int
    images_max: int

    def valeurs(self) -> list[int]:
        return list(range(self.images_min, self.images_max + 1, self.pas))

    def est_valide(self, images: int) -> bool:
        return self.images_min <= images <= self.images_max and (images - self.images_min) % self.pas == 0

    def duree_s(self, images: int) -> float:
        return images / self.fps

    def plus_proche(self, secondes: float) -> int:
        """Nombre d'images valide le plus proche d'une durée, borné à la grille."""
        cible = secondes * self.fps
        return min(self.valeurs(), key=lambda n: (abs(n - cible), n))

    @property
    def duree_min_s(self) -> float:
        return self.images_min / self.fps

    @property
    def duree_max_s(self) -> float:
        return self.images_max / self.fps


def plafond_h3(largeur: int, hauteur: int, vram_go: float | None = None) -> int | None:
    """Images max d'un plan H3 à cette résolution sur cette VRAM (None : non supporté). Même parcours que Maestro."""
    vram = gpu.vram_go() if vram_go is None else vram_go
    pixels = largeur * hauteur
    for min_pixels, paliers in H3_POLITIQUE:
        if pixels < min_pixels:
            continue
        for maximum, images in paliers:
            if maximum is None or vram <= maximum:
                return images
    return None


def _vram_requise_h3(definition: Definition) -> str:
    """Plancher réel de VRAM de cette définition (pour le message de refus) : la plus petite des VRAM citées par la table
    pour laquelle H3 atteint H3_IMAGES_UTILES (le palier « 23 Go » de la bande 800 000 px ouvre le 720p dès 16 Go)."""
    largeur, hauteur = DIMENSIONS[definition]
    candidats = sorted({maximum for _, paliers in H3_POLITIQUE for maximum, _ in paliers if maximum is not None})
    for vram in candidats:
        plafond = plafond_h3(largeur, hauteur, vram)
        if plafond is not None and plafond >= H3_IMAGES_UTILES:
            return f"{vram:g} Go et plus"
    return "plus de VRAM"


def _refus_definition(moteur: MoteurVideo, definition: Definition, vram: float) -> str:
    if moteur is MoteurVideo.H3:
        return f"H3 en {definition.value} exige plus de VRAM ({_vram_requise_h3(definition)}) : {vram:.1f} Go détectés".replace(".", ",")
    return f"définition {definition.value} non permise pour {moteur.value}"


def definitions_permises(
    moteur: MoteurVideo, fmt: FormatImage = FormatImage.PAYSAGE, vram_go: float | None = None
) -> tuple[Definition, ...]:
    """LTX : les trois. H3 : celles dont le plafond atteint H3_IMAGES_UTILES sur cette VRAM."""
    if moteur is not MoteurVideo.H3:
        return (Definition.P544, Definition.P720, Definition.P1080)
    vram = gpu.vram_go() if vram_go is None else vram_go
    permises = []
    for definition in Definition:
        largeur, hauteur = DIMENSIONS[definition]
        if fmt is FormatImage.PORTRAIT:
            largeur, hauteur = hauteur, largeur
        plafond = plafond_h3(largeur, hauteur, vram)
        if plafond is not None and plafond >= H3_IMAGES_UTILES:
            permises.append(definition)
    return tuple(permises)


def definition_par_defaut(
    moteur: MoteurVideo, fmt: FormatImage = FormatImage.PAYSAGE, vram_go: float | None = None
) -> Definition:
    """544p si elle est permise sur cette VRAM, sinon la plus grande définition permise (H3 sur 8 Go : 480p)."""
    permises = definitions_permises(moteur, fmt, vram_go)
    return DEFINITION_PAR_DEFAUT if not permises or DEFINITION_PAR_DEFAUT in permises else permises[-1]


def dimensions(fmt: FormatImage, definition: Definition) -> tuple[int, int]:
    """(largeur, hauteur) d'une définition selon le format, sans contrôle de permission."""
    largeur, hauteur = DIMENSIONS[definition]
    return (largeur, hauteur) if fmt is FormatImage.PAYSAGE else (hauteur, largeur)


def _plafond_ltx(fps: int) -> int:
    maximum = LTX_PLAFOND_S * fps
    return 17 + ((maximum - 17) // 8) * 8


def resolution_rendu(
    moteur: MoteurVideo, fmt: FormatImage, definition: Definition | None = None, vram_go: float | None = None
) -> tuple[int, int]:
    """(largeur, hauteur) de rendu ; ValueError si la définition n'est pas permise pour ce moteur sur cette VRAM.
    Sans définition : celle par défaut de ce moteur sur cette VRAM."""
    vram = gpu.vram_go() if vram_go is None else vram_go
    if definition is None:
        definition = definition_par_defaut(moteur, fmt, vram)
    if definition not in definitions_permises(moteur, fmt, vram):
        raise ValueError(_refus_definition(moteur, definition, vram))
    return dimensions(fmt, definition)


def saute_flashvsr(moteur: MoteurVideo, fmt: FormatImage, definition: Definition) -> bool:
    """Vrai si le grand côté du rendu atteint celui de la sortie (1920, en 16:9 comme en 9:16) : FlashVSR ×2 serait inutile.
    Ne contrôle pas la permission : une estimation ou un affichage ne doivent jamais échouer."""
    return max(dimensions(fmt, definition)) >= max(RESOLUTIONS_SORTIE[fmt])


def grille(
    moteur: MoteurVideo,
    fmt: FormatImage = FormatImage.PAYSAGE,
    definition: Definition | None = None,
    vram_go: float | None = None,
) -> Grille:
    """H3 : plafond selon les pixels de `resolution_rendu(moteur, fmt, definition)` et la VRAM ; LTX : inchangé."""
    if moteur is MoteurVideo.H3:
        vram = gpu.vram_go() if vram_go is None else vram_go
        largeur, hauteur = resolution_rendu(moteur, fmt, definition, vram)
        plafond = plafond_h3(largeur, hauteur, vram)
        if plafond is None or plafond < 124:
            raise ValueError(_refus_definition(moteur, definition, vram))
        return Grille(moteur, 24, 124, 17, plafond)
    if moteur is MoteurVideo.LTX23:
        return Grille(moteur, 25, 17, 8, _plafond_ltx(25))
    if moteur is MoteurVideo.LTX25:
        return Grille(moteur, 24, 17, 8, _plafond_ltx(24))
    raise ValueError(f"moteur inconnu : {moteur}")


def moteurs_compatibles(
    secondes: float,
    fmt: FormatImage = FormatImage.PAYSAGE,
    tolerance_s: float = 0.25,
    definitions: Mapping[MoteurVideo, Definition] | None = None,
) -> list[MoteurVideo]:
    """Moteurs dont la grille couvre `secondes` à `tolerance_s` près (sélecteur de l'étape 3)."""
    resultat: list[MoteurVideo] = []
    for moteur in MoteurVideo:
        g = grille(moteur, fmt, (definitions or {}).get(moteur))
        if g.duree_min_s - tolerance_s <= secondes <= g.duree_max_s + tolerance_s:
            resultat.append(moteur)
    return resultat
