"""Export d'une timeline (spec §4.1 `core/export`, D9, D25).

1. Projection : la timeline multi-pistes devient une suite de segments. Sur chaque intervalle, la piste
   vidéo la plus haute qui a un clip gagne ; un intervalle sans clip est noir ; les morceaux contigus d'un
   même clip sont fusionnés. L'aperçu et l'export suivent la même projection : ce qui est vu est ce qui est
   exporté (projection de segments du montage multipiste).
2. Rendu : un intermédiaire normalisé par segment (taille de sortie, fps maître, nombre d'images exact),
   concaténation sans réencodage, mixage des pistes audio (la chanson et les sons), puis un seul encodage
   AAC. Durcissements repris de tools/serveur-montage.py de Maestro : durées calées sur les images, `tpad`
   si la source est trop courte, `amix normalize=0` puis `alimiter`.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contrat.modeles import Segment, Timeline
from ..outils import ffmpeg

SEGMENT_MIN_S = 0.002  # micro-segments dus aux arrondis : ignorés


@dataclass(frozen=True)
class SourceClip:
    """Ce que la projection doit savoir d'un clip vidéo : son fichier (None : pas encore rendu)."""

    fichier: str | None


def _rang_piste(piste: str) -> int:
    return int(piste[1:])


def projeter(timeline: Timeline, sources: Mapping[str, SourceClip], fin_s: float | None = None) -> list[Segment]:
    """Segments couvrant [0, fin_s] (fin_s : durée de la chanson par défaut), bornes arrondies à la milliseconde."""
    fin = timeline.duree_chanson_s if fin_s is None else fin_s
    videos = [clip for clip in timeline.clips if clip.piste.startswith("V")]
    bornes = {0.0, round(fin, 3)}
    for clip in videos:
        for instant in (clip.position_s, clip.fin_s):
            if 0 < instant < fin:
                bornes.add(round(instant, 3))
    ordonnees = sorted(bornes)
    segments: list[Segment] = []
    for debut, fin_segment in zip(ordonnees, ordonnees[1:]):
        if fin_segment - debut < SEGMENT_MIN_S:
            continue
        milieu = (debut + fin_segment) / 2
        couvrants = [clip for clip in videos if clip.position_s <= milieu < clip.fin_s]
        clip = max(couvrants, key=lambda c: _rang_piste(c.piste), default=None)
        if clip is None:
            morceau = Segment(debut_s=debut, fin_s=fin_segment)
        else:
            source = sources.get(clip.id)
            morceau = Segment(
                debut_s=debut, fin_s=fin_segment, clip_id=clip.id, plan_id=clip.plan_id,
                fichier=source.fichier if source is not None else None,
                source_debut_s=max(0.0, round(clip.entree_s + (debut - clip.position_s), 6)),
            )
        precedent = segments[-1] if segments else None
        if precedent is not None and precedent.clip_id == morceau.clip_id and abs(precedent.fin_s - morceau.debut_s) < 1e-9:
            segments[-1] = precedent.model_copy(update={"fin_s": morceau.fin_s})
        else:
            segments.append(morceau)
    return segments


def _executer(commande: list[str], delai_s: float = 1800) -> None:
    resultat = subprocess.run(commande, capture_output=True, timeout=delai_s)
    if resultat.returncode != 0:
        lignes = resultat.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise RuntimeError(f"ffmpeg a échoué : {lignes[-1] if lignes else resultat.returncode}")


def _filtre_audio(indice: int, son: Mapping[str, Any]) -> str:
    """Un clip audio : portion du fichier, fondus, volume, position dans le montage."""
    entree = float(son["entree_s"])
    sortie = float(son["sortie_s"])
    position = float(son["position_s"])
    duree = max(sortie - entree, 0.0)
    etapes = [f"atrim=start={entree:.5f}:end={sortie:.5f}", "asetpts=PTS-STARTPTS", "aresample=48000",
              "aformat=channel_layouts=stereo"]
    fondu_entree = min(float(son.get("fondu_entree_s", 0.0)), duree)
    fondu_sortie = min(float(son.get("fondu_sortie_s", 0.0)), duree)
    if fondu_entree > 0.01:
        etapes.append(f"afade=t=in:st=0:d={fondu_entree:.5f}")
    if fondu_sortie > 0.01:
        etapes.append(f"afade=t=out:st={max(duree - fondu_sortie, 0.0):.5f}:d={fondu_sortie:.5f}")
    etapes.append(f"volume={float(son.get('volume', 1.0)):.3f}")
    if position > 0.0005:
        etapes.append(f"adelay={round(position * 1000)}:all=1")
    return f"[{indice}:a]{','.join(etapes)}[s{indice}]"


