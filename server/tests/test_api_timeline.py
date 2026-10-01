import io
import subprocess
import threading
import wave

import pytest
from fastapi.testclient import TestClient

from mymaestro import modules
from mymaestro.app import creer_app
from mymaestro.connectors.simule import registre_simule
from mymaestro.connectors.base import ErreurMoteur
from mymaestro.contrat.modeles import FormatImage, MoteurVideo
from mymaestro.core import empreintes
from mymaestro.fixtures import demo
from mymaestro.modules.director_musique import actions, exports, timeline
from mymaestro.outils import ffmpeg

URL = f"/api/projets/{demo.PROJET_DEMO}"


def _ffmpeg_disponible() -> bool:
    try:
        ffmpeg.trouver("ffmpeg")
        ffmpeg.trouver("ffprobe")
        return True
    except FileNotFoundError:
        return False


def _wav(secondes: float) -> bytes:
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(8000)
        sortie.writeframes(b"\x00\x00" * int(8000 * secondes))
    return tampon.getvalue()


@pytest.fixture
def env(tmp_path):
    projets = tmp_path / "projets"
    app = creer_app(
        ":memory:", dossier_medias=tmp_path / "medias", dossier_projets=projets,
        connecteurs=registre_simule(empreintes.DEFAUTS, repondeur=modules.repondeur_simule(projets)),
    )
    with TestClient(app) as client:
        yield client, projets


def test_lecture_et_edition_de_la_timeline(env):
    client, _ = env
    assert {"clip-chanson", "clip-plan-00"} <= {c["id"] for c in client.get(f"{URL}/timeline").json()["clips"]}
    refus = client.patch(f"{URL}/timeline/clips/clip-plan-01", json={"position_s": 6.0})
    assert refus.status_code == 409 and "déverrouille" in refus.json()["detail"]
    assert client.patch(f"{URL}/timeline/clips/inconnu", json={"volume": 0.5}).status_code == 404
    assert client.patch(f"{URL}/timeline/clips/clip-chanson", json={"volume": 3}).status_code == 422
    assert client.post(f"{URL}/timeline/pistes", json={"type": "video"}).json()["pistes"][0] == "V2"
    coupee = client.post(f"{URL}/timeline/clips/clip-plan-02/couper", json={"temps_s": 16.0}).json()
    morceaux = [c for c in coupee["clips"] if c["plan_id"] == "plan-02"]
    assert len(morceaux) == 2
    autre = next(c for c in morceaux if c["id"] != "clip-plan-02")
    assert client.delete(f"{URL}/timeline/clips/{autre['id']}").status_code == 200
    assert client.delete(f"{URL}/timeline/clips/clip-plan-02").status_code == 409
    assert client.get(f"/api/projets/{demo.PROJET_VERTICAL}/timeline").status_code == 404


def test_segments_prises_et_nettoyage(env):
    client, _ = env
    segments = client.get(f"{URL}/timeline/segments").json()
    assert segments[0]["clip_id"] == "clip-plan-00" and segments[-1]["fin_s"] == demo.DUREE_CHANSON_S
    projet = client.put(f"{URL}/plans/plan-01/prise-active", json={"prise_id": "plan-01-p1"}).json()
    assert next(p for p in projet["plans"] if p["id"] == "plan-01")["prise_active_id"] == "plan-01-p1"
    assert client.put(f"{URL}/plans/plan-06/prise-active", json={"prise_id": "plan-06-p1"}).status_code == 409
    assert client.put(f"{URL}/prises/plan-01-p2/sortie-active", json={"sortie_id": None}).status_code == 200
    assert client.put(f"{URL}/prises/plan-01-p2/sortie-active", json={"sortie_id": "inconnue"}).status_code == 404
    assert client.post(f"{URL}/prises/nettoyer").json()["prises_supprimees"] == 1  # plan-01-p2 n'est plus active


