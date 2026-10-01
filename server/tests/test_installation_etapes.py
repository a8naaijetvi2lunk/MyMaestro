"""Étapes d'installation : extraction sûre, commandes, préchargement Maestro (faux serveur), CLI Claude, lanceur Bonsai intégré."""

import hashlib
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from faux_maestro import FauxMaestro
from mymaestro import config
from mymaestro.connectors import bonsai
from mymaestro.connectors.maestro import ProcessusMaestro
from mymaestro.installation import etapes
from mymaestro.installation.etapes import ContexteEtape, executer_etape
from mymaestro.installation.manifeste import FichierManifeste, MoteurManifeste
from mymaestro.installation.telechargement import ErreurInstallation, InstallationAnnulee


def _ctx(tmp_path: Path, fichiers=(), lancer=None, annule=None) -> tuple[ContexteEtape, list]:
    moteur = MoteurManifeste(
        id="essai", libelle="Essai", requis=False, version="1", espace_mo=1, fichiers=tuple(fichiers), etapes=(), controle=(),
    )
    dossier = tmp_path / "moteur"
    telechargements = dossier / ".telechargements"
    telechargements.mkdir(parents=True)
    messages: list = []
    ctx = ContexteEtape(
        moteur=moteur, dossier=dossier, telechargements=telechargements, annule=annule or threading.Event(),
        progression=lambda etape, fraction, message: messages.append((etape, fraction, message)),
        lancer=lancer or (lambda argv, cwd, annule: subprocess.CompletedProcess(argv, 0, "", "")),
    )
    return ctx, messages


def _zip(chemin: Path, membres: dict[str, bytes]) -> None:
    with zipfile.ZipFile(chemin, "w") as archive:
        for nom, contenu in membres.items():
            archive.writestr(nom, contenu)


# --- extraire ---------------------------------------------------------------------------------------