def _dernier_pts_video(fichier: Path) -> float:
    """Horodatage de la dernière image vidéo : un trou entre segments le décale sans changer le nombre d'images."""
    resultat = subprocess.run(
        [ffmpeg.trouver("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(fichier)],
        capture_output=True, text=True, timeout=120,
    )
    valeurs = [float(ligne.strip().rstrip(",")) for ligne in resultat.stdout.splitlines() if ligne.strip().rstrip(",")]
    if resultat.returncode != 0 or not valeurs:
        raise RuntimeError("export illisible : impossible de lire les horodatages vidéo")
    return max(valeurs)


def rendre(donnees: Mapping[str, Any], progression: Callable[[float], None]) -> Path:
    """Exécute un export décrit par `donnees` (chemins absolus, voir le plan 5a) ; renvoie le fichier produit."""
    exe = ffmpeg.trouver("ffmpeg")
    largeur, hauteur, fps = int(donnees["largeur"]), int(donnees["hauteur"]), int(donnees["fps"])
    segments = list(donnees["segments"])
    sons = list(donnees.get("audio") or [])
    destination = Path(str(donnees["destination"]))
    temp = destination.parent / f"{destination.stem}.tmp"
    shutil.rmtree(temp, ignore_errors=True)
    temp.mkdir(parents=True)
    etapes = len(segments) + 2
    normalisation = (
        f"scale={largeur}:{hauteur}:force_original_aspect_ratio=increase,crop={largeur}:{hauteur},setsar=1,fps={fps}:start_time=0"
    )
    partiel = destination.with_name(f"{destination.stem}.partiel.mp4")
    limites: dict[str, float] = {}

    def debut_borne(fichier: str, debut: float) -> float:
        """Un `-ss` au-delà de la dernière image donne un mkv vide (ffmpeg sort 0) : on garde deux images pour `tpad`."""
        if fichier not in limites:
            infos = ffmpeg.sonder(Path(fichier))
            cadence = float(infos.get("fps") or fps) or float(fps)
            limites[fichier] = max(0.0, float(infos["duree_s"]) - 2 / cadence)
        return min(debut, limites[fichier])

    try:
        liste: list[str] = []
        total_images = 0
        for rang, segment in enumerate(segments):
            images = round(float(segment["fin_s"]) * fps) - round(float(segment["debut_s"]) * fps)
            if images <= 0:
                continue
            duree = images / fps
            cible = temp / f"segment-{rang:04d}.mkv"
            if segment.get("fichier"):
                commande = [exe, "-y", "-v", "error", "-ss",
                            f"{debut_borne(str(segment['fichier']), float(segment['source_debut_s'])):.3f}",
                            "-i", str(segment["fichier"]),
                            "-vf", f"{normalisation},tpad=stop_mode=clone:stop_duration={duree:.3f}"]
            else:
                commande = [exe, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={largeur}x{hauteur}:r={fps}"]
            commande += ["-an", "-frames:v", str(images), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                         "-pix_fmt", "yuv420p", "-r", str(fps), str(cible)]
            _executer(commande)
            # Durée exacte : le mkv arrondit ses horodatages à la milliseconde, et le démuxeur concat, qui enchaîne
            # les fichiers sur cette durée arrondie, dériverait d'environ 1/3 ms par segment à 24 fps.
            chemin_liste = cible.as_posix().replace("'", "'\\''")
            liste.append(f"file '{chemin_liste}'\nduration {images / fps:.6f}")
            total_images += images
            progression((rang + 1) / etapes)
        if not liste:
            raise RuntimeError("Timeline vide : rien à exporter")
        fichier_liste = temp / "liste.txt"
        fichier_liste.write_text("\n".join(liste) + "\n", encoding="utf-8")
        video = temp / "video.mkv"
        _executer([exe, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(fichier_liste), "-c", "copy", str(video)])
        progression((len(segments) + 1) / etapes)
        duree_totale = total_images / fps
        commande = [exe, "-y", "-v", "error", "-i", str(video)]
        filtres: list[str] = []
        etiquettes: list[str] = []
        for indice, son in enumerate(sons, start=1):
            commande += ["-i", str(son["fichier"])]
            filtres.append(_filtre_audio(indice, son))
            etiquettes.append(f"[s{indice}]")
        if etiquettes:
            filtres.append(
                f"{''.join(etiquettes)}amix=inputs={len(etiquettes)}:duration=longest:dropout_transition=0:normalize=0,"
                f"alimiter=limit=0.97,apad,atrim=end={duree_totale:.5f}[aout]"
            )
        else:
            filtres.append(f"anullsrc=r=48000:cl=stereo,atrim=end={duree_totale:.5f}[aout]")
        destination.parent.mkdir(parents=True, exist_ok=True)
        commande += ["-filter_complex", ";".join(filtres), "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                     "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(partiel)]
        _executer(commande)
        obtenues = ffmpeg.sonder(partiel).get("images")
        if obtenues != total_images:
            raise RuntimeError(f"export incomplet : {obtenues} images sur {total_images}")
        dernier = _dernier_pts_video(partiel)
        if abs(dernier - (total_images - 1) / fps) > 0.5 / fps:
            raise RuntimeError(f"export décalé : dernière image à {dernier:.3f} s au lieu de {(total_images - 1) / fps:.3f} s")
        partiel.replace(destination)
        progression(1.0)
        return destination
    except BaseException:
        partiel.unlink(missing_ok=True)  # la destination finale n'est jamais touchée en cas d'échec
        raise
    finally:
        shutil.rmtree(temp, ignore_errors=True)
