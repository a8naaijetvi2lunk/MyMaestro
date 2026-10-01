"""Dépôt SQLite : conversion entre le contrat (pydantic) et les tables du schéma.

Toutes les fonctions reçoivent une connexion obtenue par `Base.transaction()` : c'est
l'appelant qui porte le verrou et la transaction.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ..contrat.modeles import (
    ActionEntree,
    ActionProgrammee,
    Clip,
    EtapePostProd,
    EtatPhase,
    FicheBibliotheque,
    ImageFiche,
    MoteurVideo,
    Plan,
    Prise,
    Projet,
    ProjetEntree,
    Recette,
    ResumeProjet,
    SortiePostProd,
    StatutAction,
    StatutTraitement,
    Timeline,
)
from .etats import etats_des_plans


def horodatage() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def nouvel_id(prefixe: str) -> str:
    return f"{prefixe}-{uuid.uuid4().hex[:12]}"


def _json(valeur: Any) -> str:
    return json.dumps(valeur, ensure_ascii=False)


# --- Projets, plans, prises, sorties ---------------------------------------------------------


def inserer_projet(cx: sqlite3.Connection, projet: Projet, donnees_module: dict[str, Any] | None = None) -> None:
    """Insère un projet complet (casting, plans, fiches des plans, prises, sorties). Fiches et recette doivent exister."""
    maintenant = horodatage()
    cx.execute(
        "INSERT INTO projets (id, module, titre, format, recette_id, chanson, paroles, duree_chanson_s, etat_phases, "
        "donnees_module, cree_le, modifie_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            projet.id, projet.module, projet.titre, projet.format.value, projet.recette_id, projet.chanson, projet.paroles,
            projet.duree_chanson_s, _json({k: EtatPhase(v).value for k, v in projet.etat_phases.items()}),
            _json(donnees_module or {}), projet.cree_le, maintenant,
        ),
    )
    for fiche_id in projet.casting:
        cx.execute("INSERT INTO casting (projet_id, fiche_id) VALUES (?, ?)", (projet.id, fiche_id))
    _inserer_plans(cx, projet.id, projet.plans)
    for prise in projet.prises:
        cx.execute(
            "INSERT INTO prises (id, plan_id, numero, moteur, graine, statut, fichier_brut, erreur, sortie_active_id, cree_le) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                prise.id, prise.plan_id, prise.numero, prise.moteur.value, prise.graine, prise.statut.value,
                prise.fichier_brut, prise.erreur, prise.sortie_active_id, maintenant,
            ),
        )
        for sortie in prise.sorties:
            cx.execute(
                "INSERT INTO sorties (id, prise_id, etape, ordre, reglages, fichier, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sortie.id, prise.id, sortie.etape.value, sortie.ordre, _json(sortie.reglages), sortie.fichier, sortie.statut.value, maintenant),
            )


def _inserer_plans(cx: sqlite3.Connection, projet_id: str, plans: list[Plan]) -> None:
    for plan in plans:
        cx.execute(
            "INSERT INTO plans (id, projet_id, indice, role, debut_s, images, fps, paroles, description, moteur_image, "
            "moteur_video, prise_active_id, prompt_image, prompt_video, prompt_son, image_depart) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan.id, projet_id, plan.indice, plan.role.value, plan.debut_s, plan.images, plan.fps, plan.paroles,
                plan.description, plan.moteur_image.value if plan.moteur_image else None,
                plan.moteur_video.value if plan.moteur_video else None, plan.prise_active_id,
                plan.prompt_image, plan.prompt_video, plan.prompt_son, plan.image_depart,
            ),
        )
        for fiche_id in plan.fiches:
            cx.execute("INSERT INTO plans_fiches (plan_id, fiche_id) VALUES (?, ?)", (plan.id, fiche_id))


def lister_projets(cx: sqlite3.Connection) -> list[ResumeProjet]:
    lignes = cx.execute(
        "SELECT p.id, p.titre, p.module, p.format, p.cree_le, p.recette_id, COUNT(pl.id) AS nb FROM projets p "
        "LEFT JOIN plans pl ON pl.projet_id = p.id GROUP BY p.id ORDER BY p.cree_le, p.id"
    ).fetchall()
    return [
        ResumeProjet(
            id=l["id"], titre=l["titre"], module=l["module"], format=l["format"], cree_le=l["cree_le"],
            nb_plans=l["nb"], recette_id=l["recette_id"],
        )
        for l in lignes
    ]


def lire_projet(cx: sqlite3.Connection, projet_id: str) -> Projet | None:
    ligne = cx.execute("SELECT * FROM projets WHERE id = ?", (projet_id,)).fetchone()
    if ligne is None:
        return None
    fiches_par_plan: dict[str, list[str]] = {}
    for l in cx.execute(
        "SELECT pf.plan_id, pf.fiche_id FROM plans_fiches pf JOIN plans p ON p.id = pf.plan_id "
        "WHERE p.projet_id = ? ORDER BY pf.rowid",
        (projet_id,),
    ):
        fiches_par_plan.setdefault(l["plan_id"], []).append(l["fiche_id"])
    plans = [
        Plan(
            id=l["id"], indice=l["indice"], role=l["role"], debut_s=l["debut_s"], images=l["images"], fps=l["fps"],
            paroles=l["paroles"], description=l["description"], moteur_image=l["moteur_image"],
            moteur_video=l["moteur_video"], fiches=fiches_par_plan.get(l["id"], []), prise_active_id=l["prise_active_id"],
            prompt_image=l["prompt_image"], prompt_video=l["prompt_video"], prompt_son=l["prompt_son"],
            image_depart=l["image_depart"],
        )
        for l in cx.execute("SELECT * FROM plans WHERE projet_id = ? ORDER BY indice", (projet_id,))
    ]
    sorties_par_prise: dict[str, list[SortiePostProd]] = {}
    for l in cx.execute(
        "SELECT s.* FROM sorties s JOIN prises pr ON pr.id = s.prise_id JOIN plans p ON p.id = pr.plan_id "
        "WHERE p.projet_id = ? ORDER BY s.prise_id, s.ordre",
        (projet_id,),
    ):
        sorties_par_prise.setdefault(l["prise_id"], []).append(
            SortiePostProd(
                id=l["id"], etape=l["etape"], ordre=l["ordre"], statut=l["statut"], fichier=l["fichier"],
                reglages=json.loads(l["reglages"]), erreur=l["erreur"],
            )
        )
    prises = [
        Prise(
            id=l["id"], plan_id=l["plan_id"], numero=l["numero"], moteur=l["moteur"], graine=l["graine"],
            statut=l["statut"], fichier_brut=l["fichier_brut"], erreur=l["erreur"],
            sorties=sorties_par_prise.get(l["id"], []), sortie_active_id=l["sortie_active_id"],
        )
        for l in cx.execute(
            "SELECT pr.* FROM prises pr JOIN plans p ON p.id = pr.plan_id WHERE p.projet_id = ? ORDER BY p.indice, pr.numero",
            (projet_id,),
        )
    ]
    casting = [l["fiche_id"] for l in cx.execute("SELECT fiche_id FROM casting WHERE projet_id = ? ORDER BY rowid", (projet_id,))]
    return Projet(
        id=ligne["id"], titre=ligne["titre"], module=ligne["module"], format=ligne["format"], cree_le=ligne["cree_le"],
        recette_id=ligne["recette_id"], etat_phases=json.loads(ligne["etat_phases"]), plans=plans, prises=prises,
        chanson=ligne["chanson"], paroles=ligne["paroles"] or "", duree_chanson_s=ligne["duree_chanson_s"], casting=casting,
    )


# --- Timeline ------------------------------------------------------------------------------------


def inserer_timeline(cx: sqlite3.Connection, timeline: Timeline) -> None:
    modifier_donnees_module(
        cx,
        timeline.projet_id,
        "timeline",
        {"fps_maitre": timeline.fps_maitre, "duree_chanson_s": timeline.duree_chanson_s, "pistes": timeline.pistes},
    )
    for clip in timeline.clips:
        inserer_clip(cx, timeline.projet_id, clip)


def lire_timeline(cx: sqlite3.Connection, projet_id: str) -> Timeline | None:
    ligne = cx.execute("SELECT donnees_module FROM projets WHERE id = ?", (projet_id,)).fetchone()
    if ligne is None:
        return None
    meta = json.loads(ligne["donnees_module"]).get("timeline")
    if meta is None:
        return None
    projet = lire_projet(cx, projet_id)
    etats = etats_des_plans(projet) if projet is not None else {}
    clips = [
        Clip(
            id=l["id"], piste=l["piste"], plan_id=l["plan_id"], fichier_audio=l["fichier_audio"], position_s=l["position_s"],
            entree_s=l["entree_s"], sortie_s=l["sortie_s"], verrou_chanson=bool(l["verrou_chanson"]),
            etat=etats.get(l["plan_id"]) if l["plan_id"] else None, volume=l["volume"],
            fondu_entree_s=l["fondu_entree_s"], fondu_sortie_s=l["fondu_sortie_s"],
        )
        for l in cx.execute("SELECT * FROM clips WHERE projet_id = ? ORDER BY piste, position_s", (projet_id,))
    ]
    return Timeline(
        projet_id=projet_id, fps_maitre=meta["fps_maitre"], duree_chanson_s=meta["duree_chanson_s"], pistes=meta["pistes"], clips=clips
    )


CHAMPS_CLIP_MODIFIABLES = frozenset(
    {"piste", "position_s", "entree_s", "sortie_s", "verrou_chanson", "volume", "fondu_entree_s", "fondu_sortie_s"}
)


def inserer_clip(cx: sqlite3.Connection, projet_id: str, clip: Clip) -> None:
    cx.execute(
        "INSERT INTO clips (id, projet_id, piste, plan_id, fichier_audio, position_s, entree_s, sortie_s, verrou_chanson, "
        "volume, fondu_entree_s, fondu_sortie_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            clip.id, projet_id, clip.piste, clip.plan_id, clip.fichier_audio, clip.position_s, clip.entree_s,
            clip.sortie_s, int(clip.verrou_chanson), clip.volume, clip.fondu_entree_s, clip.fondu_sortie_s,
        ),
    )


def maj_clip(cx: sqlite3.Connection, clip_id: str, **champs: Any) -> None:
    _maj(cx, "clips", CHAMPS_CLIP_MODIFIABLES, clip_id, champs)


def supprimer_clip(cx: sqlite3.Connection, clip_id: str) -> bool:
    return cx.execute("DELETE FROM clips WHERE id = ?", (clip_id,)).rowcount == 1


def definir_pistes(cx: sqlite3.Connection, projet_id: str, pistes: list[str]) -> None:
    """Remplace la liste des pistes de la timeline (KeyError si le projet n'a pas de timeline)."""
    meta = dict(lire_donnees_module(cx, projet_id).get("timeline") or {})
    if not meta:
        raise KeyError(projet_id)
    meta["pistes"] = pistes
    modifier_donnees_module(cx, projet_id, "timeline", meta)


# --- Prises et sorties de post-production (phase 5, actions à la carte) ------------------------------

CHAMPS_PRISE_MODIFIABLES = frozenset({"statut", "fichier_brut", "erreur", "sortie_active_id"})
CHAMPS_SORTIE_MODIFIABLES = frozenset({"statut", "fichier", "erreur"})
TABLES_IDENTIFIEES = frozenset({"prises", "sorties", "plans", "clips"})


def _valeur_sql(valeur: Any) -> Any:
    if isinstance(valeur, bool):
        return int(valeur)
    return valeur.value if hasattr(valeur, "value") else valeur


def _maj(cx: sqlite3.Connection, table: str, autorises: frozenset[str], identifiant: str, champs: dict[str, Any]) -> None:
    """Mise à jour en une instruction ; seules les colonnes autorisées passent (noms jamais venus de l'extérieur)."""
    inconnus = set(champs) - autorises
    if inconnus:
        raise ValueError(f"champs non modifiables ({table}) : {sorted(inconnus)}")
    if not champs:
        return
    # Une seule instruction : les CHECK (ex. sortie_s > entree_s) ne voient que l'état final.
    affectations = ", ".join(f"{colonne} = ?" for colonne in champs)
    cx.execute(f"UPDATE {table} SET {affectations} WHERE id = ?", (*[_valeur_sql(v) for v in champs.values()], identifiant))


def existe(cx: sqlite3.Connection, table: str, identifiant: str) -> bool:
    if table not in TABLES_IDENTIFIEES:
        raise ValueError(f"table inattendue : {table}")
    return cx.execute(f"SELECT 1 FROM {table} WHERE id = ?", (identifiant,)).fetchone() is not None


def creer_prise(
    cx: sqlite3.Connection, plan_id: str, moteur: MoteurVideo, graine: int | None, reglages: dict[str, Any]
) -> Prise:
    """Nouvelle prise du plan (numéro suivant), en file."""
    numero = cx.execute("SELECT COALESCE(MAX(numero), 0) + 1 FROM prises WHERE plan_id = ?", (plan_id,)).fetchone()[0]
    prise = Prise(
        id=nouvel_id("prise"), plan_id=plan_id, numero=numero, moteur=moteur, graine=graine, statut=StatutTraitement.EN_FILE
    )
    cx.execute(
        "INSERT INTO prises (id, plan_id, numero, moteur, graine, reglages, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (prise.id, plan_id, numero, prise.moteur.value, graine, _json(reglages), prise.statut.value, horodatage()),
    )
    return prise


def maj_prise(cx: sqlite3.Connection, prise_id: str, **champs: Any) -> None:
    _maj(cx, "prises", CHAMPS_PRISE_MODIFIABLES, prise_id, champs)


def supprimer_prise(cx: sqlite3.Connection, prise_id: str) -> bool:
    """Supprime une prise et ses sorties (cascade) ; l'appelant s'assure qu'elle n'est active nulle part."""
    return cx.execute("DELETE FROM prises WHERE id = ?", (prise_id,)).rowcount == 1


def creer_sortie(
    cx: sqlite3.Connection, prise_id: str, etape: EtapePostProd, reglages: dict[str, Any]
) -> SortiePostProd:
    """Nouvelle sortie de post-production de la prise (ordre suivant), en file."""
    ordre = cx.execute("SELECT COALESCE(MAX(ordre), 0) + 1 FROM sorties WHERE prise_id = ?", (prise_id,)).fetchone()[0]
    sortie = SortiePostProd(id=nouvel_id("sortie"), etape=etape, ordre=ordre, statut=StatutTraitement.EN_FILE, reglages=reglages)
    cx.execute(
        "INSERT INTO sorties (id, prise_id, etape, ordre, reglages, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sortie.id, prise_id, sortie.etape.value, ordre, _json(reglages), sortie.statut.value, horodatage()),
    )
    return sortie


def maj_sortie(cx: sqlite3.Connection, sortie_id: str, **champs: Any) -> None:
    _maj(cx, "sorties", CHAMPS_SORTIE_MODIFIABLES, sortie_id, champs)


# --- Recettes --------------------------------------------------------------------------------------


def _recette(l: sqlite3.Row) -> Recette:
    return Recette(id=l["id"], module=l["module"], nom=l["nom"], valeurs=json.loads(l["valeurs"]))


def enregistrer_recette(cx: sqlite3.Connection, recette: Recette) -> Recette:
    maintenant = horodatage()
    cx.execute(
        "INSERT INTO recettes (id, module, nom, valeurs, cree_le, modifie_le) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET module = excluded.module, nom = excluded.nom, valeurs = excluded.valeurs, "
        "modifie_le = excluded.modifie_le",
        (recette.id, recette.module, recette.nom, _json(recette.valeurs), maintenant, maintenant),
    )
    return recette


def lister_recettes(cx: sqlite3.Connection, module: str | None = None) -> list[Recette]:
    if module is None:
        lignes = cx.execute("SELECT * FROM recettes ORDER BY rowid").fetchall()
    else:
        lignes = cx.execute("SELECT * FROM recettes WHERE module = ? ORDER BY rowid", (module,)).fetchall()
    return [_recette(l) for l in lignes]


def lire_recette(cx: sqlite3.Connection, recette_id: str) -> Recette | None:
    ligne = cx.execute("SELECT * FROM recettes WHERE id = ?", (recette_id,)).fetchone()
    return _recette(ligne) if ligne else None


# --- Bibliothèque ----------------------------------------------------------------------------------


def enregistrer_fiche(cx: sqlite3.Connection, fiche: FicheBibliotheque) -> FicheBibliotheque:
    cx.execute(
        "INSERT INTO fiches (id, type, nom, description, cree_le) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET type = excluded.type, nom = excluded.nom, description = excluded.description",
        (fiche.id, fiche.type.value, fiche.nom, fiche.description, horodatage()),
    )
    cx.execute("DELETE FROM images_fiche WHERE fiche_id = ?", (fiche.id,))
    for image in fiche.images:
        cx.execute(
            "INSERT INTO images_fiche (id, fiche_id, role, chemin) VALUES (?, ?, ?, ?)",
            (image.id, fiche.id, image.role.value, image.chemin),
        )
    return fiche


def lister_fiches(cx: sqlite3.Connection) -> list[FicheBibliotheque]:
    images: dict[str, list[ImageFiche]] = {}
    for l in cx.execute("SELECT * FROM images_fiche ORDER BY rowid"):
        images.setdefault(l["fiche_id"], []).append(ImageFiche(id=l["id"], role=l["role"], chemin=l["chemin"]))
    projets: dict[str, list[str]] = {}
    for l in cx.execute(
        "SELECT DISTINCT u.fiche_id, p.titre FROM ("
        "SELECT pf.fiche_id AS fiche_id, pl.projet_id AS projet_id FROM plans_fiches pf JOIN plans pl ON pl.id = pf.plan_id "
        "UNION SELECT fiche_id, projet_id FROM casting"
        ") u JOIN projets p ON p.id = u.projet_id ORDER BY p.titre"
    ):
        projets.setdefault(l["fiche_id"], []).append(l["titre"])
    return [
        FicheBibliotheque(
            id=l["id"], type=l["type"], nom=l["nom"], description=l["description"],
            images=images.get(l["id"], []), projets=projets.get(l["id"], []),
        )
        for l in cx.execute("SELECT * FROM fiches ORDER BY rowid")
    ]


def lire_fiche(cx: sqlite3.Connection, fiche_id: str) -> FicheBibliotheque | None:
    return next((f for f in lister_fiches(cx) if f.id == fiche_id), None)


def supprimer_fiche(cx: sqlite3.Connection, fiche_id: str) -> bool:
    return cx.execute("DELETE FROM fiches WHERE id = ?", (fiche_id,)).rowcount == 1


# --- Actions programmées -----------------------------------------------------------------------------


def _action(l: sqlite3.Row) -> ActionProgrammee:
    return ActionProgrammee(
        id=l["id"], projet_id=l["projet_id"], type=l["type"], plan_id=l["plan_id"], clip_id=l["clip_id"],
        reglages=json.loads(l["reglages"]), statut=l["statut"], cree_le=l["cree_le"],
    )


def programmer_action(cx: sqlite3.Connection, projet_id: str, entree: ActionEntree) -> ActionProgrammee:
    action = ActionProgrammee(
        id=nouvel_id("action"), projet_id=projet_id, type=entree.type, plan_id=entree.plan_id, clip_id=entree.clip_id,
        reglages=entree.reglages, statut=StatutAction.PROGRAMMEE, cree_le=horodatage(),
    )
    cx.execute(
        "INSERT INTO actions (id, projet_id, type, plan_id, clip_id, reglages, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (action.id, projet_id, action.type.value, action.plan_id, action.clip_id, _json(action.reglages), action.statut.value, action.cree_le),
    )
    return action


def lister_actions(cx: sqlite3.Connection, projet_id: str, statut: StatutAction | None = None) -> list[ActionProgrammee]:
    requete = "SELECT * FROM actions WHERE projet_id = ?"
    parametres: list[Any] = [projet_id]
    if statut is not None:
        requete += " AND statut = ?"
        parametres.append(statut.value)
    return [_action(l) for l in cx.execute(requete + " ORDER BY rowid", parametres)]


def marquer_actions(cx: sqlite3.Connection, ids: list[str], statut: StatutAction) -> None:
    cx.executemany("UPDATE actions SET statut = ? WHERE id = ?", [(statut.value, action_id) for action_id in ids])


def supprimer_action(cx: sqlite3.Connection, projet_id: str, action_id: str) -> bool:
    """Retire une action encore programmée (une action lancée appartient à la file)."""
    return (
        cx.execute(
            "DELETE FROM actions WHERE id = ? AND projet_id = ? AND statut = ?",
            (action_id, projet_id, StatutAction.PROGRAMMEE.value),
        ).rowcount
        == 1
    )


# --- Projets du Director : création, champs, données du module, plans -------------------------------

CHAMPS_PROJET_MODIFIABLES = frozenset({"chanson", "paroles", "duree_chanson_s"})
CHAMPS_PLAN_MODIFIABLES = frozenset(
    {
        "moteur_video", "moteur_image", "images", "fps", "prompt_image", "prompt_video", "prompt_son", "image_depart",
        "debut_s", "prise_active_id",
    }
)


def lire_donnees_module(cx: sqlite3.Connection, projet_id: str) -> dict[str, Any]:
    ligne = cx.execute("SELECT donnees_module FROM projets WHERE id = ?", (projet_id,)).fetchone()
    if ligne is None:
        raise KeyError(projet_id)
    return json.loads(ligne["donnees_module"])


def modifier_donnees_module(cx: sqlite3.Connection, projet_id: str, cle: str, valeur: Any) -> None:
    """Seule écriture autorisée de `donnees_module` : relit, change UNE clé (None la retire), réécrit."""
    donnees = lire_donnees_module(cx, projet_id)
    if valeur is None:
        donnees.pop(cle, None)
    else:
        donnees[cle] = valeur
    cx.execute(
        "UPDATE projets SET donnees_module = ?, modifie_le = ? WHERE id = ?", (_json(donnees), horodatage(), projet_id)
    )


def creer_projet(
    cx: sqlite3.Connection, entree: ProjetEntree, module: str, etat_phases: dict[str, EtatPhase]
) -> Projet:
    projet = Projet(
        id=nouvel_id("projet"), titre=entree.titre, module=module, format=entree.format, cree_le=horodatage(),
        recette_id=entree.recette_id, etat_phases=etat_phases, paroles=entree.paroles, casting=entree.casting,
    )
    inserer_projet(cx, projet)
    return projet


def maj_projet(cx: sqlite3.Connection, projet_id: str, **champs: Any) -> None:
    inconnus = set(champs) - CHAMPS_PROJET_MODIFIABLES
    if inconnus:
        raise ValueError(f"champs de projet non modifiables : {sorted(inconnus)}")
    for colonne, valeur in champs.items():
        cx.execute(f"UPDATE projets SET {colonne} = ?, modifie_le = ? WHERE id = ?", (valeur, horodatage(), projet_id))


def definir_etat_phase(cx: sqlite3.Connection, projet_id: str, phase: str, etat: EtatPhase) -> dict[str, EtatPhase]:
    ligne = cx.execute("SELECT etat_phases FROM projets WHERE id = ?", (projet_id,)).fetchone()
    if ligne is None:
        raise KeyError(projet_id)
    etats = {cle: EtatPhase(valeur) for cle, valeur in json.loads(ligne["etat_phases"]).items()}
    etats[phase] = EtatPhase(etat)
    cx.execute(
        "UPDATE projets SET etat_phases = ?, modifie_le = ? WHERE id = ?",
        (_json({cle: valeur.value for cle, valeur in etats.items()}), horodatage(), projet_id),
    )
    return etats


def remplacer_plans(cx: sqlite3.Connection, projet_id: str, plans: list[Plan]) -> None:
    """Nouveau découpage : les anciens plans partent (prises, sorties, clips et actions suivent en cascade)."""
    cx.execute("DELETE FROM plans WHERE projet_id = ?", (projet_id,))
    _inserer_plans(cx, projet_id, plans)


def maj_plan(cx: sqlite3.Connection, plan_id: str, **champs: Any) -> None:
    inconnus = set(champs) - CHAMPS_PLAN_MODIFIABLES
    if inconnus:
        raise ValueError(f"champs de plan non modifiables : {sorted(inconnus)}")
    for colonne, valeur in champs.items():
        valeur_sql = valeur.value if hasattr(valeur, "value") else valeur
        cx.execute(f"UPDATE plans SET {colonne} = ? WHERE id = ?", (valeur_sql, plan_id))
