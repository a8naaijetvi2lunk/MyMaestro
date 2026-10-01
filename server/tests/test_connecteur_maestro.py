import wave

import pytest

from faux_maestro import ANALYSE, FauxMaestro
from mymaestro.connectors.base import Empreinte, ErreurMoteur, MoteurInterrompu
from mymaestro.connectors.maestro import ESPACE, ConnecteurCodex, ConnecteurMaestro, ProcessusMaestro
from mymaestro.contrat.modeles import EtatMoteur, Regime, StatutJob, Voie
from mymaestro.core.file import JobFile
from mymaestro.outils import ffmpeg


def _ffmpeg_disponible() -> bool:
    try:
        ffmpeg.trouver("ffmpeg")
        ffmpeg.trouver("ffprobe")
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")


@pytest.fixture
def faux(tmp_path):
    with FauxMaestro(tmp_path / "sorties") as serveur:
        yield serveur


def _processus(faux, **options):
    return ProcessusMaestro(
        url=faux.url, lancer=lambda: None, prealables=lambda: None, dossier_sorties=faux.dossier, intervalle_s=0.01, **options
    )


def _job(tache, modele=None, voie=Voie.GPU, **donnees):
    return JobFile(
        id="job-test", voie=voie, connecteur="maestro", modele=modele, projet_id="p", phase=None, ordre=0,
        regime=Regime.PHASES, donnees={"tache": tache, **donnees}, statut=StatutJob.EN_COURS, tentatives=1,
        erreur=None, resultat=None, libelle="", progression=0.0,
    )


def _wav(chemin, secondes=1.0):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(chemin), "wb") as sortie:
        sortie.setnchannels(1)
        sortie.setsampwidth(2)
        sortie.setframerate(8000)
        sortie.writeframes(b"\x00\x00" * int(8000 * secondes))
    return chemin


def _video(tmp_path, moteur, images, audio=None):
    destination = tmp_path / "projet" / "prises" / "p1" / "brut.mp4"
    return _job(
        "video.plan", modele=moteur, moteur=moteur, prompt="Already singing as the shot opens", image_depart=str(tmp_path / "depart.png"),
        images=images, fps=24, format="16:9", largeur=960, hauteur=544, audio=audio, graine=7,
        fichier="prises/p1/brut.mp4", destination=str(destination),
    )


def test_rendu_h3_fenetre_explicite_et_sortie_controlee(faux, tmp_path):
    connecteur = ConnecteurMaestro(_processus(faux), Empreinte(8740, 281))
    assert connecteur.etat is EtatMoteur.ARRETE
    connecteur.demarrer()
    audio = _wav(tmp_path / "segment.wav")
    avancees: list[float] = []
    resultat = connecteur.executer(_video(tmp_path, "minimax_h3", 124, str(audio)), avancees.append)
    route, corps = faux.requetes[-1]
    assert route == "/api/v1/generate" and corps["workspace"] == ESPACE
    assert (corps["video_length"], corps["sliding_window_size"], corps["sliding_window_overlap"]) == (124, 124, 18)
    assert corps["settings_version"] == 2.52 and corps["num_inference_steps"] == 20
    assert (corps["audio_prompt_type"], corps["audio_guide"]) == ("A", str(audio))
    assert (corps["resolution"], corps["seed"], corps["image_prompt_type"]) == ("960x544", 7, "S")
    assert resultat["fichier"] == "prises/p1/brut.mp4" and resultat["images"] == 124
    assert ffmpeg.sonder(tmp_path / "projet" / "prises" / "p1" / "brut.mp4")["images"] == 124
    assert connecteur.etat is EtatMoteur.CHARGE and avancees[-1] == 1.0


def test_rendu_ltx_sans_audio(faux, tmp_path):
    connecteur = ConnecteurMaestro(_processus(faux), Empreinte(8740, 281))
    connecteur.executer(_video(tmp_path, "ltx2_22B_distilled_1_1_omninft", 121), lambda v: None)
    corps = faux.requetes[-1][1]
    assert corps["sliding_window_size"] == 121 and "sliding_window_overlap" not in corps
    assert corps["num_inference_steps"] == 8 and "audio_prompt_type" not in corps


