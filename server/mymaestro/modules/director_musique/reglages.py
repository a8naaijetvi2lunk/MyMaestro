"""Réglages de recette du module Director musique (spec D11) : source du schéma de l'écran Recette.

Chaque champ porte un titre et une description en français : l'écran Recette est généré à
partir du schéma JSON de ce modèle, sans écran codé à la main pour chaque phase. Annotations
lues par l'interface :
- « x-libelles » : libellé affiché pour chaque valeur d'une énumération ;
- « x-controle » : contrôle imposé (« segments » pour un choix court, « fige » pour une valeur
  non modifiable) ;
- « x-titre-general » : titre de la carte qui regroupe les champs de premier niveau.
La docstring d'un groupe devient sa description sous la carte.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ... import config
from ...contrat.modeles import FormatImage, MoteurImage, MoteurVideo
from ...core.grilles import Definition


def interface(libelles: dict[str, str] | None = None, controle: str | None = None) -> dict[str, Any]:
    """Annotations d'interface ajoutées au schéma JSON d'un champ."""
    extra: dict[str, Any] = {}
    if libelles:
        extra["x-libelles"] = libelles
    if controle:
        extra["x-controle"] = controle
    return extra


LIBELLES_MOTEUR_VIDEO = {
    MoteurVideo.H3.value: "MiniMax H3 (FL2VA)",
    MoteurVideo.LTX23.value: "LTX-2.3 + OmniNFT",
    MoteurVideo.LTX25.value: "LTX-2.5 + OmniNFT",
}
LIBELLES_MOTEUR_IMAGE = {
    MoteurImage.QWEN.value: "Qwen Image Edit 2511 FP8",
    MoteurImage.CODEX.value: "Codex imagegen (gpt-image-2)",
}


class Reglages(BaseModel):
    model_config = ConfigDict(extra="forbid")


MODELE_ECRITURE_CLAUDE = "claude-opus-5-5"
MODELE_PROMPTS_CLAUDE = "sonnet"


class Fournisseur(StrEnum):
    CLAUDE = "claude"
    BONSAI = "bonsai"


class Effort(StrEnum):
    FAIBLE = "low"
    MOYEN = "medium"
    ELEVE = "high"
    TRES_ELEVE = "xhigh"
    MAX = "max"


class Arrets(Reglages):
    """Vidéo et post-production : toujours en autonomie, jusqu'au bout de la file. Un arrêt décoché applique les valeurs pré-cochées."""

    analyse: bool = Field(False, title="Après l'analyse", description="Relire le calage des paroles sur la voix")
    ecriture: bool = Field(True, title="Après l'écriture", description="Concept retenu et découpage")
    prompts: bool = Field(
        True, title="Après les prompts", description="C'est ici que tu choisis le moteur de chaque plan et de chaque image"
    )
    images: bool = Field(True, title="Après les images", description="Images de départ, avant les heures de GPU de la vidéo")


class LlmEcriture(Reglages):
    fournisseur: Fournisseur = Field(
        Fournisseur.CLAUDE,
        title="Fournisseur",
        description="L'écriture passe par Opus 5.5 ; Bonsai 2 seulement quand Claude n'est pas installé (change aussi le modèle)",
        json_schema_extra=interface({"claude": "Claude", "bonsai": "Bonsai 2"}),
    )
    modele: str = Field(
        MODELE_ECRITURE_CLAUDE,
        title="Modèle",
        json_schema_extra=interface({"claude-opus-5-5": "Opus 5.5", "bonsai2-27b-pq2": "Bonsai 2 (27B)"}),
    )
    effort: Effort = Field(
        Effort.ELEVE,
        title="Effort de réflexion",
        json_schema_extra=interface(
            {"low": "Faible", "medium": "Moyen", "high": "Élevé", "xhigh": "Très élevé", "max": "Max"}, "segments"
        ),
    )
    nombre_concepts: int = Field(3, ge=1, le=5, title="Concepts proposés au départ")

    @model_validator(mode="after")
    def _aligner_le_modele(self) -> "LlmEcriture":
        """Le modèle suit le fournisseur : Bonsai → son modèle ; Claude avec un modèle Bonsai → le défaut de Claude."""
        if self.fournisseur is Fournisseur.BONSAI:
            self.modele = config.BONSAI_MODELE
        elif self.modele == config.BONSAI_MODELE:
            self.modele = MODELE_ECRITURE_CLAUDE
        return self


class LlmEtape(Reglages):
    fournisseur: Fournisseur = Field(
        Fournisseur.CLAUDE, title="Fournisseur", json_schema_extra=interface({"claude": "Claude", "bonsai": "Bonsai 2"})
    )
    modele: str = Field(MODELE_PROMPTS_CLAUDE, title="Modèle", description="sonnet ou opus pour Claude, bonsai2-27b-pq2 pour Bonsai")
    reflexion: bool = Field(
        False,
        title="Réflexion (Bonsai)",
        description="Désactivée par défaut : même conformité JSON, 16 s au lieu de 26 à 112 s (tâche 0)",
    )

    @model_validator(mode="after")
    def _aligner_le_modele(self) -> "LlmEtape":
        """Comme pour l'écriture : Bonsai → son modèle ; Claude avec un modèle Bonsai → Sonnet."""
        if self.fournisseur is Fournisseur.BONSAI:
            self.modele = config.BONSAI_MODELE
        elif self.modele == config.BONSAI_MODELE:
            self.modele = MODELE_PROMPTS_CLAUDE
        return self


