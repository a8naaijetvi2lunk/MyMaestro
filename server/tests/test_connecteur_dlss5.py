import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mymaestro.connectors.base import Empreinte, ErreurMoteur, MoteurInterrompu
from mymaestro.connectors.dlss5 import ConnecteurDlss5, options_interpolation, options_neurales
from mymaestro.contrat.modeles import EtatMoteur, Regime, StatutJob, Voie
from mymaestro.core.file import JobFile
from mymaestro.outils import ffmpeg

FAUX_RUNNER = Path(__file__).with_name("faux_dlss5_runner.py")


def _ffmpeg_disponible() -> bool:
    try:
        ffmpeg.trouver("ffmpeg")
        ffmpeg.trouver("ffprobe")
        return True
    except FileNotFoundError:
        return False


pytestmark = pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")


def _connecteur(tmp_path):
    return ConnecteurDlss5(Empreinte(1292, 0), commande=lambda demande: [sys.executable, str(FAUX_RUNNER), str(demande)], repertoire=tmp_path)


def _source(tmp_path):
    chemin = tmp_path / "projet" / "prises" / "p1" / "1-flashvsr.mp4"
    chemin.parent.mkdir(parents=True)
    subprocess.run(
        [ffmpeg.trouver("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x95BAE8:s=64x36:r=24", "-frames:v", "48",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(chemin)],
        check=True, capture_output=True, timeout=60,
    )
    return chemin


def _job(tache, **donnees):
    return JobFile(
        id="job-dlss5", voie=Voie.GPU, connecteur="dlss5", modele="dlss5", projet_id="p", phase=None, ordre=0, regime=Regime.PHASES,
        donnees={"tache": tache, **donnees}, statut=StatutJob.EN_COURS, tentatives=1, erreur=None, resultat=None, libelle="", progression=0.0,
    )


def test_correspondance_des_reglages():
    options = options_neurales({"style": "Cinematic", "intensite": 0.8, "ton_local": 1.2, "structure": 0.9, "facteur": 1.0})
    assert options == {
        "nr_style": "Cinematic", "nr_intensity": 0.8, "local_tone_strength": 1.2, "local_structure_strength": 0.9,
        "upscaling_factor": 1.0, "codec": "H.264 (NVIDIA NVENC)", "container": "MP4", "quality": "Max",
    }
    assert options_interpolation(60)["target_fps"] == "60"


def test_passe_dlss5_copiee_controlee_et_nettoyee(tmp_path):
    connecteur = _connecteur(tmp_path)
    source = _source(tmp_path)
    destination = tmp_path / "projet" / "prises" / "p1" / "2-dlss5.mp4"
    avancees: list[float] = []
    job = _job("postprod.dlss5", source=str(source), reglages={"style": "Default", "intensite": 1.4}, fichier="prises/p1/2-dlss5.mp4",
               destination=str(destination))
    assert connecteur.executer(job, avancees.append) == {"fichier": "prises/p1/2-dlss5.mp4"}
    assert ffmpeg.sonder(destination)["images"] == 48 and 0.5 in avancees and avancees[-1] == 1.0
    assert connecteur.etat is EtatMoteur.CHARGE
    assert not [p for p in destination.parent.iterdir() if p.name.startswith("dlss5-")]  # dossier de travail supprimé


def test_interpolation_de_l_export(tmp_path):
    connecteur = _connecteur(tmp_path)
    source = _source(tmp_path)
    destination = tmp_path / "projet" / "exports" / "e-60fps.mp4"
    job = _job("export.interpolation", source=str(source), fps=60, fichier="exports/e-60fps.mp4", destination=str(destination))
    assert connecteur.executer(job, lambda v: None) == {"fichier": "exports/e-60fps.mp4"}
    assert destination.is_file()


def test_erreurs(tmp_path, monkeypatch):
    connecteur = _connecteur(tmp_path)
    source = _source(tmp_path)
    monkeypatch.setenv("FAUX_DLSS5_ERREUR", "CUDA out of memory")
    job = _job("postprod.dlss5", source=str(source), reglages={}, fichier="prises/p1/2-dlss5.mp4",
               destination=str(tmp_path / "projet" / "prises" / "p1" / "2-dlss5.mp4"))
    with pytest.raises(ErreurMoteur, match="CUDA out of memory"):
        connecteur.executer(job, lambda v: None)
    monkeypatch.delenv("FAUX_DLSS5_ERREUR")
    with pytest.raises(ErreurMoteur, match="introuvable"):
        connecteur.executer(_job("postprod.dlss5", source=str(tmp_path / "absente.mp4"), reglages={}, fichier="x.mp4",
                                 destination=str(tmp_path / "x.mp4")), lambda v: None)
    with pytest.raises(ErreurMoteur, match="inconnue"):
        connecteur.executer(_job("video.plan"), lambda v: None)


def test_arret_pendant_un_traitement_lent(tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_DLSS5_LENT", "1")
    connecteur = _connecteur(tmp_path)
    source = _source(tmp_path)
    job = _job("postprod.dlss5", source=str(source), reglages={}, fichier="prises/p1/2-dlss5.mp4",
               destination=str(tmp_path / "projet" / "prises" / "p1" / "2-dlss5.mp4"))
    demarre = threading.Event()
    resultat: list[BaseException | None] = []

    def tourner():
        try:
            connecteur.executer(job, lambda v: demarre.set())
            resultat.append(None)
        except BaseException as exc:  # noqa: BLE001
            resultat.append(exc)

    fil = threading.Thread(target=tourner)
    fil.start()
    assert demarre.wait(30)
    debut = time.monotonic()
    connecteur.arreter()
    fil.join(10)
    assert not fil.is_alive() and time.monotonic() - debut < 5
    assert isinstance(resultat[0], ErreurMoteur)
    assert connecteur.etat is EtatMoteur.ARRETE


def test_delai_depasse_leve_une_erreur_sans_remise_en_file(tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_DLSS5_LENT", "1")
    connecteur = _connecteur(tmp_path)
    connecteur.delai_s = 1
    source = _source(tmp_path)
    job = _job("postprod.dlss5", source=str(source), reglages={}, fichier="prises/p1/2-dlss5.mp4",
               destination=str(tmp_path / "projet" / "prises" / "p1" / "2-dlss5.mp4"))
    debut = time.monotonic()
    with pytest.raises(ErreurMoteur, match="trop long") as info:
        connecteur.executer(job, lambda v: None)
    assert not isinstance(info.value, MoteurInterrompu)
    assert time.monotonic() - debut < 5
    assert not [p for p in job_dir(tmp_path).iterdir() if p.name.startswith("dlss5-")]


def job_dir(tmp_path):
    return tmp_path / "projet" / "prises" / "p1"


def test_arret_avant_executer_ne_lance_aucun_runner(tmp_path):
    connecteur = _connecteur(tmp_path)
    source = _source(tmp_path)
    connecteur.demarrer()
    connecteur.arreter_sans_attendre()
    job = _job("postprod.dlss5", source=str(source), reglages={}, fichier="prises/p1/2-dlss5.mp4",
               destination=str(tmp_path / "projet" / "prises" / "p1" / "2-dlss5.mp4"))
    with pytest.raises(MoteurInterrompu):
        connecteur.executer(job, lambda v: None)
    assert not list(tmp_path.rglob("options-recues.json"))
    assert connecteur.etat is EtatMoteur.ARRETE


def test_progression_qui_leve_ne_laisse_pas_le_runner_vivant(tmp_path, monkeypatch):
    monkeypatch.setenv("FAUX_DLSS5_LENT", "1")
    connecteur = _connecteur(tmp_path)
    source = _source(tmp_path)
    lances: list[subprocess.Popen] = []
    origine = subprocess.Popen

    def espion(*args, **kwargs):
        processus = origine(*args, **kwargs)
        lances.append(processus)
        return processus

    monkeypatch.setattr("mymaestro.connectors.dlss5.subprocess.Popen", espion)

    def progression(valeur):
        raise RuntimeError("rappel cassé")

    job = _job("postprod.dlss5", source=str(source), reglages={}, fichier="prises/p1/2-dlss5.mp4",
               destination=str(tmp_path / "projet" / "prises" / "p1" / "2-dlss5.mp4"))
    with pytest.raises(RuntimeError, match="rappel cassé"):
        connecteur.executer(job, progression)
    assert lances and all(p.poll() is not None for p in lances)
    assert not [p for p in job_dir(tmp_path).iterdir() if p.name.startswith("dlss5-")]
