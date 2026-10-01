"""Contrat de données de l'API MyMaestro (source des types TypeScript).

Ces modèles décrivent ce que l'API expose. Ils ne connaissent ni SQLite ni les
moteurs : la persistance (plan 3) et les connecteurs (plans 3 et 6) s'y
conforment. Toute évolution passe par ici, puis par l'export OpenAPI.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

MOTIF_PISTE = r"^(V[1-9][0-9]*|A[0-9]+)$"


class Modele(BaseModel):
    # Champs à valeur par défaut obligatoires EN SORTIE : les types TypeScript générés ne les
    # rendent plus optionnels (constat du plan 1 : gardes « ?? [] » inutiles dans l'interface).
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, json_schema_serialization_defaults_required=True)


class FormatImage(StrEnum):
    PAYSAGE = "16:9"
    PORTRAIT = "9:16"


class RolePlan(StrEnum):
    CHANTE = "chante"
    COUPE = "coupe"


class MoteurVideo(StrEnum):
    H3 = "minimax_h3"
    LTX23 = "ltx2_22B_distilled_1_1_omninft"
    LTX25 = "ltx2_25_omninft"


class MoteurImage(StrEnum):
    QWEN = "qwen_image_edit_2511_20B_fp8_lightning_8step"
    CODEX = "codex_imagegen"


class EtatClip(StrEnum):
    PREVU = "prevu"
    EN_FILE = "en_file"
    EN_RENDU = "en_rendu"
    BRUT = "brut"
    UPSCALE = "upscale"
    DLSS5 = "dlss5"
    ECHEC = "echec"


class EtapePostProd(StrEnum):
    FLASHVSR = "flashvsr"
    DLSS5 = "dlss5"


class StatutTraitement(StrEnum):
    EN_FILE = "en_file"
    EN_COURS = "en_cours"
    TERMINE = "termine"
    ECHEC = "echec"


class Voie(StrEnum):
    GPU = "gpu"
    CLOUD = "cloud"


class StatutJob(StrEnum):
    EN_FILE = "en_file"
    EN_COURS = "en_cours"
    TERMINE = "termine"
    ECHEC = "echec"
    ANNULE = "annule"


class TypeFiche(StrEnum):
    PERSONNAGE = "personnage"
    DECOR = "decor"
    STYLE = "style"


class RoleImageFiche(StrEnum):
    PORTRAIT_PIED = "portrait_pied"
    GROS_PLAN = "gros_plan"
    REFERENCE = "reference"


class EtatMoteur(StrEnum):
    ARRETE = "arrete"
    DEMARRE = "demarre"
    CHARGE = "charge"


class Regime(StrEnum):
    PHASES = "phases"
    CARTE = "carte"


class TypeAction(StrEnum):
    REFAIRE = "refaire"
    PASSE_DLSS5 = "passe_dlss5"
    BRUITAGE = "bruitage"
    CHANGER_MOTEUR = "changer_moteur"


class StatutAction(StrEnum):
    PROGRAMMEE = "programmee"
    LANCEE = "lancee"


class EtatPhase(StrEnum):
    A_FAIRE = "a_faire"
    EN_COURS = "en_cours"
    A_VALIDER = "a_valider"
    TERMINE = "termine"
    ECHEC = "echec"


class Sante(Modele):
    statut: str
    version: str
    schema_db: int


class InfosMateriel(Modele):
    """Carte graphique détectée (ou repli sur la carte de référence)."""

    gpu: str | None
    vram_mo: int
    vram_go: float
    source: str  # « nvidia-smi », « config » ou « repli »
    suffisant: bool
    avertissement: str | None


class EtatMoteurInstalle(Modele):
    """État d'installation d'un moteur (écran « Moteurs »)."""

    id: str
    libelle: str
    requis: bool
    etat: str  # valeurs d'EtatInstallation : absent, installe, externe, version_differente, incomplet, en_cours
    version_attendue: str
    espace_mo: int
    note: str | None = None
    progression: float | None = None
    etape: str | None = None
    message: str | None = None
    journal: str | None = None  # chemin du dernier journal d'installation
    connecte: bool | None = None  # Claude seulement : connexion à l'abonnement


class EtatMoteurs(Modele):
    moteurs: list[EtatMoteurInstalle]
    requis_manquants: bool
    mode_demo: bool  # MYMAESTRO_MOTEURS_REELS=aucun : tout est simulé, rien n'est bloqué
    en_cours: str | None = None
    redemarrage_requis: bool = False  # une installation a réussi : MyMaestro doit redémarrer pour piloter le moteur


class Plan(Modele):
    id: str
    indice: int = Field(ge=0)
    role: RolePlan
    debut_s: float = Field(ge=0)
    images: int = Field(gt=0)
    fps: int = Field(gt=0)
    paroles: str = ""
    description: str = ""
    moteur_image: MoteurImage | None = None
    moteur_video: MoteurVideo | None = None
    fiches: list[str] = Field(default_factory=list)
    prise_active_id: str | None = None
    prompt_image: str = ""
    prompt_video: str = ""
    prompt_son: str = ""
    image_depart: str | None = None

    @computed_field
    @property
    def duree_s(self) -> float:
        return self.images / self.fps


class SortiePostProd(Modele):
    id: str
    etape: EtapePostProd
    ordre: int = Field(ge=1)
    statut: StatutTraitement
    fichier: str | None = None
    reglages: dict[str, Any] = Field(default_factory=dict)
    erreur: str | None = None


class Prise(Modele):
    id: str
    plan_id: str
    numero: int = Field(ge=1)
    moteur: MoteurVideo
    graine: int | None = None
    statut: StatutTraitement
    fichier_brut: str | None = None
    erreur: str | None = None
    sorties: list[SortiePostProd] = Field(default_factory=list)
    sortie_active_id: str | None = None

    @model_validator(mode="after")
    def _sortie_active_connue(self) -> Prise:
        if self.sortie_active_id is not None and self.sortie_active_id not in {s.id for s in self.sorties}:
            raise ValueError("sortie_active_id ne désigne aucune sortie de cette prise")
        return self


class Clip(Modele):
    id: str
    piste: str = Field(pattern=MOTIF_PISTE)
    plan_id: str | None = None
    fichier_audio: str | None = None
    position_s: float = Field(ge=0)
    entree_s: float = Field(default=0, ge=0)
    sortie_s: float = Field(gt=0)
    verrou_chanson: bool = False
    etat: EtatClip | None = None
    progression: float | None = Field(default=None, ge=0, le=1)  # rendu en cours (déduit de la file, jamais stocké)
    volume: float = Field(default=1.0, ge=0, le=2)
    fondu_entree_s: float = Field(default=0, ge=0)
    fondu_sortie_s: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _bornes_coherentes(self) -> Clip:
        if self.sortie_s <= self.entree_s:
            raise ValueError("sortie_s doit être strictement supérieur à entree_s")
        if self.piste.startswith("V") and self.plan_id is None:
            raise ValueError("un clip vidéo doit désigner un plan")
        if self.piste.startswith("A") and self.fichier_audio is None:
            raise ValueError("un clip audio doit désigner un fichier")
        return self

    @computed_field
    @property
    def duree_s(self) -> float:
        return self.sortie_s - self.entree_s

    @computed_field
    @property
    def fin_s(self) -> float:
        return self.position_s + self.sortie_s - self.entree_s


class Timeline(Modele):
    projet_id: str
    fps_maitre: int = 24
    duree_chanson_s: float = Field(gt=0)
    pistes: list[str]
    clips: list[Clip]

    @model_validator(mode="after")
    def _regles(self) -> Timeline:
        for piste in self.pistes:
            if not re.fullmatch(MOTIF_PISTE, piste):
                raise ValueError(f"nom de piste invalide : {piste}")
        inconnues = {c.piste for c in self.clips} - set(self.pistes)
        if inconnues:
            raise ValueError(f"clips sur des pistes non déclarées : {sorted(inconnues)}")
        for piste in self.pistes:
            clips = sorted((c for c in self.clips if c.piste == piste), key=lambda c: c.position_s)
            for avant, apres in zip(clips, clips[1:]):
                if apres.position_s < avant.fin_s - 1e-6:
                    raise ValueError(f"chevauchement sur la piste {piste} : {avant.id} et {apres.id}")
        return self


class ResumeProjet(Modele):
    id: str
    titre: str
    module: str
    format: FormatImage
    cree_le: str
    nb_plans: int = Field(ge=0)
    recette_id: str | None = None


class Projet(Modele):
    id: str
    titre: str
    module: str
    format: FormatImage
    cree_le: str
    recette_id: str | None = None
    chanson: str | None = None
    paroles: str = ""
    duree_chanson_s: float | None = None
    casting: list[str] = Field(default_factory=list)
    etat_phases: dict[str, EtatPhase] = Field(default_factory=dict)
    plans: list[Plan] = Field(default_factory=list)
    prises: list[Prise] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherence(self) -> Projet:
        if [p.indice for p in self.plans] != list(range(len(self.plans))):
            raise ValueError("les indices de plans doivent valoir 0, 1, 2… dans l'ordre")
        ids_plans = {p.id for p in self.plans}
        prises_par_id = {p.id: p for p in self.prises}
        for prise in self.prises:
            if prise.plan_id not in ids_plans:
                raise ValueError(f"la prise {prise.id} est rattachée à un plan inconnu")
        for plan in self.plans:
            if plan.prise_active_id is not None:
                prise = prises_par_id.get(plan.prise_active_id)
                if prise is None or prise.plan_id != plan.id:
                    raise ValueError(f"prise active invalide pour {plan.id}")
        return self


class ImageFiche(Modele):
    id: str
    role: RoleImageFiche
    chemin: str


class FicheBibliotheque(Modele):
    id: str
    type: TypeFiche
    nom: str
    description: str = ""
    images: list[ImageFiche] = Field(default_factory=list)
    projets: list[str] = Field(default_factory=list)


class Recette(Modele):
    id: str
    module: str
    nom: str
    valeurs: dict[str, Any] = Field(default_factory=dict)


class EtatConnecteur(Modele):
    nom: str
    voie: Voie
    etat: EtatMoteur
    empreinte_vram_mo: int = Field(ge=0)
    vram_residuelle_mo: int = Field(ge=0)
    simule: bool = False


class Job(Modele):
    id: str
    voie: Voie
    connecteur: str
    modele: str | None = None
    statut: StatutJob
    tentatives: int = Field(default=0, ge=0)
    progression: float = Field(default=0, ge=0, le=1)
    libelle: str = ""
    erreur: str | None = None
    phase: str | None = None
    ordre: int = 0
    regime: Regime = Regime.PHASES
    projet_id: str | None = None


class EtatFile(Modele):
    gpu_occupe_par: str | None = None
    en_marche: bool = False
    jobs: list[Job] = Field(default_factory=list)
    connecteurs: list[EtatConnecteur] = Field(default_factory=list)
    vram_totale_mo: int = 0


class PhaseModule(Modele):
    id: str
    nom: str
    arret_possible: bool
    connecteurs: list[str] = Field(default_factory=list)


class ManifesteModule(Modele):
    id: str
    nom: str
    description: str
    phases: list[PhaseModule]
    schema_reglages: dict[str, Any]


class RecetteEntree(Modele):
    module: str
    nom: str = Field(min_length=1, max_length=120)
    valeurs: dict[str, Any] = Field(default_factory=dict)


class FicheEntree(Modele):
    type: TypeFiche
    nom: str = Field(min_length=1, max_length=120)
    description: str = ""


class ActionEntree(Modele):
    type: TypeAction
    plan_id: str | None = None
    clip_id: str | None = None
    reglages: dict[str, Any] = Field(default_factory=dict)


class ActionProgrammee(Modele):
    id: str
    projet_id: str
    type: TypeAction
    plan_id: str | None = None
    clip_id: str | None = None
    reglages: dict[str, Any] = Field(default_factory=dict)
    statut: StatutAction
    cree_le: str


class Lancement(Modele):
    jobs: list[str]


class InfosRenduMoteur(Modele):
    moteur: MoteurVideo
    definition: str  # « 544p », « 720p »…
    largeur: int
    hauteur: int
    images_max: int  # grille du moteur à cette définition
    duree_max_s: float
    saute_flashvsr: bool
    definitions_permises: list[str]  # définitions proposées pour ce moteur sur la VRAM détectée


class InfosRendu(Modele):
    format: FormatImage
    moteurs: list[InfosRenduMoteur]
    fps_maitre: int
    largeur_sortie: int
    hauteur_sortie: int


class ProjetEntree(Modele):
    titre: str = Field(min_length=1, max_length=120)
    format: FormatImage = FormatImage.PAYSAGE
    recette_id: str | None = None
    paroles: str = Field("", max_length=20000)
    casting: list[str] = Field(default_factory=list)


class PlanModification(Modele):
    """Champs modifiables d'un plan pendant la validation ; None = inchangé."""

    moteur_video: MoteurVideo | None = None
    moteur_image: MoteurImage | None = None
    prompt_image: str | None = None
    prompt_video: str | None = None
    prompt_son: str | None = None


