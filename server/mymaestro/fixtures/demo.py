"""Données factices réalistes (spec §9).

Un clip d'une minute dont chaque plan respecte la grille de son moteur :
l'interface se construit sur des données qui pourront exister pour de vrai.
Ce module est remplacé par la persistance SQLite au plan 3.
"""

from __future__ import annotations

from ..contrat.modeles import (
    Clip,
    EtapePostProd,
    EtatClip,
    FicheBibliotheque,
    FormatImage,
    ImageFiche,
    MoteurImage,
    MoteurVideo,
    Plan,
    Prise,
    Projet,
    Recette,
    ResumeProjet,
    RoleImageFiche,
    RolePlan,
    SortiePostProd,
    StatutTraitement,
    Timeline,
    TypeFiche,
)
from ..core.grilles import FPS_MAITRE, grille

PROJET_DEMO = "demo-nuit-blanche"
PROJET_VERTICAL = "demo-reel-vertical"
RECETTE_DEMO = "recette-clip-nuit"
DUREE_CHANSON_S = 60.0
CREE_LE = "2026-09-29T20:00:00+02:00"

# (rôle, moteur, images, paroles, description) — chaque nombre d'images est sur la grille du moteur.
_DECOUPAGE: tuple[tuple[RolePlan, MoteurVideo, int, str, str], ...] = (
    (RolePlan.COUPE, MoteurVideo.LTX23, 121, "", "Ville de nuit sous la pluie, travelling latéral sur les néons."),
    (RolePlan.CHANTE, MoteurVideo.H3, 243, "Je marche seule quand la ville s'endort", "Lina chante face caméra sur le toit-terrasse."),
    (RolePlan.COUPE, MoteurVideo.LTX25, 121, "", "Gros plan sur une flaque où tremblent les enseignes."),
    (RolePlan.CHANTE, MoteurVideo.H3, 226, "Les néons comptent mes pas jusqu'au matin", "Lina en plan taille, la pluie redouble."),
    (RolePlan.COUPE, MoteurVideo.LTX23, 121, "", "Un métro aérien traverse le cadre."),
    (RolePlan.CHANTE, MoteurVideo.H3, 243, "Nuit blanche, cœur battant", "Refrain : Lina tourne sur elle-même, caméra en arc."),
    (RolePlan.COUPE, MoteurVideo.LTX25, 145, "", "Silhouettes derrière une vitre embuée."),
    (RolePlan.CHANTE, MoteurVideo.H3, 209, "Et je garde la lumière", "Lina s'arrête, regard caméra, fin de phrase tenue."),
)

# (prompt_image, prompt_video, prompt_son) de chaque plan, en anglais comme ceux que rendent les modèles.
_PROMPTS: tuple[tuple[str, str, str], ...] = (
    (
        "Wide night street in the rain, magenta and cyan neon signs reflected in deep puddles on wet asphalt, "
        "empty sidewalk, cinematic, shallow depth of field",
        "Slow lateral tracking shot along a rain-soaked street at night, neon signs reflecting in deep puddles, "
        "light drizzle already falling, cinematic, shallow depth of field",
        "Rain on asphalt, distant traffic hum",
    ),
    (
        "Young woman with short black hair and a burgundy leather jacket facing the camera on a rooftop terrace at night, "
        "antennas and a glowing city below, magenta rim light, rain on her shoulders",
        "The woman is already singing straight into the lens, subtle head movements, the camera pushes in slowly, "
        "rain streaking through magenta and cyan light, the city lights flickering behind her",
        "Her close, breathy vocal over a low synth pad, rain pattering on the rooftop",
    ),
    (
        "Extreme close-up of a puddle on dark asphalt, blurred neon signs trembling on its surface, raindrops frozen mid-fall",
        "Raindrops already hitting the puddle, rings spreading and breaking the neon reflections, "
        "the camera tilts down slowly, macro lens, shallow depth of field",
        "Close water drops and a soft electronic pulse",
    ),
    (
        "Medium waist-up shot of the same woman in her burgundy jacket on the rooftop, heavier rain, "
        "wet hair stuck to her face, cyan light from the right, city bokeh behind",
        "She keeps singing while the rain gets heavier, a slow handheld drift to the left, "
        "drops catching the cyan light, her jacket glistening",
        "Heavier rain, her voice rising over steady synth bass",
    ),
    (
        "Elevated metro viaduct at night above a rainy avenue, a train entering the frame from the left, "
        "lit windows blurred, magenta haze, wet rails",
        "An elevated metro train is already crossing the frame from left to right, windows streaking light, "
        "the camera holds low and static, rain falling through the glow",
        "Metro rumble passing overhead, wheels on the rails",
    ),
    (
        "The woman in the burgundy jacket spinning in the middle of the rooftop, arms slightly open, "
        "neon city lights smeared into colored streaks, rain drops suspended around her",
        "She is already mid-spin, her jacket flaring, the camera sweeps around her in a wide arc, "
        "neon lights stretching into magenta and cyan streaks, rain whipping through the air",
        "Chorus: layered vocals, driving beat at 118 BPM, bright synth arpeggio",
    ),
    (
        "Silhouettes of people behind a fogged train window at night, orange and blue lights blurring through the condensation, "
        "a hand wiping a clear patch in the glass",
        "A hand is already wiping the fogged glass, silhouettes shifting behind it, the camera creeps forward, "
        "city lights sliding past in soft blue and amber streaks",
        "Muffled carriage ambience, a faint announcement, rain on the glass",
    ),
    (
        "The woman stops in the middle of the rooftop and looks straight into the camera, calm face, "
        "first pale blue of dawn on the horizon behind the neon, rain easing",
        "She holds still and sustains the last note, eyes locked on the lens, the camera pushes in very slowly, "
        "dawn light rising behind her, last raindrops falling",
        "The last held note fading into soft pad and light rain",
    ),
)