def test_extraire_filtre_et_aplatit(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _zip(ctx.telechargements / "ffmpeg.zip", {"ff/bin/ffmpeg.exe": b"A", "ff/bin/ffprobe.exe": b"B", "ff/doc/lisez.txt": b"C"})
    executer_etape(
        {"type": "extraire", "fichier": "ffmpeg.zip", "membres": ["*/bin/ffmpeg.exe", "*/bin/ffprobe.exe"], "aplatir": True, "vers": "."}, ctx
    )
    assert sorted(p.name for p in ctx.dossier.iterdir() if p.is_file()) == ["ffmpeg.exe", "ffprobe.exe"]
    assert (ctx.dossier / "ffmpeg.exe").read_bytes() == b"A"


def test_extraire_retire_la_racine_vers_un_sous_dossier(tmp_path):
    ctx, _ = _ctx(tmp_path)
    _zip(ctx.telechargements / "m.zip", {"racine/": b"", "racine/app/launch.py": b"print(1)", "racine/README.md": b"x"})
    executer_etape({"type": "extraire", "fichier": "m.zip", "retirer_racine": True, "vers": "sous"}, ctx)
    assert (ctx.dossier / "sous" / "app" / "launch.py").read_bytes() == b"print(1)"
    assert (ctx.dossier / "sous" / "README.md").exists()


@pytest.mark.parametrize("nom_dangereux", ["../evil.txt", "ok/../../evil.txt", "/absolu.txt", "C:/absolu.txt"])
def test_extraire_refuse_le_zip_slip(tmp_path, nom_dangereux):
    ctx, _ = _ctx(tmp_path)
    _zip(ctx.telechargements / "m.zip", {"bon.txt": b"1", nom_dangereux: b"2"})
    with pytest.raises(ErreurInstallation, match="chemin"):
        executer_etape({"type": "extraire", "fichier": "m.zip", "vers": "."}, ctx)
    assert not (tmp_path / "evil.txt").exists() and not (ctx.dossier.parent / "evil.txt").exists()


def test_extraire_controle_de_contenu(tmp_path):
    contenu = b"print('maestro')"
    bon = hashlib.sha256(contenu).hexdigest()
    ok = FichierManifeste(nom="m.zip", url="http://x", taille=None, sha256=None, controles_contenu={"app/launch.py": bon})
    ctx, _ = _ctx(tmp_path, fichiers=[ok])
    _zip(ctx.telechargements / "m.zip", {"r/app/launch.py": contenu})
    executer_etape({"type": "extraire", "fichier": "m.zip", "retirer_racine": True, "vers": "."}, ctx)

    faux = FichierManifeste(nom="m.zip", url="http://x", taille=None, sha256=None, controles_contenu={"app/launch.py": "0" * 64})
    ctx2, _ = _ctx(tmp_path / "autre", fichiers=[faux])
    _zip(ctx2.telechargements / "m.zip", {"r/app/launch.py": contenu})
    with pytest.raises(ErreurInstallation, match="launch.py"):
        executer_etape({"type": "extraire", "fichier": "m.zip", "retirer_racine": True, "vers": "."}, ctx2)


# --- commande -----------------------------------------------------------------------------------------


def test_commande_substitue_uv_et_dossier(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_JOURNAUX", tmp_path / "journaux")
    monkeypatch.setattr(etapes.shutil, "which", lambda nom: "C:/outils/uv.exe")
    appels = []

    def lancer(argv, cwd, annule):
        appels.append((argv, cwd))
        return subprocess.CompletedProcess(argv, 0, "tout va bien\n", "")

    ctx, _ = _ctx(tmp_path, lancer=lancer)
    (ctx.dossier / "app").mkdir()
    executer_etape({"type": "commande", "cwd": "app", "argv": ["{uv}", "venv", "{dossier}/env"]}, ctx)
    assert appels == [(["C:/outils/uv.exe", "venv", f"{ctx.dossier}/env"], ctx.dossier / "app")]
    journaux = list((tmp_path / "journaux").glob("installation-essai-*.log"))
    assert len(journaux) == 1 and "tout va bien" in journaux[0].read_text(encoding="utf-8")


def test_commande_en_echec_garde_les_20_dernieres_lignes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_JOURNAUX", tmp_path / "journaux")
    monkeypatch.setattr(etapes.shutil, "which", lambda nom: "uv")
    sortie = "\n".join(f"ligne {n}" for n in range(1, 31))
    ctx, _ = _ctx(tmp_path, lancer=lambda argv, cwd, annule: subprocess.CompletedProcess(argv, 3, sortie, ""))
    with pytest.raises(ErreurInstallation) as info:
        executer_etape({"type": "commande", "cwd": ".", "argv": ["{uv}", "pip"]}, ctx)
    message = str(info.value)
    assert "ligne 30" in message and "ligne 11" in message and "ligne 10\n" not in message + "\n" and "ligne 1\n" not in message + "\n"
    journal = next((tmp_path / "journaux").glob("installation-essai-*.log"))
    assert "ligne 1\n" in journal.read_text(encoding="utf-8")


def test_commande_sans_uv(tmp_path, monkeypatch):
    monkeypatch.setattr(etapes.shutil, "which", lambda nom: None)
    ctx, _ = _ctx(tmp_path)
    with pytest.raises(ErreurInstallation, match="uv introuvable"):
        executer_etape({"type": "commande", "cwd": ".", "argv": ["{uv}", "venv"]}, ctx)


def test_etape_inconnue(tmp_path):
    ctx, _ = _ctx(tmp_path)
    with pytest.raises(ErreurInstallation, match="inconnue"):
        executer_etape({"type": "magie"}, ctx)


# --- copier_ressource ---------------------------------------------------------------------------------


def test_copier_ressource(tmp_path):
    ctx, _ = _ctx(tmp_path)
    executer_etape({"type": "copier_ressource", "ressource": "bonsai2-chat-template.jinja", "vers": "models/modele.jinja"}, ctx)
    source = Path(etapes.__file__).with_name("bonsai2-chat-template.jinja")
    assert (ctx.dossier / "models" / "modele.jinja").read_bytes() == source.read_bytes()


# --- precharger_maestro -------------------------------------------------------------------------------


@pytest.fixture
def faux(tmp_path):
    with FauxMaestro(tmp_path / "sorties") as serveur:
        yield serveur


@pytest.fixture(autouse=True)
def prealables_neutres(monkeypatch):
    """Les préalables réels (orphelin, Maestro manuel, port) lisent l'état de la machine : neutres ici, leur contenu est
    vérifié à part (test_precharger_maestro_garde_orphelin_et_port_mais_pas_la_marge, test_processus_maestro)."""
    from mymaestro.connectors import maestro as connecteur_maestro

    monkeypatch.setattr(connecteur_maestro, "_prealables_maestro", lambda **options: None)


@pytest.fixture
def maestro_double(faux, monkeypatch):
    instances: list[ProcessusMaestro] = []

    def fabrique(**options):
        instance = ProcessusMaestro(url=faux.url, lancer=lambda: None, intervalle_s=0.01, **options)
        instances.append(instance)
        return instance

    monkeypatch.setattr(etapes, "ProcessusMaestro", fabrique)
    monkeypatch.setattr(etapes, "INTERVALLE_SONDAGE_S", 0.01)
    return instances


def test_precharger_maestro_succes(tmp_path, faux, maestro_double):
    faux.modeles = {"m1", "m2"}
    faux.polls_avant_fin = 3
    ctx, messages = _ctx(tmp_path)
    executer_etape({"type": "precharger_maestro", "modeles": ["m1", "m2"]}, ctx)
    assert faux.telechargements_demandes == ["m1", "m2"]
    assert len(maestro_double) == 1 and not maestro_double[0].lance()
    assert any(fraction is not None for _, fraction, _ in messages)


def test_precharger_maestro_echec_remonte_l_erreur(tmp_path, faux, maestro_double):
    faux.modeles = {"m1"}
    faux.statut_telechargement = "failed"
    faux.erreur_telechargement = "disque plein"
    ctx, _ = _ctx(tmp_path)
    with pytest.raises(ErreurInstallation, match="disque plein"):
        executer_etape({"type": "precharger_maestro", "modeles": ["m1"]}, ctx)
    assert not maestro_double[0].lance()


def test_precharger_maestro_modele_inconnu_est_un_avertissement(tmp_path, faux, maestro_double):
    faux.modeles = {"m1"}
    ctx, messages = _ctx(tmp_path)
    executer_etape({"type": "precharger_maestro", "modeles": ["m1", "absent"]}, ctx)
    assert faux.telechargements_demandes == ["m1"]
    assert any("absent absent de cette version de Maestro" in message for _, _, message in messages)


def test_precharger_maestro_annulation_arrete_maestro(tmp_path, faux, maestro_double):
    faux.modeles = {"m1"}
    faux.polls_avant_fin = 10**9  # ne finit jamais
    annule = threading.Event()
    threading.Timer(0.3, annule.set).start()
    ctx, _ = _ctx(tmp_path, annule=annule)
    with pytest.raises(InstallationAnnulee):
        executer_etape({"type": "precharger_maestro", "modeles": ["m1"]}, ctx)
    assert not maestro_double[0].lance()


def test_precharger_maestro_annulation_pendant_un_demarrage_lent(tmp_path, faux, monkeypatch):
    faux.modeles = {"m1"}
    monkeypatch.setattr(
        etapes, "ProcessusMaestro",
        lambda **options: ProcessusMaestro(url="http://127.0.0.1:9", lancer=lambda: None, intervalle_s=0.01, delai_demarrage_s=30, **options),
    )
    annule = threading.Event()
    threading.Timer(0.3, annule.set).start()
    ctx, _ = _ctx(tmp_path, annule=annule)
    debut = time.monotonic()
    with pytest.raises(InstallationAnnulee):
        executer_etape({"type": "precharger_maestro", "modeles": ["m1"]}, ctx)
    assert time.monotonic() - debut < 5
    assert faux.telechargements_demandes == []


def test_precharger_maestro_mort_de_maestro_leve_une_erreur(tmp_path, faux, monkeypatch):
    faux.modeles = {"m1"}
    faux.polls_avant_fin = 10**9
    processus = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    monkeypatch.setattr(
        etapes, "ProcessusMaestro",
        lambda **options: ProcessusMaestro(url=faux.url, lancer=lambda: processus, intervalle_s=0.01, **options),
    )
    monkeypatch.setattr(etapes, "INTERVALLE_SONDAGE_S", 0.05)
    threading.Timer(0.5, processus.kill).start()
    ctx, _ = _ctx(tmp_path)
    try:
        with pytest.raises(ErreurInstallation, match="s'est arrêté pendant le préchargement"):
            executer_etape({"type": "precharger_maestro", "modeles": ["m1"]}, ctx)
    finally:
        processus.kill()


# --- installeur_claude --------------------------------------------------------------------------------


def test_installeur_claude_deja_present(tmp_path, monkeypatch):
    monkeypatch.setattr(etapes, "_claude_repond", lambda: True)
    commandes: list = []
    ctx, _ = _ctx(tmp_path, lancer=lambda argv, cwd, annule: commandes.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    executer_etape({"type": "installeur_claude"}, ctx)
    assert commandes == []


def test_installeur_claude_absent_puis_present(tmp_path, monkeypatch):
    commandes: list = []
    reponses = iter([False, True])
    monkeypatch.setattr(etapes, "_claude_repond", lambda: next(reponses))
    ctx, _ = _ctx(tmp_path, lancer=lambda argv, cwd, annule: commandes.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    executer_etape({"type": "installeur_claude"}, ctx)
    assert commandes == [["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm https://claude.ai/install.ps1 | iex"]]


def test_installeur_claude_echec(tmp_path, monkeypatch):
    monkeypatch.setattr(etapes, "_claude_repond", lambda: False)
    ctx, _ = _ctx(tmp_path, lancer=lambda argv, cwd, annule: subprocess.CompletedProcess(argv, 1, "réseau coupé", ""))
    with pytest.raises(ErreurInstallation, match="réseau coupé"):
        executer_etape({"type": "installeur_claude"}, ctx)


# --- lanceur Bonsai intégré ---------------------------------------------------------------------------


class _FauxPopen:
    appels: list = []

    def __init__(self, argv, **options):
        _FauxPopen.appels.append((argv, options))
        self.pid = 4242


def test_lanceur_integre_start_puis_stop(tmp_path, monkeypatch):
    racine = tmp_path / "bonsai"
    racine.mkdir()
    monkeypatch.setattr(config, "BONSAI_RACINE", racine)
    monkeypatch.setattr(config, "DOSSIER_DONNEES", tmp_path / "data")
    monkeypatch.setattr(config, "DOSSIER_JOURNAUX", tmp_path / "data" / "journaux")
    _FauxPopen.appels = []
    monkeypatch.setattr(bonsai.subprocess, "Popen", _FauxPopen)
    arrets: list = []
    monkeypatch.setattr(bonsai.subprocess, "run", lambda argv, **options: arrets.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    monkeypatch.setattr(bonsai, "_ecouteur_bonsai", lambda: None)
    monkeypatch.setattr(bonsai, "_chemin_processus", lambda pid: racine / "bin" / "llama-server.exe")

    bonsai._lanceur_integre("Start")
    (argv, options), = _FauxPopen.appels
    assert argv[0] == str(racine / "bin" / "llama-server.exe")
    assert argv[1:] == (
        "-m models/Ternary-Bonsai-2-27B-PQ2_0.gguf --no-mmproj --host 127.0.0.1 --port 8088 --cors-origins localhost -lv 4 "
        "--alias bonsai2-27b-pq2 -ngl 99 -fa on -c 172032 -np 1 -b 128 -ub 128 -t 12 -ctk q4_0 -ctv q4_0 --temp 1.0 "
        "--top-p 0.95 --top-k 20 --min-p 0 --repeat-penalty 1.0 --jinja --chat-template-file models/bonsai2-chat-template.jinja "
        "--reasoning-format deepseek --reasoning-budget 2048"
    ).split()
    assert options["cwd"] == racine
    fichier_pid = tmp_path / "data" / "bonsai-8088.pid"
    assert fichier_pid.read_text(encoding="utf-8") == "4242"
    assert list((tmp_path / "data" / "journaux").glob("bonsai-*.log"))

    bonsai._lanceur_integre("Stop")
    assert arrets == [["taskkill", "/PID", "4242", "/T", "/F"]]
    assert not fichier_pid.exists()


def test_lanceur_integre_stop_sans_pid_ignore_un_processus_etranger(tmp_path, monkeypatch):
    racine = tmp_path / "bonsai"
    racine.mkdir()
    monkeypatch.setattr(config, "BONSAI_RACINE", racine)
    monkeypatch.setattr(config, "DOSSIER_DONNEES", tmp_path / "data")
    arrets: list = []
    monkeypatch.setattr(bonsai.subprocess, "run", lambda argv, **options: arrets.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    monkeypatch.setattr(bonsai, "_ecouteur_bonsai", lambda: (999, Path("C:/autre/ollama.exe")))
    bonsai._lanceur_integre("Stop")
    assert arrets == []
    monkeypatch.setattr(bonsai, "_ecouteur_bonsai", lambda: (777, racine / "bin" / "llama-server.exe"))
    bonsai._lanceur_integre("Stop")
    assert arrets == [["taskkill", "/PID", "777", "/T", "/F"]]


def _preparer_orphelin(tmp_path, monkeypatch, *, pid_reutilise=False):
    racine = tmp_path / "bonsai"
    racine.mkdir()
    monkeypatch.setattr(config, "BONSAI_RACINE", racine)
    monkeypatch.setattr(config, "DOSSIER_DONNEES", tmp_path / "data")
    monkeypatch.setattr(config, "DOSSIER_JOURNAUX", tmp_path / "data" / "journaux")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "bonsai-8088.pid").write_text("1111", encoding="utf-8")
    arrets: list = []
    monkeypatch.setattr(bonsai.subprocess, "run", lambda argv, **options: arrets.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    monkeypatch.setattr(bonsai.subprocess, "Popen", _FauxPopen)
    _FauxPopen.appels = []
    monkeypatch.setattr(bonsai.time, "sleep", lambda s: None)
    vivants = {1111} if not pid_reutilise else set()
    monkeypatch.setattr(
        bonsai, "_chemin_processus",
        lambda pid: (racine / "bin" / "llama-server.exe") if pid in vivants else (Path("C:/autre/chrome.exe") if pid == 1111 else None),
    )
    return racine, arrets, vivants


def test_lanceur_integre_start_arrete_d_abord_un_orphelin(tmp_path, monkeypatch):
    racine, arrets, vivants = _preparer_orphelin(tmp_path, monkeypatch)
    ecouteurs = [(1111, racine / "bin" / "llama-server.exe"), None]  # l'orphelin tient le port, puis il est libéré
    monkeypatch.setattr(bonsai, "_ecouteur_bonsai", lambda: ecouteurs.pop(0) if len(ecouteurs) > 1 else None)
    bonsai._lanceur_integre("Start")
    assert ["taskkill", "/PID", "1111", "/T", "/F"] in arrets
    assert len(_FauxPopen.appels) == 1
    assert (tmp_path / "data" / "bonsai-8088.pid").read_text(encoding="utf-8") == "4242"


def test_lanceur_integre_start_refuse_un_port_pris_par_un_etranger(tmp_path, monkeypatch):
    racine, arrets, _ = _preparer_orphelin(tmp_path, monkeypatch, pid_reutilise=True)
    monkeypatch.setattr(bonsai, "_ecouteur_bonsai", lambda: (999, Path("C:/autre/ollama.exe")))
    with pytest.raises(bonsai.ErreurMoteur, match="déjà pris"):
        bonsai._lanceur_integre("Start")
    assert _FauxPopen.appels == []
    assert arrets == []


def test_lanceur_integre_stop_ne_tue_pas_un_pid_reattribue(tmp_path, monkeypatch):
    _, arrets, _ = _preparer_orphelin(tmp_path, monkeypatch, pid_reutilise=True)  # le PID 1111 est devenu chrome.exe
    monkeypatch.setattr(bonsai, "_ecouteur_bonsai", lambda: None)
    bonsai._lanceur_integre("Stop")
    assert arrets == []
    assert not (tmp_path / "data" / "bonsai-8088.pid").exists()


def test_lanceur_integre_stop_se_rabat_sur_l_ecouteur_du_port(tmp_path, monkeypatch):
    racine, arrets, _ = _preparer_orphelin(tmp_path, monkeypatch, pid_reutilise=True)
    monkeypatch.setattr(bonsai, "_ecouteur_bonsai", lambda: (5555, racine / "bin" / "llama-server.exe"))
    bonsai._lanceur_integre("Stop")
    assert arrets == [["taskkill", "/PID", "5555", "/T", "/F"]]


def test_lancer_reel_confine_uv_sous_moteurs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_MOTEURS", tmp_path / "moteurs")
    recu: dict = {}

    class FauxPopen:
        returncode = 0

        def __init__(self, argv, **options):
            recu.update(options)

        def communicate(self, timeout=None):
            return "sortie", None

    monkeypatch.setattr(etapes.subprocess, "Popen", FauxPopen)
    resultat = etapes.lancer_reel(["uv", "--version"], tmp_path, threading.Event())
    assert recu["env"]["UV_CACHE_DIR"] == str(tmp_path / "moteurs" / ".uv-cache")
    assert recu["env"]["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / "moteurs" / ".uv-python")
    assert recu["env"]["PYTHONIOENCODING"] == "utf-8" and recu["stderr"] == subprocess.STDOUT  # sortie fusionnée
    assert recu["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
    assert (resultat.returncode, resultat.stdout) == (0, "sortie")


def _processus_vivant(pid: int) -> bool:
    sortie = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False).stdout
    return str(pid) in sortie.split()


def test_lancer_reel_annule_tue_la_commande_et_ses_enfants(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_MOTEURS", tmp_path / "moteurs")
    pid_fichier = tmp_path / "pid.txt"
    code = f"import os, pathlib, time; pathlib.Path(r'{pid_fichier}').write_text(str(os.getpid())); time.sleep(60)"
    annule = threading.Event()

    def annuler_apres_demarrage():
        for _ in range(100):  # le processus a posé son pid : il tourne vraiment
            if pid_fichier.exists() and pid_fichier.read_text():
                break
            time.sleep(0.1)
        time.sleep(0.5)
        annule.set()

    threading.Thread(target=annuler_apres_demarrage, daemon=True).start()
    debut = time.monotonic()
    with pytest.raises(InstallationAnnulee):
        etapes.lancer_reel([sys.executable, "-c", code], tmp_path, annule)
    assert time.monotonic() - debut < 15  # largement avant les 60 s de la commande
    pid = int(pid_fichier.read_text())
    for _ in range(50):
        if not _processus_vivant(pid):
            break
        time.sleep(0.1)
    assert not _processus_vivant(pid)


def test_commande_annulee_deja_posee_ne_lance_rien(tmp_path):
    annule = threading.Event()
    annule.set()
    commandes: list = []
    ctx, _ = _ctx(tmp_path, lancer=lambda argv, cwd, annule: commandes.append(argv), annule=annule)
    with pytest.raises(InstallationAnnulee):
        executer_etape({"type": "commande", "argv": ["x"]}, ctx)
    assert commandes == []


def test_commande_annonce_son_libelle_sans_chemin(tmp_path):
    ctx, messages = _ctx(tmp_path)
    executer_etape({"type": "commande", "libelle": "Installation de Triton", "argv": ["C:/outils/uv.exe", "pip", "install", "triton"]}, ctx)
    executer_etape({"type": "commande", "argv": ["C:/outils/uv.exe", "pip"]}, ctx)
    assert [m[2] for m in messages if m[0] == "commande"] == ["Installation de Triton", "Commande d'installation"]


def test_lanceur_par_defaut_depend_de_l_installation(tmp_path, monkeypatch):
    racine = tmp_path / "bonsai"
    racine.mkdir()
    monkeypatch.setattr(config, "BONSAI_RACINE", racine)
    choix: list = []
    monkeypatch.setattr(bonsai, "_bonsai_ps1", lambda action: choix.append(("ps1", action)))
    monkeypatch.setattr(bonsai, "_lanceur_integre", lambda action: choix.append(("integre", action)))
    bonsai._lanceur_par_defaut("Start")
    (racine / "bonsai.ps1").write_text("", encoding="utf-8")
    bonsai._lanceur_par_defaut("Stop")
    assert choix == [("integre", "Start"), ("ps1", "Stop")]


def test_precharger_maestro_garde_orphelin_et_port_mais_pas_la_marge(tmp_path, monkeypatch):
    from mymaestro.connectors import maestro as connecteur_maestro

    vus: dict = {}

    class Construit(Exception):
        pass

    def fabrique(**options):
        vus.update(options)
        raise Construit

    monkeypatch.setattr(etapes, "ProcessusMaestro", fabrique)
    ctx, _ = _ctx(tmp_path)
    with pytest.raises(Construit):
        etapes._precharger_maestro({"type": "precharger_maestro", "modeles": []}, ctx)
    appels: list[dict] = []
    monkeypatch.setattr(connecteur_maestro, "_prealables_maestro", lambda **options: appels.append(options))
    vus["prealables"]()
    assert appels == [{"marge_memoire": False}]
