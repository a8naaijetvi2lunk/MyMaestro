"""Empreintes VRAM des moteurs : mesurées par la tâche 0 si disponibles, sinon valeurs prudentes.

Les valeurs par défaut viennent du cahier des charges (§5 et §6.3). `charger` les remplace par
les mesures de core/empreintes_mesurees.json quand elles existent : VRAM mesurée moins la VRAM
occupée par le bureau au même moment. Seules les mesures réussies comptent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..connectors.base import Empreinte

VRAM_TOTALE_MO = 12282
VRAM_BUREAU_MO = 2000  # prudent : 1 100 à 2 200 Mo mesurés selon les applications ouvertes
FICHIER_MESURES = Path(__file__).with_name("empreintes_mesurees.json")  # mesures publiées (extrait de docs/mesures/tache0.json)

DEFAUTS: dict[str, Empreinte] = {
    "maestro": Empreinte(vram_mo=11000, residuelle_mo=1500),
    "dlss5": Empreinte(vram_mo=6000, residuelle_mo=0),
    "bonsai": Empreinte(vram_mo=9500, residuelle_mo=9500),  # llama-server garde tout tant qu'il tourne
    "claude": Empreinte(vram_mo=0, residuelle_mo=0),
    "codex": Empreinte(vram_mo=0, residuelle_mo=0),  # cloud (gpt-image-2) ; passe par le processus Maestro en réel (plan 6)
}

JOBS_MAESTRO = (
    "qwen_image", "h3_segment_124", "h3_offset_124", "h3_segment_243_paysage",
    "h3_segment_243_portrait", "ltx23_121", "ltx25_121", "flashvsr",
)


def _section(parent: Any, cle: str) -> dict[str, Any]:
    """Sous-dictionnaire ou {} : une sonde en échec peut avoir écrit une chaîne à la place."""
    valeur = parent.get(cle) if isinstance(parent, dict) else None
    return valeur if isinstance(valeur, dict) else {}


def _net(valeur: Any, bureau: Any) -> int | None:
    if not isinstance(valeur, (int, float)) or not isinstance(bureau, (int, float)):
        return None
    return max(0, int(valeur - bureau))


def _pic(mesures: list[Any]) -> float | None:
    valides = [m for m in mesures if isinstance(m, (int, float))]
    return max(valides) if valides else None


def charger(chemin: Path | None = None) -> dict[str, Empreinte]:
    empreintes = dict(DEFAUTS)
    try:
        mesures: dict[str, Any] = json.loads((chemin or FICHIER_MESURES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empreintes

    bonsai = _section(mesures, "bonsai")
    demarrage = _section(bonsai, "demarrage")
    net_bonsai = _net(demarrage.get("vram_chargee_mo"), bonsai.get("vram_avant_mo")) if demarrage.get("pret") is True else None
    if net_bonsai:
        empreintes["bonsai"] = Empreinte(vram_mo=net_bonsai, residuelle_mo=net_bonsai)

    maestro = _section(mesures, "maestro")
    jobs = [_section(maestro, cle) for cle in JOBS_MAESTRO]
    net_maestro = _net(_pic([j.get("vram_pic_mo") for j in jobs if j.get("statut") == "completed"]), maestro.get("vram_avant_mo"))
    if net_maestro:
        liberation = _section(maestro, "release_model")
        residuelle = None
        if liberation.get("resultat") is True:
            residuelle = _net(liberation.get("vram_apres_mo"), maestro.get("vram_avant_mo"))
        empreintes["maestro"] = Empreinte(
            vram_mo=net_maestro, residuelle_mo=residuelle if residuelle is not None else DEFAUTS["maestro"].residuelle_mo
        )

    dlss5 = _section(mesures, "dlss5")
    operations = [_section(dlss5, cle) for cle in ("neural_rendering", "interpolation")]
    net_dlss5 = _net(_pic([o.get("vram_pic_mo") for o in operations if o.get("code_retour") == 0]), dlss5.get("vram_avant_mo"))
    if net_dlss5:
        empreintes["dlss5"] = Empreinte(vram_mo=net_dlss5, residuelle_mo=0)
    return empreintes