class CompatibiliteMoteur(Modele):
    moteur: MoteurVideo
    compatible: bool
    images: int | None = None
    duree_s: float | None = None
    note: str | None = None
    avertissement: str | None = None


# --- Timeline, phase 5 et export (plan 5a) ------------------------------------------------------


class TypePiste(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class Segment(Modele):
    """Morceau de la projection de la timeline : ce qui est vu, et exporté, entre deux instants."""

    debut_s: float = Field(ge=0)
    fin_s: float = Field(gt=0)
    clip_id: str | None = None
    plan_id: str | None = None
    fichier: str | None = None  # relatif au dossier du projet ; None = image noire
    source_debut_s: float = Field(default=0, ge=0)


class ClipModification(Modele):
    """Champs modifiables d'un clip de timeline ; None = inchangé."""

    piste: str | None = Field(None, pattern=MOTIF_PISTE)
    position_s: float | None = Field(None, ge=0)
    entree_s: float | None = Field(None, ge=0)
    sortie_s: float | None = Field(None, gt=0)
    verrou_chanson: bool | None = None
    volume: float | None = Field(None, ge=0, le=2)
    fondu_entree_s: float | None = Field(None, ge=0)
    fondu_sortie_s: float | None = Field(None, ge=0)


class Coupe(Modele):
    temps_s: float = Field(gt=0)


class NouvellePiste(Modele):
    type: TypePiste


class ChoixPrise(Modele):
    prise_id: str


class ChoixSortie(Modele):
    sortie_id: str | None = None  # None : la prise part au montage en brut


class Nettoyage(Modele):
    prises_supprimees: int = Field(ge=0)
    octets_liberes: int = Field(ge=0)


class EstimationVideo(Modele):
    plans: int = Field(ge=0)
    octets_necessaires: int = Field(ge=0)
    octets_libres: int = Field(ge=0)
    suffisant: bool


class ExportEntree(Modele):
    interpolation_60fps: bool | None = None  # None : valeur de la recette


class ExportProjet(Modele):
    id: str
    cree_le: str
    statut: StatutTraitement
    interpolation_60fps: bool
    duree_s: float = Field(gt=0)
    fichier: str | None = None
    fichier_60fps: str | None = None
    erreur: str | None = None