class Llm(Reglages):
    """Chaque sortie est validée par un schéma. Si Bonsai rend un JSON invalide : une relance, puis bascule sur Claude, signalée."""

    ecriture: LlmEcriture = Field(default_factory=LlmEcriture, title="Écriture")
    prompts_image: LlmEtape = Field(default_factory=LlmEtape, title="Prompts image")
    prompts_video: LlmEtape = Field(default_factory=LlmEtape, title="Prompts vidéo")
    prompts_son: LlmEtape = Field(default_factory=LlmEtape, title="Prompts son")


class MoteursPrecoches(Reglages):
    """Valeurs de départ seulement : le choix final se fait plan par plan et image par image, à la validation."""

    chante: MoteurVideo = Field(MoteurVideo.LTX23, title="Plans chantés", json_schema_extra=interface(LIBELLES_MOTEUR_VIDEO))
    coupe: MoteurVideo = Field(MoteurVideo.LTX23, title="Plans de coupe", json_schema_extra=interface(LIBELLES_MOTEUR_VIDEO))
    image: MoteurImage = Field(MoteurImage.QWEN, title="Images", json_schema_extra=interface(LIBELLES_MOTEUR_IMAGE))


class FlashVsr(Reglages):
    actif: bool = Field(True, title="FlashVSR")
    facteur: Literal[2] = Field(2, title="Facteur", json_schema_extra=interface({"2": "×2"}, "fige"))


class Dlss5(Reglages):
    actif: bool = Field(True, title="DLSS5")
    style: Literal["Cinematic", "Default"] = Field("Cinematic", title="Style")
    intensite: float = Field(1.0, ge=0, le=2, title="Intensité")
    ton_local: float = Field(1.0, ge=0, le=2, title="Ton local")
    structure: float = Field(1.0, ge=0, le=2, title="Structure")
    facteur: float = Field(1.0, ge=1, le=2, title="Facteur d'agrandissement")


class PostProd(Reglages):
    """Chaîne appliquée à chaque plan : rendu, puis FlashVSR ×2, puis DLSS5."""

    flashvsr: FlashVsr = Field(default_factory=FlashVsr, title="FlashVSR")
    dlss5: Dlss5 = Field(default_factory=Dlss5, title="DLSS5")


class Export(Reglages):
    interpolation_60fps: bool = Field(
        False, title="Interpolation 60 fps (DLSSG)", description="Appliquée une seule fois, au montage final"
    )


class Rendu(Reglages):
    """Résolution de rendu de chaque moteur vidéo. Un rendu en 1080p saute FlashVSR ×2 (déjà à la taille de sortie)."""

    h3: Literal["480p", "544p", "720p", "1080p"] = Field(
        "544p",
        title="H3",
        json_schema_extra=interface({
            "480p": "864×480 · plans ≤ 14,4 s",
            "544p": "960×544 · plans ≤ 10,1 s sur 12 Go",
            "720p": "720p · 1280×704 · 16 Go de VRAM et plus",
            "1080p": "1080p · 1920×1088 · 32 Go de VRAM et plus",
        }),
    )
    ltx23: Literal["544p", "720p", "1080p"] = Field("544p", title="LTX-2.3", json_schema_extra=interface({"544p": "960×544", "720p": "720p · 1280×704", "1080p": "1080p · 1920×1088"}))
    ltx25: Literal["544p", "720p", "1080p"] = Field("544p", title="LTX-2.5", json_schema_extra=interface({"544p": "960×544", "720p": "720p · 1280×704", "1080p": "1080p · 1920×1088"}))

    def definition(self, moteur: MoteurVideo) -> Definition:
        return Definition({MoteurVideo.H3: self.h3, MoteurVideo.LTX23: self.ltx23, MoteurVideo.LTX25: self.ltx25}[moteur])

    def definitions(self) -> dict[MoteurVideo, Definition]:
        return {moteur: self.definition(moteur) for moteur in MoteurVideo}


class ReglagesDirector(Reglages):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-titre-general": "Rendu"})

    format: FormatImage = Field(
        FormatImage.PAYSAGE,
        title="Format",
        json_schema_extra=interface({"16:9": "16:9 · paysage", "9:16": "9:16 · vertical"}, "segments"),
    )
    rendu: Rendu = Field(default_factory=Rendu, title="Résolution de rendu")
    arrets: Arrets = Field(default_factory=Arrets, title="Arrêts pour validation")
    llm: Llm = Field(default_factory=Llm, title="Modèles de langage")
    moteurs_precoches: MoteursPrecoches = Field(default_factory=MoteursPrecoches, title="Moteurs pré-cochés")
    postprod: PostProd = Field(default_factory=PostProd, title="Post-production par plan")
    export: Export = Field(default_factory=Export, title="Export")
