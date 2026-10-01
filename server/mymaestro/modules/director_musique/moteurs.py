"""Compatibilité des moteurs vidéo avec la durée d'un plan (étape 3, D15 ; spec §6.1).

Un moteur est compatible si la durée du plan tient dans sa grille à `TOLERANCE_RECALAGE_S` près.
Le choisir recale le nombre d'images sur sa grille ; les plans suivants ne bougent pas (la
timeline absorbe l'écart). Un avertissement ne bloque pas : LTX-2.5 reste possible sur un plan
chanté, mais son lip-sync a été écarté par l'A/B du 16/08.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...contrat.modeles import CompatibiliteMoteur, FormatImage, MoteurVideo, Plan, RolePlan
from ...core.grilles import Definition, grille

TOLERANCE_RECALAGE_S = 0.25
ECART_SIGNALE_S = 0.05
AVERTISSEMENT_LTX25_CHANTE = "LTX-2.5 : lip-sync écarté (A/B du 16/08)"


def _s(secondes: float) -> str:
    return f"{secondes:.1f}".replace(".", ",")


def compatibilite(
    plan: Plan, moteur: MoteurVideo, fmt: FormatImage, definition: Definition | None = None
) -> CompatibiliteMoteur:
    avertissement = AVERTISSEMENT_LTX25_CHANTE if plan.role is RolePlan.CHANTE and moteur is MoteurVideo.LTX25 else None
    try:  # recette enregistrée sur une autre carte : la définition peut ne plus être permise, ce n'est pas une erreur de lecture
        g = grille(moteur, fmt, definition)
    except ValueError as exc:
        return CompatibiliteMoteur(moteur=moteur, compatible=False, note=str(exc), avertissement=avertissement)
    duree = plan.duree_s
    if duree < g.duree_min_s - TOLERANCE_RECALAGE_S:
        return CompatibiliteMoteur(
            moteur=moteur, compatible=False, note=f"{_s(duree)} s < {_s(g.duree_min_s)} s minimum", avertissement=avertissement
        )
    if duree > g.duree_max_s + TOLERANCE_RECALAGE_S:
        return CompatibiliteMoteur(
            moteur=moteur, compatible=False, note=f"{_s(duree)} s > {_s(g.duree_max_s)} s maximum", avertissement=avertissement
        )
    images = g.plus_proche(duree)
    duree_recalee = images / g.fps
    if abs(duree_recalee - duree) > TOLERANCE_RECALAGE_S:
        return CompatibiliteMoteur(
            moteur=moteur, compatible=False,
            note=f"recalage de {_s(abs(duree_recalee - duree))} s > 0,25 s : redécoupe le plan", avertissement=avertissement,
        )
    note = f"recalé à {_s(duree_recalee)} s" if abs(duree_recalee - duree) >= ECART_SIGNALE_S else None
    return CompatibiliteMoteur(
        moteur=moteur, compatible=True, images=images, duree_s=duree_recalee, note=note, avertissement=avertissement
    )


def compatibilites(
    plan: Plan, fmt: FormatImage, definitions: Mapping[MoteurVideo, Definition] | None = None
) -> list[CompatibiliteMoteur]:
    return [compatibilite(plan, moteur, fmt, (definitions or {}).get(moteur)) for moteur in MoteurVideo]