def test_estimation_video(env):
    client, _ = env
    estimation = client.get(f"{URL}/video/estimation").json()
    assert estimation["plans"] == 8 and estimation["suffisant"] is True


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_import_de_son(env):
    client, projets = env
    reponse = client.put(f"{URL}/sons?position_s=2.0", content=_wav(1.5), headers={"Content-Type": "audio/wav"})
    assert reponse.status_code == 200
    son = next(c for c in reponse.json()["clips"] if (c["fichier_audio"] or "").startswith("sons/import-"))
    assert (son["piste"], son["position_s"]) == ("A1", 2.0) and son["sortie_s"] == pytest.approx(1.5, abs=0.01)
    assert (projets / demo.PROJET_DEMO / son["fichier_audio"]).is_file()
    assert client.put(f"{URL}/sons", content=b"texte", headers={"Content-Type": "text/plain"}).status_code == 415


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_son_ne_peut_pas_depasser_son_fichier(env):
    client, _ = env
    reponse = client.put(f"{URL}/sons?position_s=2.0", content=_wav(1.5), headers={"Content-Type": "audio/wav"})
    son = next(c for c in reponse.json()["clips"] if (c["fichier_audio"] or "").startswith("sons/import-"))
    trop = client.patch(f"{URL}/timeline/clips/{son['id']}", json={"sortie_s": 9})
    assert trop.status_code == 409 and "Le son dure" in trop.json()["detail"]
    assert client.patch(f"{URL}/timeline/clips/{son['id']}", json={"sortie_s": 1.0}).status_code == 200


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_export_du_montage_et_60_fps(env, monkeypatch):
    client, projets = env
    monkeypatch.setitem(exports.RESOLUTIONS_SORTIE, FormatImage.PAYSAGE, (320, 180))  # rapide : la taille ne change rien au calage
    export = client.post(f"{URL}/exports", json={"interpolation_60fps": True})
    assert export.status_code == 201 and export.json()["statut"] == "en_file" and export.json()["interpolation_60fps"] is True
    client.app.state.ordonnanceur.vider()
    [fini] = client.get(f"{URL}/exports").json()
    assert fini["statut"] == "termine" and fini["fichier"] and fini["fichier_60fps"]
    infos = ffmpeg.sonder(projets / demo.PROJET_DEMO / fini["fichier"])
    assert (infos["largeur"], infos["hauteur"]) == (320, 180)
    assert infos["duree_s"] == pytest.approx(demo.DUREE_CHANSON_S, abs=0.1)
    piece_jointe = client.get(f"{URL}/medias/{fini['fichier']}?telecharger=true")
    assert piece_jointe.headers["content-disposition"].startswith("attachment")
    assert client.get(URL).json()["etat_phases"]["export"] == "termine"
    assert client.post(f"/api/projets/{demo.PROJET_VERTICAL}/exports", json={}).status_code == 409


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_export_ancien_annule_ne_touche_pas_la_phase(env, monkeypatch):
    client, _ = env
    monkeypatch.setitem(exports.RESOLUTIONS_SORTIE, FormatImage.PAYSAGE, (320, 180))
    ordo = client.app.state.ordonnanceur
    a = client.post(f"{URL}/exports", json={"interpolation_60fps": True}).json()
    ordo.etape_cloud()  # montage de A terminé, interpolation de A en file GPU
    b = client.post(f"{URL}/exports", json={"interpolation_60fps": False}).json()
    ordo.etape_cloud()
    assert client.get(URL).json()["etat_phases"]["export"] == "termine"
    interpolation_a = next(j for j in client.app.state.file.lister_projet(demo.PROJET_DEMO) if j.donnees.get("export_id") == a["id"] and j.donnees.get("tache") == "export.interpolation")
    assert client.post(f"/api/file/jobs/{interpolation_a.id}/annuler").status_code < 300
    assert client.get(URL).json()["etat_phases"]["export"] == "termine"
    assert not client.get(f"{URL}/director").json()["erreurs"].get("export")
    assert {e["id"]: e["statut"] for e in client.get(f"{URL}/exports").json()}[b["id"]] == "termine"


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_import_de_son_refuse_video_seule_et_position_infinie(env, tmp_path):
    client, projets = env
    muet = tmp_path / "muet.mp4"
    subprocess.run(
        [ffmpeg.trouver("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=24", "-t", "1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(muet)],
        check=True, capture_output=True, timeout=60,
    )
    refus = client.put(f"{URL}/sons", content=muet.read_bytes(), headers={"Content-Type": "audio/mp4"})
    assert refus.status_code == 422 and "illisible" in refus.json()["detail"]
    assert not list((projets / demo.PROJET_DEMO / "sons").glob("import-*"))  # le fichier refusé est supprimé
    infini = client.put(f"{URL}/sons?position_s=inf", content=_wav(0.5), headers={"Content-Type": "audio/wav"})
    assert infini.status_code == 422


def test_contrat_refuse_inf_et_nan(env):
    client, _ = env
    for valeur in ("Infinity", "NaN"):
        reponse = client.patch(
            f"{URL}/timeline/clips/clip-plan-00", content=f'{{"position_s": {valeur}}}', headers={"Content-Type": "application/json"}
        )
        assert reponse.status_code == 422


def test_clip_ne_commence_pas_apres_la_fin_de_la_chanson(env):
    client, _ = env
    duree = client.get(f"{URL}/timeline").json()["duree_chanson_s"]
    refus = client.patch(f"{URL}/timeline/clips/clip-plan-00", json={"position_s": duree + 50, "verrou_chanson": False})
    assert refus.status_code == 409


def test_changement_de_moteur_rogne_les_clips_du_plan(env):
    client, _ = env
    reponse = client.patch(f"{URL}/plans/plan-03", json={"moteur_video": MoteurVideo.LTX23.value})
    assert reponse.status_code == 200
    duree = reponse.json()["images"] / reponse.json()["fps"]
    clip = next(c for c in client.get(f"{URL}/timeline").json()["clips"] if c["plan_id"] == "plan-03")
    assert clip["sortie_s"] == pytest.approx(duree, abs=1e-3)


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_montage_rate_garde_sa_cause_malgre_l_interpolation_annulee(env, monkeypatch):
    client, _ = env
    monkeypatch.setitem(exports.RESOLUTIONS_SORTIE, FormatImage.PAYSAGE, (320, 180))

    def casse(donnees, progression):
        raise ErreurMoteur("montage cassé pour le test")

    monkeypatch.setattr("mymaestro.connectors.export.rendre", casse)
    assert client.post(f"{URL}/exports", json={"interpolation_60fps": True}).status_code == 201
    client.app.state.ordonnanceur.vider()
    erreur = client.get(f"{URL}/director").json()["erreurs"]["export"]
    assert "montage cassé" in erreur and "prérequis" not in erreur
    assert client.get(URL).json()["etat_phases"]["export"] == "echec"


def test_nettoyage_garde_la_prise_citee_par_un_export_en_file(env):
    client, _ = env
    export = client.post(f"{URL}/exports", json={}).json()  # non exécuté : ses jobs restent en file
    job = next(j for j in client.app.state.file.lister_projet(demo.PROJET_DEMO) if j.donnees.get("export_id") == export["id"])
    assert "plan-01-p2" in job.donnees["prises"]
    assert client.put(f"{URL}/plans/plan-01/prise-active", json={"prise_id": "plan-01-p1"}).status_code == 200
    assert client.post(f"{URL}/prises/nettoyer").json()["prises_supprimees"] == 0
    assert "plan-01-p2" in {p["id"] for p in client.get(URL).json()["prises"]}


@pytest.mark.parametrize("appel", ["choisir_prise", "choisir_sortie", "nettoyer", "lancer_actions"])
def test_verrous_de_module_serialisent_les_operations(env, appel):
    client, _ = env
    ctx = client.app.state.contexte
    verrou = actions._VERROU_LANCEMENT_ACTIONS if appel == "lancer_actions" else timeline._VERROU_PRISES
    operation = {
        "choisir_prise": lambda: timeline.choisir_prise(ctx, demo.PROJET_DEMO, "plan-01", "plan-01-p1"),
        "choisir_sortie": lambda: timeline.choisir_sortie(ctx, demo.PROJET_DEMO, "plan-01-p2", None),
        "nettoyer": lambda: timeline.nettoyer(ctx, demo.PROJET_DEMO),
        "lancer_actions": lambda: actions.lancer(ctx, demo.PROJET_DEMO),
    }[appel]
    fil = threading.Thread(target=operation)
    with verrou:
        fil.start()
        fil.join(timeout=0.3)
        assert fil.is_alive()  # bloqué tant que le verrou est tenu
    fil.join(timeout=10)
    assert not fil.is_alive()
