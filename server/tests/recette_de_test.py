"""Configuration des tests du Director qui vérifient H3 et le 544p : H3 sur les plans chantés, LTX-2.3 en coupe, rendu
par défaut (544p partout).

Depuis le 30/09, la recette de démo met tout en LTX-2.3 720p (choix du projet, pour des rendus rapides). Ces tests fixent
donc explicitement leur configuration au lieu de dépendre de celle de la démo."""

from mymaestro.contrat.modeles import MoteurVideo
from mymaestro.core import depot
from mymaestro.core.db import Base
from mymaestro.fixtures import demo


def h3_chante_en_544p(base: Base) -> None:
    with base.transaction() as cx:
        recette = depot.lire_recette(cx, demo.RECETTE_DEMO)
        moteurs = {**recette.valeurs["moteurs_precoches"], "chante": MoteurVideo.H3.value, "coupe": MoteurVideo.LTX23.value}
        valeurs = {**recette.valeurs, "moteurs_precoches": moteurs, "rendu": {}}
        depot.enregistrer_recette(cx, recette.model_copy(update={"valeurs": valeurs}))