def test_sorties_refusees_et_echecs(faux, tmp_path):
    connecteur = ConnecteurMaestro(_processus(faux, echecs_max=3), Empreinte(8740, 281))
    faux.images_en_moins = 20
    with pytest.raises(ErreurMoteur, match="tronquée"):
        connecteur.executer(_video(tmp_path, "minimax_h3", 124), lambda v: None)
    faux.images_en_moins, faux.noir = 0, True
    with pytest.raises(ErreurMoteur, match="noire"):
        connecteur.executer(_video(tmp_path, "minimax_h3", 124), lambda v: None)
    faux.noir, faux.statut_final, faux.erreur = False, "failed", "CUDA out of memory"
    with pytest.raises(ErreurMoteur, match="CUDA out of memory"):
        connecteur.executer(_video(tmp_path, "minimax_h3", 124), lambda v: None)
    faux.statut_final, faux.status_en_panne = "completed", 50
    with pytest.raises(ErreurMoteur, match="Suivi"):
        connecteur.executer(_video(tmp_path, "minimax_h3", 124), lambda v: None)
    assert len(faux.annules) == 1


def test_image_qwen_references_absolues(faux, tmp_path):
    reference = tmp_path / "medias" / "fiche-lina" / "portrait_pied.png"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"png")
    destination = tmp_path / "projet" / "images" / "plan-00-a.png"
    job = _job(
        "images.plan", modele="qwen_image_edit_2511_20B_fp8_lightning_8step", prompt="Lina on the rooftop",
        references=[str(reference), str(tmp_path / "absente.png")], largeur=960, hauteur=544,
        fichier="images/plan-00-a.png", destination=str(destination),
    )
    resultat = ConnecteurMaestro(_processus(faux), Empreinte(8740, 281)).executer(job, lambda v: None)
    corps = faux.requetes[-1][1]
    assert corps["image_refs"] == [str(reference)] and corps["video_prompt_type"] == "KI" and corps["resolution"] == "960x544"
    assert resultat == {"fichier": "images/plan-00-a.png"} and destination.read_bytes().startswith(b"\x89PNG")


def test_flashvsr_bruitage_et_analyse(faux, tmp_path):
    connecteur = ConnecteurMaestro(_processus(faux), Empreinte(8740, 281))
    connecteur.executer(_video(tmp_path, "minimax_h3", 124), lambda v: None)
    source = tmp_path / "projet" / "prises" / "p1" / "brut.mp4"
    flash = _job("postprod.flashvsr", modele="flashvsr2", source=str(source), reglages={"facteur": 2},
                 fichier="prises/p1/1-flashvsr.mp4", destination=str(tmp_path / "projet" / "prises" / "p1" / "1-flashvsr.mp4"))
    assert connecteur.executer(flash, lambda v: None)["fichier"] == "prises/p1/1-flashvsr.mp4"
    assert faux.requetes[-1] == ("/api/v1/tools/upscale", {"video_path": str(source), "method": "flashvsr2", "workspace": ESPACE})
    son = tmp_path / "projet" / "sons" / "bruitage.wav"
    bruitage = _job("bruitage.plan", modele="mmaudio", prompt="footsteps on wet asphalt", video=str(source), duree_s=5.17,
                    fichier="sons/bruitage.wav", destination=str(son))
    assert connecteur.executer(bruitage, lambda v: None) == {"fichier": "sons/bruitage.wav"}
    corps = faux.requetes[-1][1]
    assert corps["sfx_mode"] is True and corps["video_guide"] == str(source) and corps["_mmaudio_variant"] == "v2"
    assert corps["MMAudio_prompt"] == "footsteps on wet asphalt"
    assert ffmpeg.sonder(son)["audio"] is True
    resultat = connecteur.executer(_job("analyse", modele="analyse_audio", chanson=str(tmp_path / "chanson.wav"), paroles="Je marche seule"), lambda v: None)
    assert resultat == {"brut": ANALYSE, "paroles": "Je marche seule"}
    assert faux.requetes[-1][1]["lyrics_hint"] == "Je marche seule" and faux.requetes[-1][1]["transcribe"] is True


def test_liberation_arret_et_prealables(faux, tmp_path):
    connecteur = ConnecteurMaestro(_processus(faux), Empreinte(8740, 281))
    connecteur.executer(_video(tmp_path, "minimax_h3", 124), lambda v: None)
    connecteur.liberer()
    assert faux.liberations == 1 and connecteur.etat is EtatMoteur.DEMARRE
    connecteur.arreter()
    assert connecteur.etat is EtatMoteur.ARRETE

    def refuser() -> None:
        raise ErreurMoteur("Un Maestro lancé à la main occupe déjà le GPU")

    bloque = ProcessusMaestro(url=faux.url, lancer=lambda: None, prealables=refuser, dossier_sorties=faux.dossier)
    with pytest.raises(ErreurMoteur, match="à la main"):
        bloque.demarrer()
    assert not bloque.actif()


