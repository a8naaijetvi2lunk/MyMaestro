import subprocess

import pytest
from fastapi.testclient import TestClient

from mymaestro.app import creer_app
from mymaestro.connectors.base import ErreurMoteur
from mymaestro.connectors.export import ConnecteurExport
from mymaestro.connectors.simule import registre_simule
from mymaestro.contrat.modeles import Clip, Regime, StatutJob, Timeline, Voie
from mymaestro.core import empreintes
from mymaestro.core.export import SourceClip, projeter, rendre
from mymaestro.core.file import JobFile
from mymaestro.outils import ffmpeg


def _ffmpeg_disponible() -> bool:
    try:
        ffmpeg.trouver("ffmpeg")
        ffmpeg.trouver("ffprobe")
        return True
    except FileNotFoundError:
        return False


def _timeline(clips, duree=10.0, pistes=("V2", "V1", "A0")):
    return Timeline(projet_id="p", duree_chanson_s=duree, pistes=list(pistes), clips=clips)


def _video(clip_id, piste, position, sortie, entree=0.0, plan="plan"):
    return Clip(id=clip_id, piste=piste, plan_id=plan, position_s=position, entree_s=entree, sortie_s=sortie)


def test_piste_haute_gagne_trous_noirs_et_reprise():
    timeline = _timeline([
        _video("a", "V1", 0.0, 6.0, plan="p1"),
        _video("b", "V2", 2.0, 3.5, entree=1.0, plan="p2"),
        _video("c", "V1", 7.0, 2.0, plan="p3"),
    ])
    segments = projeter(timeline, {"a": SourceClip("prises/a.mp4"), "b": SourceClip(None)})
    assert [(s.debut_s, s.fin_s, s.clip_id) for s in segments] == [
        (0.0, 2.0, "a"), (2.0, 4.5, "b"), (4.5, 6.0, "a"), (6.0, 7.0, None), (7.0, 9.0, "c"), (9.0, 10.0, None),
    ]
    assert segments[1].fichier is None and segments[1].plan_id == "p2" and segments[1].source_debut_s == 1.0
    assert segments[2].fichier == "prises/a.mp4" and segments[2].source_debut_s == pytest.approx(4.5)
    assert segments[4].fichier is None  # clip sans source connue : image noire


def test_clip_masque_ne_coupe_pas_le_clip_du_dessus_et_fin_bornee():
    timeline = _timeline([_video("haut", "V2", 0.0, 6.0), _video("bas", "V1", 2.0, 1.0), _video("long", "V1", 6.0, 20.0)])
    segments = projeter(timeline, {"haut": SourceClip("h.mp4"), "long": SourceClip("l.mp4")})
    assert [(s.debut_s, s.fin_s, s.clip_id) for s in segments] == [(0.0, 6.0, "haut"), (6.0, 10.0, "long")]
    assert segments[0].source_debut_s == 0.0


def test_timeline_sans_video_est_noire():
    segments = projeter(_timeline([], duree=3.2), {})
    assert [(s.debut_s, s.fin_s, s.fichier) for s in segments] == [(0.0, 3.2, None)]