# Palette (haut, bas) de l'image de départ de chaque plan : gamme « néon de nuit ».
PALETTES_PLANS: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((12, 16, 64), (200, 30, 150)),  # bleu nuit vers magenta
    ((0, 150, 190), (90, 30, 150)),  # cyan vers violet
    ((220, 130, 30), (20, 30, 90)),  # ambre vers bleu
    ((90, 30, 150), (0, 130, 170)),  # violet vers cyan
    ((20, 20, 70), (230, 90, 120)),  # indigo vers rose
    ((220, 40, 150), (10, 90, 170)),  # magenta vers bleu
    ((230, 150, 60), (60, 20, 130)),  # ambre vers violet
    ((15, 25, 90), (240, 120, 90)),  # bleu nuit vers aube corail
)

# Palette (haut, bas) de l'image de chaque fiche de la bibliothèque, par id d'image.
PALETTES_FICHES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "img-lina-pied": ((120, 20, 70), (15, 20, 70)),
    "img-lina-visage": ((200, 60, 110), (30, 25, 80)),
    "img-toit": ((15, 25, 85), (0, 150, 190)),
    "img-neon": ((210, 30, 150), (0, 160, 200)),
}

_ECRITURE_DEMO: dict[str, object] = {
    "brief": {
        "ambiance": "Nuit urbaine humide, néons magenta et cyan, mélancolie lumineuse",
        "genre": "Pop électronique, 118 BPM",
        "envies": "Plans chantés face caméra sur le toit, coupes de ville sous la pluie, fin sur l'aube",
    },
    "concepts": [
        {
            "titre": "Toit sous la pluie",
            "pitch": "Lina chante sur un toit-terrasse pendant que la ville s'allume sous l'averse. "
            "Les coupes descendent dans les rues et remontent vers elle à chaque refrain.",
        },
        {
            "titre": "Dernier métro",
            "pitch": "La chanson suit un trajet de nuit, du quai désert au wagon éclairé. "
            "Lina chante à travers les vitres embuées.",
        },
        {
            "titre": "Néons jusqu'à l'aube",
            "pitch": "Une nuit sans sommeil racontée en trois couleurs de néon. "
            "Elles s'éteignent une à une jusqu'au lever du jour.",
        },
    ],
    "concept_retenu": 0,
    "chat": [
        {"auteur": "utilisateur", "texte": "Plus de reflets dans les flaques sur les coupes"},
        {
            "auteur": "opus",
            "texte": "Bien noté : chaque plan de coupe s'ouvrira sur une flaque ou une vitre où les néons se reflètent. "
            "J'ai gardé les plans chantés sur le toit pour que ces reflets fassent le lien avec la ville.",
        },
    ],
}

_ECRITURE_VERTICAL: dict[str, object] = {
    "brief": {
        "ambiance": "Lumière dorée de fin de journée, gestes simples, ambiance intime",
        "genre": "Pop acoustique, 96 BPM",
        "envies": "Format vertical pour les réseaux, un seul décor, refrain en gros plan",
    },
}


def donnees_module_demo(projet_id: str) -> dict[str, object]:
    """Ce que le module Director lit dans `donnees_module` : l'écriture (brief, concepts, concept retenu, chat)."""
    if projet_id == PROJET_DEMO:
        return {"ecriture": _ECRITURE_DEMO}
    if projet_id == PROJET_VERTICAL:
        return {"ecriture": _ECRITURE_VERTICAL}
    return {}