def test_liberation_attend_l_image_codex_en_vol_et_bloque_les_nouvelles(faux, tmp_path):
    """Porte fermée pendant release-model : l'image Codex en vol finit d'abord, une nouvelle n'est pas soumise."""
    import threading
    import time

    processus = _processus(faux)
    maestro = ConnecteurMaestro(processus, Empreinte(8740, 281))
    codex = ConnecteurCodex(processus, gpu_libre=lambda: True)
    maestro.demarrer()
    faux.lenteur = 30  # environ 0,3 s de rendu à 0,01 s par interrogation
    resultats: dict[str, object] = {}

    def image(nom: str) -> None:
        job = _job("images.plan", modele="codex_imagegen", voie=Voie.CLOUD, prompt="Lina", references=[], largeur=960, hauteur=544,
                   fichier=f"images/{nom}.png", destination=str(tmp_path / f"{nom}.png"))
        resultats[nom] = codex.executer(job, lambda v: None)

    en_vol = threading.Thread(target=image, args=("a",))
    en_vol.start()
    while not faux.jobs:
        time.sleep(0.01)
    liberation = threading.Thread(target=maestro.liberer)
    liberation.start()
    while not processus._porte_fermee and liberation.is_alive():
        time.sleep(0.005)
    assert not codex.peut_executer()  # porte fermée : la voie cloud attend
    liberation.join(10)
    en_vol.join(10)
    assert resultats["a"] == {"fichier": "images/a.png"} and faux.liberations == 1
    [(_, premier_job)] = [e for e in faux.journal if e[0] == "termine"]
    assert faux.journal.index(("termine", premier_job)) < faux.journal.index(("release", ""))
    assert codex.peut_executer()  # porte rouverte


def test_maestro_mort_au_demarrage_echoue_vite(faux, tmp_path):
    import subprocess
    import sys
    import time

    processus = ProcessusMaestro(
        url="http://127.0.0.1:9", lancer=lambda: subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"]),
        prealables=lambda: None, dossier_sorties=faux.dossier, intervalle_s=0.05, delai_demarrage_s=60,
    )
    depart = time.monotonic()
    with pytest.raises(ErreurMoteur, match="arrêté pendant son démarrage"):
        processus.demarrer()
    assert time.monotonic() - depart < 5 and not processus.lance()


def test_arret_pendant_le_demarrage(faux, tmp_path):
    """Pendant le démarrage, Maestro compte pour l'arbitre (pas « arrêté ») et un arrêt le tue sans attendre la fin."""
    import subprocess
    import sys
    import threading
    import time

    processus = ProcessusMaestro(
        url="http://127.0.0.1:9", lancer=lambda: subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]),
        prealables=lambda: None, dossier_sorties=faux.dossier, intervalle_s=0.05, delai_demarrage_s=60,
    )
    maestro = ConnecteurMaestro(processus, Empreinte(8740, 281))
    erreurs: list[Exception] = []

    def demarrer() -> None:
        try:
            processus.demarrer()
        except ErreurMoteur as exc:
            erreurs.append(exc)

    fil = threading.Thread(target=demarrer)
    fil.start()
    while not processus.lance():
        time.sleep(0.01)
    assert maestro.etat is EtatMoteur.DEMARRE and not processus.actif()
    depart = time.monotonic()
    maestro.arreter()
    fil.join(10)
    assert time.monotonic() - depart < 10 and not processus.lance() and maestro.etat is EtatMoteur.ARRETE
    assert erreurs and "interrompu" in str(erreurs[0])


def test_codex_attend_que_bonsai_libere_le_gpu(faux, tmp_path):
    processus = _processus(faux)
    bonsai_arrete = {"valeur": False}
    codex = ConnecteurCodex(processus, gpu_libre=lambda: bonsai_arrete["valeur"])
    maestro = ConnecteurMaestro(processus, Empreinte(8740, 281))
    assert codex.voie is Voie.CLOUD and not codex.peut_executer()
    bonsai_arrete["valeur"] = True
    assert codex.peut_executer()
    job = _job("images.plan", modele="codex_imagegen", voie=Voie.CLOUD, prompt="Lina", references=[], largeur=960, hauteur=544,
               fichier="images/plan-01-a.png", destination=str(tmp_path / "projet" / "images" / "plan-01-a.png"))
    assert codex.executer(job, lambda v: None) == {"fichier": "images/plan-01-a.png"}
    assert faux.requetes[-1][1]["model_type"] == "codex_imagegen"
    assert maestro.etat is EtatMoteur.DEMARRE  # processus partagé démarré par Codex : l'arbitre le voit


