"""État d'un clip vidéo, déduit de la prise active de son plan (jamais stocké)."""

from __future__ import annotations

from ..contrat.modeles import EtapePostProd, EtatClip, Plan, Prise, Projet, StatutTraitement


def etat_clip(plan: Plan, prises: list[Prise]) -> EtatClip:
    active = next((p for p in prises if p.id == plan.prise_active_id), None)
    if active is None:
        return EtatClip.PREVU
    if active.statut is StatutTraitement.EN_FILE:
        return EtatClip.EN_FILE
    if active.statut is StatutTraitement.EN_COURS:
        return EtatClip.EN_RENDU
    if active.statut is StatutTraitement.ECHEC:
        return EtatClip.ECHEC
    sortie = next((s for s in active.sorties if s.id == active.sortie_active_id), None)
    if sortie is None:
        return EtatClip.BRUT
    return EtatClip.DLSS5 if sortie.etape is EtapePostProd.DLSS5 else EtatClip.UPSCALE


def etats_des_plans(projet: Projet) -> dict[str, EtatClip]:
    par_plan: dict[str, list[Prise]] = {}
    for prise in projet.prises:
        par_plan.setdefault(prise.plan_id, []).append(prise)
    return {plan.id: etat_clip(plan, par_plan.get(plan.id, [])) for plan in projet.plans}
