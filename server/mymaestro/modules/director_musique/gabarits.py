"""Gabarits des consignes envoyées aux modèles de langage (Opus pour l'écriture, Claude ou Bonsai pour les prompts).

Règle : une consigne par plan, jamais un ratio global. Chaque consigne se
termine par le schéma JSON attendu ; la sortie est validée par ce schéma avant d'être appliquée.
"""

from __future__ import annotations

import json
from typing import Any

from ...contrat.modeles import Projet


def _schema(modele: Any) -> str:
    return json.dumps(modele.model_json_schema(), ensure_ascii=False)


def concepts(brief: dict[str, Any], analyse: dict[str, Any] | None, nombre: int, schema: Any) -> str:
    lignes = [l["texte"] for l in (analyse or {}).get("lignes", [])]
    return (
        f"Tu écris un clip musical. Propose {nombre} concepts CONTRASTÉS (pitch, arc narratif, traitement visuel).\n"
        f"Brief : {json.dumps(brief, ensure_ascii=False)}\n"
        f"Paroles : {' / '.join(lignes) or '(aucune)'}\n"
        f"Réponds uniquement en JSON conforme à ce schéma : {_schema(schema)}"
    )


def chat(historique: list[dict[str, str]], concept: dict[str, Any] | None, message: str, schema: Any) -> str:
    return (
        "Tu affines le concept d'un clip musical avec son auteur.\n"
        f"Concept retenu : {json.dumps(concept, ensure_ascii=False)}\n"
        f"Échanges précédents : {json.dumps(historique, ensure_ascii=False)}\n"
        f"Nouveau message : {message}\n"
        f"Réponds uniquement en JSON conforme à ce schéma : {_schema(schema)}"
    )


def decoupage(projet: Projet, analyse: dict[str, Any], concept: dict[str, Any] | None, chat: list[dict[str, str]],
              bornes: dict[str, str], casting: list[dict[str, str]], schema: Any) -> str:
    return (
        "Découpe la chanson en plans, du début à la fin, sans trou ni chevauchement.\n"
        "Pour CHAQUE plan : rôle (chante si le chanteur est à l'image et chante, coupe sinon), début et fin en secondes, "
        "paroles couvertes, description visuelle, identifiants des fiches du casting à l'image.\n"
        f"Durées permises par rôle : {json.dumps(bornes, ensure_ascii=False)}. Respecte-les plan par plan.\n"
        f"Durée de la chanson : {projet.duree_chanson_s} s.\n"
        f"Casting (fiches de la bibliothèque) : {json.dumps(casting, ensure_ascii=False)}\n"
        f"Analyse : {json.dumps(analyse, ensure_ascii=False)}\n"
        f"Concept : {json.dumps(concept, ensure_ascii=False)}\nÉchanges : {json.dumps(chat, ensure_ascii=False)}\n"
        f"Réponds uniquement en JSON conforme à ce schéma : {_schema(schema)}"
    )


CONSIGNES_ETAPE = {
    "image": "un prompt d'image de départ en anglais, composé à partir des références du casting, sans texte à l'image",
    "video": "un prompt vidéo en anglais qui ouvre sur l'action déjà engagée (« Already … as the shot opens »)",
    "son": "un prompt de bruitage en anglais de 55 mots au plus (MMAudio, guidé par la vidéo du plan)",
}


def prompts(etape: str, plans: list[dict[str, Any]], concept: dict[str, Any] | None, casting: list[dict[str, str]],
            schema: Any) -> str:
    return (
        f"Pour CHAQUE plan ci-dessous, écris {CONSIGNES_ETAPE[etape]}.\n"
        f"Concept : {json.dumps(concept, ensure_ascii=False)}\n"
        f"Casting (les « fiches » de chaque plan renvoient à ces identifiants) : {json.dumps(casting, ensure_ascii=False)}\n"
        f"Plans : {json.dumps(plans, ensure_ascii=False)}\n"
        f"Réponds uniquement en JSON conforme à ce schéma : {_schema(schema)}"
    )