def test_deux_fils_pendant_le_demarrage_attendent_le_port(faux, tmp_path):
    """Processus lancé mais port pas encore ouvert : le 2e fil doit attendre, pas échouer sur un refus de connexion."""
    import http.server
    import socket
    import threading
    import time

    class Vivant:
        pid = 0

        def poll(self):
            return None

    with socket.socket() as sonde:
        sonde.bind(("127.0.0.1", 0))
        port = sonde.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    processus = ProcessusMaestro(
        url=url, lancer=lambda: Vivant(), prealables=lambda: None, dossier_sorties=faux.dossier, intervalle_s=0.01, delai_demarrage_s=20
    )

    def ouvrir_plus_tard() -> None:
        time.sleep(1.5)
        faux.serveur.shutdown()
        faux.serveur.server_close()
        faux.serveur.socket = socket.socket()
        faux.serveur.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        faux.serveur.socket.bind(("127.0.0.1", port))
        faux.serveur.socket.listen(5)
        threading.Thread(target=faux.serveur.serve_forever, daemon=True).start()

    threading.Thread(target=ouvrir_plus_tard, daemon=True).start()
    codex = ConnecteurCodex(processus, gpu_libre=lambda: True)
    resultats: dict[str, object] = {}

    def lancer(nom: str) -> None:
        job = _job("images.plan", modele="codex_imagegen", voie=Voie.CLOUD, prompt="Lina", references=[], largeur=960,
                   hauteur=544, fichier=f"images/{nom}.png", destination=str(tmp_path / f"{nom}.png"))
        try:
            resultats[nom] = codex.executer(job, lambda v: None)
        except Exception as exc:  # noqa: BLE001
            resultats[nom] = exc

    fils = [threading.Thread(target=lancer, args=("a",)), threading.Thread(target=lancer, args=("b",))]
    fils[0].start()
    time.sleep(0.3)
    assert not processus.actif()
    fils[1].start()
    for fil in fils:
        fil.join(30)
    assert resultats["a"] == {"fichier": "images/a.png"} and resultats["b"] == {"fichier": "images/b.png"}, resultats


def test_arret_pendant_un_job_en_vol_interrompt_le_suivi_sans_attendre_les_erreurs_reseau(faux, tmp_path):
    """Passé le délai d'attente des jobs, l'arrêt décidé par MyMaestro est vu tout de suite (pas après 10 erreurs réseau)."""
    import threading
    import time

    processus = _processus(faux, attente_jobs_s=0.1)
    processus.demarrer()
    faux.lenteur = 1000  # environ 10 s de rendu à 0,01 s par interrogation
    erreurs: list[Exception] = []

    def rendre() -> None:
        corps = {"model_type": "codex_imagegen", "prompt": "Lina", "workspace": ESPACE}
        try:
            processus.executer_job("/api/v1/generate", corps, lambda v: None)
        except Exception as exc:  # noqa: BLE001
            erreurs.append(exc)

    fil = threading.Thread(target=rendre)
    fil.start()
    while not faux.jobs:
        time.sleep(0.01)
    depart = time.monotonic()
    processus.arreter()
    fil.join(10)
    assert time.monotonic() - depart < 2
    assert len(erreurs) == 1 and isinstance(erreurs[0], MoteurInterrompu), erreurs
    assert "arrêté par MyMaestro" in str(erreurs[0])


def test_codex_attendant_le_gpu_de_bonsai_est_une_interruption(faux, tmp_path):
    codex = ConnecteurCodex(_processus(faux), gpu_libre=lambda: False)
    job = _job("images.plan", modele="codex_imagegen", voie=Voie.CLOUD, prompt="Lina", references=[], largeur=960, hauteur=544,
               fichier="images/a.png", destination=str(tmp_path / "a.png"))
    with pytest.raises(MoteurInterrompu, match="Bonsai occupe le GPU"):
        codex.executer(job, lambda v: None)