def _video_source(chemin, secondes, fps, couleur):
    subprocess.run(
        [ffmpeg.trouver("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={couleur}:s=160x90:r={fps}",
         "-t", str(secondes), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(chemin)],
        check=True, capture_output=True, timeout=60,
    )
    return chemin


def _son(chemin, secondes):
    subprocess.run(
        [ffmpeg.trouver("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", str(secondes), str(chemin)],
        check=True, capture_output=True, timeout=60,
    )
    return chemin


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_rendu_exact_en_images_avec_son(tmp_path):
    rouge = _video_source(tmp_path / "rouge.mp4", 3.0, 25, "red")
    bleu = _video_source(tmp_path / "bleu.mp4", 2.0, 24, "blue")
    chanson = _son(tmp_path / "chanson.wav", 4.0)
    donnees = {
        "segments": [
            {"debut_s": 0.0, "fin_s": 1.5, "fichier": str(rouge), "source_debut_s": 0.5},
            {"debut_s": 1.5, "fin_s": 3.0, "fichier": str(bleu), "source_debut_s": 1.0},  # source trop courte : dernière image prolongée
            {"debut_s": 3.0, "fin_s": 4.0, "fichier": None, "source_debut_s": 0.0},
        ],
        "audio": [{"fichier": str(chanson), "position_s": 0.0, "entree_s": 0.0, "sortie_s": 4.0, "volume": 1.0,
                   "fondu_entree_s": 0.0, "fondu_sortie_s": 0.5}],
        "largeur": 320, "hauteur": 180, "fps": 24, "destination": str(tmp_path / "exports" / "clip.mp4"),
    }
    etapes: list[float] = []
    sortie = rendre(donnees, etapes.append)
    infos = ffmpeg.sonder(sortie)
    assert (infos["largeur"], infos["hauteur"], infos["images"]) == (320, 180, 96)
    assert infos["audio"] is True and infos["duree_s"] == pytest.approx(4.0, abs=0.05)
    assert etapes[-1] == 1.0 and not (tmp_path / "exports" / "clip.tmp").exists()


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_seek_apres_la_derniere_image_ne_tronque_pas_la_suite(tmp_path):
    rouge = _video_source(tmp_path / "rouge.mp4", 3.0, 24, "red")
    vert = _video_source(tmp_path / "vert.mp4", 3.0, 24, "green")
    chanson = _son(tmp_path / "chanson.wav", 6.0)
    timeline = _timeline([
        _video("a", "V1", 0.0, 3.0, plan="pa"), _video("b", "V2", 1.0, 1.97, plan="pb"), _video("c", "V1", 3.0, 3.0, plan="pc"),
    ], duree=6.0)
    sources = {"a": SourceClip(str(rouge)), "b": SourceClip(str(vert)), "c": SourceClip(str(vert))}
    segments = projeter(timeline, sources)
    assert segments[2].source_debut_s == pytest.approx(2.97)
    donnees = {
        "segments": [s.model_dump() for s in segments],
        "audio": [{"fichier": str(chanson), "position_s": 0.0, "entree_s": 0.0, "sortie_s": 6.0}],
        "largeur": 160, "hauteur": 90, "fps": 24, "destination": str(tmp_path / "exports" / "abc.mp4"),
    }
    infos = ffmpeg.sonder(rendre(donnees, lambda valeur: None))
    assert infos["images"] == 144


def test_connecteur_export_refuse_une_tache_inconnue():
    connecteur = ConnecteurExport()
    assert connecteur.voie is Voie.CLOUD and connecteur.etat_public().nom == "export"
    job = JobFile(
        id="job-1", voie=Voie.CLOUD, connecteur="export", modele="ffmpeg", projet_id="p", phase="export", ordre=0,
        regime=Regime.PHASES, donnees={"tache": "autre"}, statut=StatutJob.EN_COURS, tentatives=1, erreur=None,
        resultat=None, libelle="", progression=0.0,
    )
    with pytest.raises(ErreurMoteur):
        connecteur.executer(job, lambda valeur: None)


def test_application_enregistre_le_connecteur_export(tmp_path):
    app = creer_app(":memory:", dossier_medias=tmp_path / "medias", dossier_projets=tmp_path / "projets",
                    connecteurs=registre_simule(empreintes.DEFAUTS))
    with TestClient(app) as client:
        noms = [c["nom"] for c in client.get("/api/file").json()["connecteurs"]]
    assert noms[-1] == "export" and "maestro" in noms


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_seek_hors_grille_ne_laisse_pas_de_trou_entre_segments(tmp_path):
    source = _video_source(tmp_path / "source.mp4", 4.0, 24, "red")
    chanson = _son(tmp_path / "chanson.wav", 4.0)
    donnees = {
        "segments": [
            {"debut_s": 0.0, "fin_s": 2.0, "fichier": str(source), "source_debut_s": 1.02},
            {"debut_s": 2.0, "fin_s": 4.0, "fichier": str(source), "source_debut_s": 0.0},
        ],
        "audio": [{"fichier": str(chanson), "position_s": 0.0, "entree_s": 0.0, "sortie_s": 4.0}],
        "largeur": 160, "hauteur": 90, "fps": 24, "destination": str(tmp_path / "exports" / "d.mp4"),
    }
    sortie = rendre(donnees, lambda valeur: None)
    res = subprocess.run(
        [ffmpeg.trouver("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(sortie)], capture_output=True, text=True, check=True)
    pts = [float(x.strip().rstrip(",")) for x in res.stdout.split() if x.strip().rstrip(",")]
    assert len(pts) == 96
    assert max(pts) == pytest.approx(95 / 24, abs=0.002)


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_beaucoup_de_segments_sans_derive(tmp_path):
    """80 segments de 25 images à 24 fps : sans durée exacte dans la liste de concaténation, les horodatages
    arrondis à la milliseconde des intermédiaires dériveraient d'environ 26 ms et le contrôle final échouerait."""
    segments = [
        {"debut_s": round(i * 25 / 24, 3), "fin_s": round((i + 1) * 25 / 24, 3), "fichier": None, "source_debut_s": 0.0}
        for i in range(80)
    ]
    sortie = rendre(
        {"segments": segments, "audio": [], "largeur": 64, "hauteur": 36, "fps": 24, "destination": str(tmp_path / "long.mp4")},
        lambda valeur: None,
    )
    assert ffmpeg.sonder(sortie)["images"] == 2000


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_export_avec_apostrophe_dans_le_chemin(tmp_path):
    rouge = _video_source(tmp_path / "rouge.mp4", 2.0, 24, "red")
    donnees = {
        "segments": [{"debut_s": 0.0, "fin_s": 1.0, "fichier": str(rouge), "source_debut_s": 0.0}],
        "audio": [], "largeur": 160, "hauteur": 90, "fps": 24, "destination": str(tmp_path / "l'export" / "clip.mp4"),
    }
    assert ffmpeg.sonder(rendre(donnees, lambda valeur: None))["images"] == 24


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_export_rate_ne_laisse_ni_partiel_ni_destination(tmp_path, monkeypatch):
    rouge = _video_source(tmp_path / "rouge.mp4", 2.0, 24, "red")
    donnees = {
        "segments": [{"debut_s": 0.0, "fin_s": 1.0, "fichier": str(rouge), "source_debut_s": 0.0}],
        "audio": [], "largeur": 160, "hauteur": 90, "fps": 24, "destination": str(tmp_path / "exports" / "clip.mp4"),
    }
    monkeypatch.setattr("mymaestro.core.export._dernier_pts_video", lambda fichier: 99.0)
    with pytest.raises(RuntimeError, match="décalé"):
        rendre(donnees, lambda valeur: None)
    assert not list((tmp_path / "exports").glob("*.partiel.mp4"))
    assert not (tmp_path / "exports" / "clip.mp4").exists()