# État du clip de chaque plan dans la timeline de démonstration (un exemple de chaque état).
_ETATS: tuple[EtatClip, ...] = (
    EtatClip.DLSS5,
    EtatClip.DLSS5,
    EtatClip.UPSCALE,
    EtatClip.BRUT,
    EtatClip.EN_RENDU,
    EtatClip.EN_FILE,
    EtatClip.ECHEC,
    EtatClip.PREVU,
)


def _sortie(prise_id: str, ordre: int, etape: EtapePostProd) -> SortiePostProd:
    reglages = {"style": "Cinematic", "intensite": 1.0} if etape is EtapePostProd.DLSS5 else {"facteur": 2}
    return SortiePostProd(
        id=f"{prise_id}-s{ordre}",
        etape=etape,
        ordre=ordre,
        statut=StatutTraitement.TERMINE,
        fichier=f"prises/{prise_id}/{ordre}-{etape.value}.mp4",
        reglages=reglages,
    )


def _prise(
    indice: int,
    numero: int,
    statut: StatutTraitement,
    etapes: tuple[EtapePostProd, ...] = (),
    erreur: str | None = None,
) -> Prise:
    prise_id = f"plan-{indice:02d}-p{numero}"
    sorties = [_sortie(prise_id, ordre, etape) for ordre, etape in enumerate(etapes, start=1)]
    return Prise(
        id=prise_id,
        plan_id=f"plan-{indice:02d}",
        numero=numero,
        moteur=_DECOUPAGE[indice][1],
        graine=1000 + indice * 10 + numero,
        statut=statut,
        fichier_brut=f"prises/{prise_id}/brut.mp4" if statut is StatutTraitement.TERMINE else None,
        erreur=erreur,
        sorties=sorties,
        sortie_active_id=sorties[-1].id if sorties else None,
    )


def prises_demo() -> list[Prise]:
    flashvsr, dlss5 = EtapePostProd.FLASHVSR, EtapePostProd.DLSS5
    fini = StatutTraitement.TERMINE
    return [
        _prise(0, 1, fini, (flashvsr, dlss5)),
        _prise(1, 1, fini, (flashvsr,)),
        _prise(1, 2, fini, (flashvsr, dlss5, dlss5)),  # deux passes DLSS5 : la dernière est active
        _prise(2, 1, fini, (flashvsr,)),
        _prise(3, 1, fini),
        _prise(4, 1, StatutTraitement.EN_COURS),
        _prise(5, 1, StatutTraitement.EN_FILE),
        _prise(6, 1, StatutTraitement.ECHEC, erreur="CUDA out of memory (2e tentative) — plan marqué en échec, la file a continué"),
    ]


VRAM_DEMO_GO = 12.0  # la démo décrit la carte de référence, quelle que soit la carte détectée


def plans_demo() -> list[Plan]:
    actives = {prise.plan_id: prise.id for prise in prises_demo()}  # la dernière prise de chaque plan gagne
    plans: list[Plan] = []
    curseur = 0.0
    for indice, (role, moteur, images, paroles, description) in enumerate(_DECOUPAGE):
        g = grille(moteur, FormatImage.PAYSAGE, vram_go=VRAM_DEMO_GO)
        if not g.est_valide(images):
            raise ValueError(f"plan {indice} : {images} images hors de la grille de {moteur.value}")
        plan_id = f"plan-{indice:02d}"
        plans.append(
            Plan(
                id=plan_id,
                indice=indice,
                role=role,
                debut_s=curseur,
                images=images,
                fps=g.fps,
                paroles=paroles,
                description=description,
                moteur_image=MoteurImage.CODEX if indice == 0 else MoteurImage.QWEN,
                moteur_video=moteur,
                fiches=["fiche-lina", "fiche-toit"] if role is RolePlan.CHANTE else ["fiche-neon"],
                prise_active_id=actives.get(plan_id),
                prompt_image=_PROMPTS[indice][0],
                prompt_video=_PROMPTS[indice][1],
                prompt_son=_PROMPTS[indice][2],
                image_depart=f"images/{plan_id}.png",
            )
        )
        curseur += g.duree_s(images)
    return plans


def projets_demo() -> dict[str, Projet]:
    return {
        PROJET_DEMO: Projet(
            id=PROJET_DEMO,
            titre="Nuit blanche (démo)",
            module="director_musique",
            format=FormatImage.PAYSAGE,
            cree_le=CREE_LE,
            recette_id=RECETTE_DEMO,
            chanson="chanson.wav",
            duree_chanson_s=DUREE_CHANSON_S,
            casting=["fiche-lina", "fiche-toit", "fiche-neon"],
            etat_phases={
                "analyse": "termine",
                "ecriture": "termine",
                "prompts": "termine",
                "images": "termine",
                "video": "en_cours",
                "export": "a_faire",
            },
            plans=plans_demo(),
            prises=prises_demo(),
        ),
        PROJET_VERTICAL: Projet(
            id=PROJET_VERTICAL,
            titre="Reel vertical (démo)",
            module="director_musique",
            format=FormatImage.PORTRAIT,
            cree_le=CREE_LE,
            recette_id=RECETTE_DEMO,
            etat_phases={"analyse": "a_faire"},
        ),
    }


