"""Répondeur des connecteurs simulés pour le Director : sorties plausibles, toujours étiquetées « simulé ».

Rien ici ne remplace un moteur : ces sorties servent à dérouler les phases et à construire les
écrans avant les connecteurs réels (plan 6). Les images sont des PNG unis écrits en Python pur.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import wave
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ...contrat.modeles import RolePlan
from ...core import medias
from ...core.file import JobFile
from ...outils import ffmpeg
from .modeles import Analyse, LigneParoles, Section

PALETTE = ((240, 164, 204), (149, 186, 232), (168, 188, 117), (241, 211, 105))
TITRES = ("La veilleuse", "Ligne 2", "Nuit blanche, jour gris", "Le dernier métro", "Miroirs")
NOMS_SECTIONS = ("Intro", "Couplet", "Refrain", "Couplet", "Refrain", "Pont", "Refrain", "Outro")
DUREE_SECTION_S = 15.0
PLAN_CHANTE_MAX_S = 10.0


def png_uni(largeur: int, hauteur: int, couleur: tuple[int, int, int]) -> bytes:
    """PNG RVB uni, sans dépendance (zlib + struct)."""

    def bloc(nature: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + nature + donnees + struct.pack(">I", zlib.crc32(nature + donnees) & 0xFFFFFFFF)

    ligne = b"\x00" + bytes(couleur) * largeur
    entete = struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + bloc(b"IHDR", entete) + bloc(b"IDAT", zlib.compress(ligne * hauteur, 9)) + bloc(b"IEND", b"")


TAILLES_SIMULEES = {"16:9": (240, 136), "9:16": (136, 240)}  # petites : les tests restent rapides


def video_simulee(destination: Path, images: int, fps: int, fmt: str, couleur: tuple[int, int, int], audio: str | None) -> None:
    """Vrai mp4 uni au bon nombre d'images ; un plan chanté embarque son segment de chanson, comme un rendu H3."""
    largeur, hauteur = TAILLES_SIMULEES.get(fmt, TAILLES_SIMULEES["16:9"])
    teinte = "".join(f"{canal:02X}" for canal in couleur)
    commande = [ffmpeg.trouver("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x{teinte}:s={largeur}x{hauteur}:r={fps}"]
    if audio:
        commande += ["-i", audio]
    commande += ["-frames:v", str(images), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    commande += ["-c:a", "aac", "-t", f"{images / fps:.4f}"] if audio else ["-an"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*commande, str(destination)], check=True, capture_output=True, timeout=120)


def son_simule(destination: Path, duree_s: float) -> None:
    """WAV mono discret (sinusoïde à 220 Hz) : un bruitage simulé qu'on entend sans gêner."""
    taux = 48000
    instants = np.arange(int(taux * max(duree_s, 0.1))) / taux
    signal = (0.1 * np.sin(2 * np.pi * 220 * instants) * 32767).astype("<i2")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(taux)
        sortie.writeframes(signal.tobytes())


def analyse_simulee(duree_s: float, paroles: str) -> Analyse:
    """Sections de 15 s, voix hors intro et outro, paroles réparties sur la voix (ou transcription factice)."""
    sections: list[Section] = []
    debut = 0.0
    rang = 0
    while debut < duree_s - 1e-6:
        fin = min(duree_s, debut + DUREE_SECTION_S)
        nom = NOMS_SECTIONS[rang] if rang < len(NOMS_SECTIONS) - 1 else ("Couplet", "Refrain")[(rang - 1) % 2]
        sections.append(Section(nom=nom, debut_s=debut, fin_s=fin))
        debut = fin
        rang += 1
    if len(sections) > 1:
        sections[-1] = sections[-1].model_copy(update={"nom": "Outro"})
    voix = [s for s in sections if s.nom not in ("Intro", "Outro")] or sections
    textes = [ligne.strip() for ligne in paroles.splitlines() if ligne.strip()]
    duree_voix = sum(s.fin_s - s.debut_s for s in voix)
    if not textes:
        textes = [f"(transcription simulée {n + 1})" for n in range(max(1, int(duree_voix // 4)))]
    part = duree_voix / len(textes)
    lignes: list[LigneParoles] = []
    for n, texte in enumerate(textes):
        decalage = n * part
        for segment in voix:
            longueur = segment.fin_s - segment.debut_s
            if decalage < longueur - 1e-9:
                debut_ligne = segment.debut_s + decalage
                lignes.append(LigneParoles(texte=texte, debut_s=round(debut_ligne, 3), fin_s=round(min(segment.fin_s, debut_ligne + part), 3)))
                break
            decalage -= longueur
    temps_forts = [round(n * 0.5, 3) for n in range(int(duree_s / 0.5) + 1)]
    return Analyse(bpm=120.0, temps_forts=temps_forts, sections=sections, voix=voix, lignes=lignes, simule=True)


def decoupage_simule(analyse: Analyse, duree_s: float, concept: dict[str, Any], casting: list[dict[str, str]]) -> dict[str, Any]:
    """Un plan chanté par ligne (coupé au-delà de 10 s), des plans de coupe dans les trous d'au moins 1 s."""
    titre = concept.get("titre", "concept")
    personnages = [f["id"] for f in casting if f.get("type") == "personnage"]
    decors = [f["id"] for f in casting if f.get("type") != "personnage"]
    plans: list[dict[str, Any]] = []
    curseur = 0.0

    def coupe(debut: float, fin: float) -> None:
        plans.append({"role": RolePlan.COUPE.value, "debut_s": round(debut, 3), "fin_s": round(fin, 3),
                      "description": f"Plan de coupe (simulé) — {titre}", "fiches": decors})

    for ligne in sorted(analyse.lignes, key=lambda l: l.debut_s):
        if ligne.debut_s - curseur >= 1.0:
            coupe(curseur, ligne.debut_s)
            curseur = ligne.debut_s
        debut = max(curseur, ligne.debut_s)
        while ligne.fin_s - debut > 1e-6:
            fin = min(ligne.fin_s, debut + PLAN_CHANTE_MAX_S)
            plans.append({"role": RolePlan.CHANTE.value, "debut_s": round(debut, 3), "fin_s": round(fin, 3), "paroles": ligne.texte,
                          "description": f"Plan chanté (simulé) — {ligne.texte}", "fiches": personnages})
            debut = fin
        curseur = max(curseur, ligne.fin_s)
    if duree_s - curseur >= 1.0 or not plans:
        coupe(curseur, duree_s)
    else:
        plans[-1]["fin_s"] = duree_s
    return {"plans": plans}


def _prompt(etape: str, plan: dict[str, Any]) -> str:
    description = plan.get("description", "")
    if etape == "video":
        action = "singing" if plan.get("role") == RolePlan.CHANTE.value else "moving"
        return f"Already {action} as the shot opens, {description}, cinematic lighting (simulated prompt)"
    if etape == "image":
        return f"{description}, clean composition from the reference images (simulated prompt)"
    return f"Night city ambience matching: {description} (simulated prompt)"


def fabriquer_repondeur(dossier_projets: Path) -> Callable[[JobFile], dict[str, Any]]:
    def repondre(job: JobFile) -> dict[str, Any]:
        d = job.donnees
        tache = d.get("tache")
        if tache == "analyse":
            return analyse_simulee(float(d["duree_s"]), str(d.get("paroles", ""))).model_dump(mode="json")
        if tache == "ecriture.concepts":
            ambiance = (d.get("brief") or {}).get("ambiance") or "libre"
            nombre = max(1, min(5, int(d.get("nombre", 3))))
            return {"concepts": [
                {"titre": TITRES[n], "pitch": f"Concept simulé à partir du brief « {ambiance} ».",
                 "arc": "début → fin (simulé)", "traitement": "traitement visuel simulé"}
                for n in range(nombre)
            ]}
        if tache == "ecriture.chat":
            return {"reponse": f"Réponse simulée : « {d.get('message', '')} » est noté pour le découpage."}
        if tache == "ecriture.decoupage":
            analyse = Analyse.model_validate(d["analyse"])
            return decoupage_simule(analyse, float(d["duree_s"]), d.get("concept") or {}, list(d.get("casting") or []))
        if tache in ("prompts.image", "prompts.video", "prompts.son"):
            etape = str(d.get("etape", tache.split(".")[1]))
            return {"prompts": [{"plan_id": p["id"], "prompt": _prompt(etape, p)} for p in d.get("plans", [])]}
        if tache == "images.plan":
            largeur, hauteur = (544, 960) if d.get("format") == "9:16" else (960, 544)
            if d.get("destination") and d.get("fichier"):
                cible, relatif = Path(str(d["destination"])), str(d["fichier"])
            else:
                relatif = f"images/{d['plan_id']}-{job.id}.png"
                cible = medias.chemin_sur(Path(dossier_projets) / str(job.projet_id), relatif)
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(png_uni(largeur, hauteur, PALETTE[int(d.get("indice", 0)) % len(PALETTE)]))
            return {"fichier": relatif, "simule": True}
        if tache == "video.plan":
            video_simulee(
                Path(str(d["destination"])), int(d["images"]), int(d["fps"]), str(d.get("format", "16:9")),
                PALETTE[int(d.get("indice", 0)) % len(PALETTE)], d.get("audio"),
            )
            return {"fichier": d["fichier"], "simule": True}
        if tache in ("postprod.flashvsr", "postprod.dlss5", "export.interpolation"):
            destination = Path(str(d["destination"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(d["source"]), destination)
            return {"fichier": d["fichier"], "simule": True}
        if tache == "bruitage.plan":
            son_simule(Path(str(d["destination"])), float(d["duree_s"]))
            return {"fichier": d["fichier"], "simule": True}
        return {"fichier": f"simule/{job.id}.mp4", "simule": True}

    return repondre
