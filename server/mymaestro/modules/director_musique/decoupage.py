"""Pose un découpage proposé en secondes sur les grilles des moteurs pré-cochés.

Pavage continu depuis 0 : le début d'un plan est la fin du précédent. Chaque plan vise la FIN
proposée (et non sa durée) : l'écart dû au recalage sur la grille se reporte ainsi sur le plan
suivant, comme `normalize_h3_clip_frame_schedule` dans Maestro, et la dérive globale reste
de l'ordre d'un pas de grille. Le dernier plan vise la fin de la chanson ; si le reste ne contient pas
le plan minimal du moteur, le plan précédent est raccourci pour lui laisser ce minimum (rôle et paroles
conservés), ou, pour une bribe de moins d'un demi-minimum, l'absorbe en reprenant ses paroles.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from ...contrat.modeles import FormatImage, MoteurVideo, Plan, RolePlan
from ...core.grilles import Definition, grille
from .modeles import PlanPropose
from .moteurs import TOLERANCE_RECALAGE_S
from .reglages import MoteursPrecoches


def normaliser(
    propositions: list[PlanPropose],
    duree_chanson_s: float,
    fmt: FormatImage,
    moteurs: MoteursPrecoches,
    prefixe_id: str,
    casting: list[str] | None = None,
    definitions: Mapping[MoteurVideo, Definition] | None = None,
) -> list[Plan]:
    tries = sorted(propositions, key=lambda p: (p.debut_s, p.fin_s))
    # Les propositions entièrement hors de la chanson sont écartées (la première est gardée si tout déborde).
    dedans = [p for p in tries if p.debut_s < duree_chanson_s - TOLERANCE_RECALAGE_S]
    tries = dedans or tries[:1]
    plans: list[Plan] = []
    curseur = 0.0
    for rang, proposition in enumerate(tries):
        if duree_chanson_s - curseur <= TOLERANCE_RECALAGE_S:
            break
        moteur = moteurs.chante if proposition.role is RolePlan.CHANTE else moteurs.coupe
        g = grille(moteur, fmt, (definitions or {}).get(moteur))
        reste = duree_chanson_s - curseur
        if plans and reste < g.duree_min_s - TOLERANCE_RECALAGE_S:
            # Le reste ne contient pas le plan minimal du moteur. D'abord, raccourcir le précédent pour laisser
            # ce minimum au plan courant (ses paroles et son rôle sont conservés). Si c'est impossible, ou si la
            # proposition fait moins de la moitié du minimum (bruit de découpage), le précédent l'absorbe :
            # il est allongé jusqu'à la fin de la chanson et reprend ses paroles et ses fiches.
            prec = plans[-1]
            g_prec = grille(prec.moteur_video, fmt, (definitions or {}).get(prec.moteur_video))
            restant = duree_chanson_s - prec.debut_s
            raccourci = restant - g.duree_min_s
            duree_proposee = min(proposition.fin_s, duree_chanson_s) - proposition.debut_s
            peut_raccourcir = raccourci >= g_prec.duree_min_s - TOLERANCE_RECALAGE_S and duree_proposee >= g.duree_min_s / 2
            if not peut_raccourcir and restant <= g_prec.duree_max_s + TOLERANCE_RECALAGE_S:
                fiches = [f for f in proposition.fiches if casting is None or f in casting]
                plans[-1] = prec.model_copy(
                    update={
                        "images": g_prec.plus_proche(restant),
                        "paroles": " ".join(t for t in (prec.paroles, proposition.paroles) if t),
                        "fiches": list(dict.fromkeys([*prec.fiches, *fiches])),
                    }
                )
                break
            plans[-1] = prec.model_copy(update={"images": g_prec.plus_proche(raccourci)})
            curseur = plans[-1].debut_s + plans[-1].duree_s
        fin_visee = duree_chanson_s if rang == len(tries) - 1 else min(proposition.fin_s, duree_chanson_s)
        # Une cible plus longue que le maximum de la grille (tolérance comprise) est découpée en tranches égales.
        longueur = max(fin_visee - curseur, 0.0)
        morceaux = 1 if longueur <= g.duree_max_s + TOLERANCE_RECALAGE_S else math.ceil(longueur / g.duree_max_s - 1e-9)
        for k in range(morceaux):
            cible = curseur + (fin_visee - curseur) / (morceaux - k)
            images = g.plus_proche(max(cible - curseur, 0.0))
            indice = len(plans)
            plans.append(
                Plan(
                    id=f"{prefixe_id}-{indice:02d}", indice=indice, role=proposition.role, debut_s=round(curseur, 6),
                    images=images, fps=g.fps, paroles=proposition.paroles, description=proposition.description,
                    moteur_image=moteurs.image, moteur_video=moteur,
                    fiches=list(dict.fromkeys(f for f in proposition.fiches if casting is None or f in casting)),
                )
            )
            curseur += images / g.fps
    return plans