def resumes_demo() -> list[ResumeProjet]:
    return [
        ResumeProjet(
            id=p.id, titre=p.titre, module=p.module, format=p.format, cree_le=p.cree_le, nb_plans=len(p.plans)
        )
        for p in projets_demo().values()
    ]


def timeline_demo() -> Timeline:
    clips: list[Clip] = [
        Clip(
            id="clip-chanson",
            piste="A0",
            fichier_audio="chanson.wav",
            position_s=0,
            sortie_s=DUREE_CHANSON_S,
            verrou_chanson=True,
        )
    ]
    for plan, etat in zip(plans_demo(), _ETATS, strict=True):
        clips.append(
            Clip(
                id=f"clip-{plan.id}",
                piste="V1",
                plan_id=plan.id,
                position_s=plan.debut_s,
                sortie_s=plan.duree_s,
                verrou_chanson=plan.role is RolePlan.CHANTE,
                etat=etat,
            )
        )
    clips.append(
        Clip(
            id="clip-bruitage-metro",
            piste="A1",
            fichier_audio="sons/metro-aerien.wav",
            position_s=30.5,  # pendant le plan 5, où le métro aérien traverse le cadre
            sortie_s=1.8,
            volume=0.8,
            fondu_sortie_s=0.3,
        )
    )
    return Timeline(
        projet_id=PROJET_DEMO,
        fps_maitre=FPS_MAITRE,
        duree_chanson_s=DUREE_CHANSON_S,
        pistes=["V1", "A0", "A1"],
        clips=clips,
    )


def recettes_demo() -> list[Recette]:
    return [
        Recette(
            id=RECETTE_DEMO,
            module="director_musique",
            nom="Clip de nuit — LTX-2.3 en 720p",
            valeurs={
                "format": FormatImage.PAYSAGE.value,
                "arrets": {"analyse": False, "ecriture": True, "prompts": True, "images": True},
                "llm": {
                    "ecriture": {"fournisseur": "claude", "modele": "claude-opus-5-5", "effort": "high"},
                    "prompts_image": {"fournisseur": "claude", "modele": "sonnet"},
                    "prompts_video": {"fournisseur": "bonsai", "modele": "bonsai2-27b-pq2"},
                    "prompts_son": {"fournisseur": "claude", "modele": "sonnet"},
                },
                "moteurs_precoches": {
                    "chante": MoteurVideo.LTX23.value,
                    "coupe": MoteurVideo.LTX23.value,
                    "image": MoteurImage.QWEN.value,
                },
                "rendu": {"h3": "544p", "ltx23": "720p", "ltx25": "720p"},  # 720p : rendu rapide (choix du projet, 30/09)
                "postprod": {
                    "flashvsr": {"actif": True, "facteur": 2},
                    "dlss5": {"actif": True, "style": "Cinematic", "intensite": 1.0, "facteur": 1.0},
                },
                "export": {"interpolation_60fps": False},
            },
        )
    ]


def fiches_demo() -> list[FicheBibliotheque]:
    return [
        FicheBibliotheque(
            id="fiche-lina",
            type=TypeFiche.PERSONNAGE,
            nom="Lina",
            description="Chanteuse, 28 ans, cheveux courts noirs, veste en cuir bordeaux.",
            images=[
                ImageFiche(id="img-lina-pied", role=RoleImageFiche.PORTRAIT_PIED, chemin="bibliotheque/fiche-lina/portrait-pied.png"),
                ImageFiche(id="img-lina-visage", role=RoleImageFiche.GROS_PLAN, chemin="bibliotheque/fiche-lina/gros-plan.png"),
            ],
        ),
        FicheBibliotheque(
            id="fiche-toit",
            type=TypeFiche.DECOR,
            nom="Toit-terrasse de nuit",
            description="Toit d'immeuble, antennes, ville illuminée en contrebas.",
            images=[ImageFiche(id="img-toit", role=RoleImageFiche.REFERENCE, chemin="bibliotheque/fiche-toit/reference.png")],
        ),
        FicheBibliotheque(
            id="fiche-neon",
            type=TypeFiche.STYLE,
            nom="Néon pluvieux",
            description="Reflets humides, magenta et cyan, grain léger.",
            images=[ImageFiche(id="img-neon", role=RoleImageFiche.REFERENCE, chemin="bibliotheque/fiche-neon/reference.png")],
        ),
    ]
