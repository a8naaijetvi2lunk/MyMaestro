"""Service d'installation : installation, reprise, annulation, espace disque, moteur externe, routes /api/moteurs, pré-vol
« non installé » et moteurs optionnels. Aucun moteur réel : faux serveur HTTP, faux fichiers, commandes doublées."""

import dataclasses
import hashlib
import io
import subprocess
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from faux_serveur_fichiers import FauxServeurFichiers
from mymaestro import config, modules
from mymaestro.app import creer_app
from mymaestro.connectors.registre import MoteurNonInstalle, prevol_pour, registre
from mymaestro.connectors.simule import ConnecteurSimule, registre_simule
from mymaestro.contrat.modeles import Voie
from mymaestro.core import amorce, depot, empreintes
from mymaestro.core.db import Base
from mymaestro.installation import manifeste as m
from mymaestro.installation import service as s
from mymaestro.installation.manifeste import FichierManifeste, MoteurManifeste
from mymaestro.installation.telechargement import ErreurInstallation
from mymaestro.modules.director_musique import phases
from test_phases import monde  # noqa: F401 - fixture du projet simulé
from test_video import _ffmpeg_disponible, pret  # noqa: F401 - `pret` : fixture du projet mené jusqu'aux images validées

VARIABLES = ("MYMAESTRO_MAESTRO_APP", "MYMAESTRO_DLSS5", "MYMAESTRO_BONSAI", "MYMAESTRO_FFMPEG")


@pytest.fixture(autouse=True)
def environnement_propre(monkeypatch, tmp_path):
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(config, "DOSSIER_MOTEURS", tmp_path / "moteurs")
    monkeypatch.setattr(config, "DOSSIER_JOURNAUX", tmp_path / "journaux")
    monkeypatch.setattr(m, "_ffmpeg_externe", lambda dossier: False)
    monkeypatch.setattr(m, "_claude_repond", lambda: False)
    monkeypatch.setattr(s.ServiceInstallation, "_claude_connecte", staticmethod(lambda: False))
    monkeypatch.setattr(s, "espace_libre_mo", lambda dossier: 10_000_000)
    return tmp_path


def _archive() -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as archive:
        archive.writestr("racine/outil.txt", b"outil")
    return tampon.getvalue()


def _moteur(serveur: FauxServeurFichiers, id_: str = "dlss5", *, etapes=None) -> MoteurManifeste:
    contenu = serveur.contenu
    return MoteurManifeste(
        id=id_, libelle=f"Faux {id_}", requis=False, version="1", espace_mo=1,
        fichiers=(FichierManifeste(nom="outil.zip", url=serveur.url, taille=len(contenu), sha256=hashlib.sha256(contenu).hexdigest(), controles_contenu={}),),
        etapes=tuple(etapes if etapes is not None else [
            {"type": "extraire", "fichier": "outil.zip", "retirer_racine": True, "vers": "."},
            {"type": "commande", "argv": ["faux", "{dossier}"]},
        ]),
        controle=("outil.txt",),
    )


def _service(moteurs, lancer=None) -> tuple[s.ServiceInstallation, list]:
    evenements: list = []
    ok = lambda argv, cwd, annule: subprocess.CompletedProcess(argv, 0, "ok", "")
    return s.ServiceInstallation(evenements.append, {x.id: x for x in moteurs}, lancer=lancer or ok), evenements


def _attendre(service: s.ServiceInstallation) -> None:
    service._fil.join(20)
    assert not service._fil.is_alive()


def _etat(service, id_):
    return next(x for x in service.etat().moteurs if x.id == id_)


def test_installation_de_l_absent_a_l_installe():
    with FauxServeurFichiers(_archive()) as serveur:
        moteur = _moteur(serveur)
        service, evenements = _service([moteur])
        assert _etat(service, "dlss5").etat == "absent"
        service.installer("dlss5")
        _attendre(service)
    assert _etat(service, "dlss5").etat == "installe"
    dossier = m.dossier_moteur("dlss5")
    assert (dossier / "outil.txt").read_bytes() == b"outil"
    assert (dossier / m.FICHIER_VERSION).is_file() and not (dossier / s.FICHIER_ETAPES).exists()
    assert evenements and all(e["type"] == "installation" and e["moteur"] == "dlss5" for e in evenements)
    assert {e["etape"] for e in evenements} >= {"telechargement", "extraire", "commande", "fin"}
    assert evenements[-1]["etat"] == "installe" and evenements[-1]["progression"] == 1.0
    assert service.etat().en_cours is None


def test_deuxieme_installation_simultanee_refusee():
    liberer, commencee = threading.Event(), threading.Event()

    def lent(argv, cwd, annule):
        commencee.set()
        liberer.wait(10)
        return subprocess.CompletedProcess(argv, 0, "", "")

    with FauxServeurFichiers(_archive()) as serveur, FauxServeurFichiers(_archive()) as autre:
        service, _ = _service([_moteur(serveur), _moteur(autre, "bonsai")], lancer=lent)
        service.installer("dlss5")
        assert commencee.wait(10)
        assert service.etat().en_cours == "dlss5" and _etat(service, "dlss5").etat == "en_cours"
        with pytest.raises(ErreurInstallation, match="déjà en cours"):
            service.installer("bonsai")
        liberer.set()
        _attendre(service)
    assert _etat(service, "dlss5").etat == "installe"


def test_echec_puis_reessayer_ne_rejoue_pas_l_etape_faite():
    appels: list = []

    def capricieux(argv, cwd, annule):
        appels.append(argv)
        return subprocess.CompletedProcess(argv, 1 if len(appels) == 1 else 0, "boum" if len(appels) == 1 else "ok", "")

    with FauxServeurFichiers(_archive()) as serveur:
        service, evenements = _service([_moteur(serveur)], lancer=capricieux)
        service.installer("dlss5")
        _attendre(service)
        dossier = m.dossier_moteur("dlss5")
        assert _etat(service, "dlss5").etat == "incomplet" and "boum" in _etat(service, "dlss5").message
        assert evenements[-1]["etat"] == "incomplet"
        assert (dossier / s.FICHIER_ETAPES).is_file() and not (dossier / m.FICHIER_VERSION).exists()
        (dossier / "outil.txt").unlink()  # l'étape 1 (extraction) est faite : si on la rejouait, le fichier reviendrait
        requetes = len(serveur.requetes)
        service.installer("dlss5")
        _attendre(service)
        assert len(serveur.requetes) == requetes  # archive déjà téléchargée et vérifiée
    assert not (dossier / "outil.txt").exists()
    assert len(appels) == 2
    assert (dossier / m.FICHIER_VERSION).is_file()


def test_annulation_laisse_incomplet_sans_fichier_de_version():
    service_ref: list = []

    def annuler(argv, cwd, annule):
        service_ref[0].annuler()
        return subprocess.CompletedProcess(argv, 0, "", "")

    with FauxServeurFichiers(_archive()) as serveur:
        etapes = [{"type": "commande", "argv": ["a"]}, {"type": "commande", "argv": ["b"]}]
        service, evenements = _service([_moteur(serveur, etapes=etapes)], lancer=annuler)
        service_ref.append(service)
        service.installer("dlss5")
        _attendre(service)
    assert _etat(service, "dlss5").etat == "incomplet"
    assert not (m.dossier_moteur("dlss5") / m.FICHIER_VERSION).exists()
    assert "annulée" in evenements[-1]["message"] and evenements[-1]["etat"] == "incomplet"


def test_espace_insuffisant_refuse_avant_tout_telechargement(monkeypatch):
    monkeypatch.setattr(s, "espace_libre_mo", lambda dossier: 0)
    with FauxServeurFichiers(_archive()) as serveur:
        service, evenements = _service([_moteur(serveur)])
        with pytest.raises(ErreurInstallation, match="espace disque"):
            service.installer("dlss5")
        assert serveur.requetes == [] and evenements == [] and service.etat().en_cours is None


def test_moteur_externe_et_deja_installe_refuses(monkeypatch, tmp_path):
    with FauxServeurFichiers(_archive()) as serveur:
        service, _ = _service([_moteur(serveur)])
        monkeypatch.setenv("MYMAESTRO_DLSS5", str(tmp_path / "ailleurs"))
        with pytest.raises(ErreurInstallation, match="externe"):
            service.installer("dlss5")
        monkeypatch.delenv("MYMAESTRO_DLSS5")
        service.installer("dlss5")
        _attendre(service)
        with pytest.raises(ErreurInstallation, match="déjà installé"):
            service.installer("dlss5")
        with pytest.raises(KeyError):
            service.installer("inconnu")


def test_fichier_hors_archive_pose_directement_dans_le_dossier():
    with FauxServeurFichiers(b"modele") as serveur:
        moteur = MoteurManifeste(
            id="bonsai", libelle="Faux", requis=False, version="1", espace_mo=1, etapes=(), controle=("models/m.gguf",),
            fichiers=(FichierManifeste(nom="models/m.gguf", url=serveur.url, taille=6, sha256=hashlib.sha256(b"modele").hexdigest(), controles_contenu={}),),
        )
        service, _ = _service([moteur])
        service.installer("bonsai")
        _attendre(service)
    assert (m.dossier_moteur("bonsai") / "models" / "m.gguf").read_bytes() == b"modele"
    assert _etat(service, "bonsai").etat == "installe"


def test_arreter_annule_et_attend_le_fil():
    liberer = threading.Event()
    commencee = threading.Event()

    def bloque(argv, cwd, annule):
        commencee.set()
        liberer.wait(10)
        return subprocess.CompletedProcess(argv, 0, "", "")

    with FauxServeurFichiers(_archive()) as serveur:
        service, _ = _service([_moteur(serveur)], lancer=bloque)
        service.installer("dlss5")
        assert commencee.wait(10)
        liberer.set()
        service.arreter()
        assert not service._fil.is_alive()


def test_etat_requis_manquants_et_claude_connecte(monkeypatch):
    service = s.ServiceInstallation(lambda e: None)  # manifeste réel
    etat = service.etat()
    assert [x.id for x in etat.moteurs] == ["ffmpeg", "maestro", "dlss5", "bonsai", "claude"]
    assert etat.requis_manquants and etat.mode_demo  # conftest : MYMAESTRO_MOTEURS_REELS=aucun
    assert next(x for x in etat.moteurs if x.id == "claude").connecte is False
    assert next(x for x in etat.moteurs if x.id == "dlss5").connecte is None
    monkeypatch.setenv("MYMAESTRO_MAESTRO_APP", "ailleurs/app")
    monkeypatch.setattr(m, "_ffmpeg_externe", lambda dossier: True)
    assert not s.ServiceInstallation(lambda e: None).etat().requis_manquants  # Maestro et ffmpeg externes


def _sondes_claude(monkeypatch, *, repond=True, connecte=True):
    compte = {"repond": 0, "connecte": 0}

    def repond_():
        compte["repond"] += 1
        return repond

    def connecte_():
        compte["connecte"] += 1
        return connecte

    monkeypatch.setattr(m, "_claude_repond", repond_)
    monkeypatch.setattr(s.ServiceInstallation, "_claude_connecte", staticmethod(connecte_))
    return compte


def test_etat_de_claude_mis_en_cache_30_secondes(monkeypatch):
    compte = _sondes_claude(monkeypatch)
    service = s.ServiceInstallation(lambda e: None)  # manifeste réel
    premier = next(x for x in service.etat().moteurs if x.id == "claude")
    second = next(x for x in service.etat().moteurs if x.id == "claude")
    assert (premier.etat, premier.connecte) == (second.etat, second.connecte) == ("installe", True)
    assert compte == {"repond": 1, "connecte": 1}  # une seule sonde pour deux etat()
    instant = s.time.monotonic()
    monkeypatch.setattr(s.time, "monotonic", lambda: instant + s.DUREE_CACHE_CLAUDE_S + 1)  # le cache expire
    service.etat()
    assert compte == {"repond": 2, "connecte": 2}


def test_cache_de_claude_invalide_apres_installation_et_connexion(monkeypatch):
    compte = _sondes_claude(monkeypatch, connecte=False)
    monkeypatch.setattr(s, "executable_claude", lambda: "C:/claude.exe")
    monkeypatch.setattr(s.subprocess, "Popen", lambda argv, **kw: None)
    service = s.ServiceInstallation(lambda e: None)
    service.etat()
    service.connecter_claude()  # « Se connecter » : la connexion se termine dans le terminal, hors de notre vue
    service.etat()
    service.etat()
    assert compte["repond"] == 2  # le cache a été invalidé par le clic
    assert compte["connecte"] == 3  # tant que Claude n'est pas connecté après un clic, la connexion est resondée
    with FauxServeurFichiers(_archive()) as serveur:
        compte = _sondes_claude(monkeypatch)
        service, _ = _service([_moteur(serveur), _moteur(serveur, "claude")])
        service.etat()
        service.etat()
        assert compte["repond"] == 1  # mis en cache
        service.installer("dlss5")
        _attendre(service)
        service.etat()
        assert compte["repond"] == 2  # fin d'installation : le cache est invalidé


def test_telechargements_supprimes_apres_une_installation_reussie():
    with FauxServeurFichiers(_archive()) as serveur:
        service, _ = _service([_moteur(serveur)])
        service.installer("dlss5")
        _attendre(service)
    dossier = m.dossier_moteur("dlss5")
    assert (dossier / m.FICHIER_VERSION).is_file() and (dossier / "outil.txt").is_file()
    assert not (dossier / ".telechargements").exists()


def test_telechargements_gardes_apres_un_echec():
    with FauxServeurFichiers(_archive()) as serveur:
        service, _ = _service([_moteur(serveur)], lancer=lambda argv, cwd, annule: subprocess.CompletedProcess(argv, 1, "boum", ""))
        service.installer("dlss5")
        _attendre(service)
    assert (m.dossier_moteur("dlss5") / ".telechargements" / "outil.zip").is_file()  # la reprise ne retélécharge pas


def test_manifeste_libelle_chaque_commande():
    libelles = [
        e.get("libelle") for e in m.charger_manifeste()["maestro"].etapes if e.get("type") == "commande"
    ]
    assert libelles == [
        "Création de l'environnement Python",
        "Installation des dépendances de Maestro",
        "Installation de hf-xet et pip",
        "Installation de PyTorch (CUDA 12.8)",
        "Installation de Triton",
        "Installation de SageAttention",
    ]
    for moteur in m.charger_manifeste().values():
        assert all(e.get("libelle") for e in moteur.etapes if e.get("type") == "commande")


def test_connecter_claude_ouvre_un_terminal(monkeypatch):
    lances: list = []
    monkeypatch.setattr(s, "executable_claude", lambda: "C:/claude.exe")
    monkeypatch.setattr(s.subprocess, "Popen", lambda argv, **kw: lances.append(argv))
    s.ServiceInstallation(lambda e: None).connecter_claude()
    assert lances == [["cmd", "/c", "start", "", "cmd", "/k", "C:/claude.exe", "auth", "login"]]
    monkeypatch.setattr(s, "executable_claude", lambda: None)
    with pytest.raises(ErreurInstallation):
        s.ServiceInstallation(lambda e: None).connecter_claude()


# --- routes ---------------------------------------------------------------------------------------------


def test_routes_moteurs():
    liberer, commencee = threading.Event(), threading.Event()

    def lent(argv, cwd, annule):
        commencee.set()
        liberer.wait(10)
        return subprocess.CompletedProcess(argv, 0, "", "")

    with FauxServeurFichiers(_archive()) as serveur, TestClient(creer_app(":memory:")) as client:
        service, _ = _service([_moteur(serveur)], lancer=lent)
        client.app.state.installation = service
        corps = client.get("/api/moteurs").json()
        assert corps["requis_manquants"] is False and [x["id"] for x in corps["moteurs"]] == ["dlss5"] and corps["mode_demo"] is True
        assert client.post("/api/moteurs/inconnu/installer").status_code == 404
        assert client.post("/api/moteurs/dlss5/installer").status_code == 202
        assert commencee.wait(10)
        assert client.post("/api/moteurs/dlss5/installer").status_code == 409  # déjà en cours
        assert client.get("/api/moteurs").json()["en_cours"] == "dlss5"
        assert client.post("/api/moteurs/annuler").status_code == 204
        liberer.set()
        _attendre(service)
        assert client.get("/api/moteurs").json()["en_cours"] is None
        assert client.post("/api/moteurs/dlss5/installer").status_code == 409  # la dernière étape était déjà lancée : installé


def test_route_moteur_externe_et_espace_refuses(monkeypatch, tmp_path):
    with FauxServeurFichiers(_archive()) as serveur, TestClient(creer_app(":memory:")) as client:
        client.app.state.installation = _service([_moteur(serveur)])[0]
        monkeypatch.setattr(s, "espace_libre_mo", lambda dossier: 0)
        assert client.post("/api/moteurs/dlss5/installer").status_code == 409
        monkeypatch.setattr(s, "espace_libre_mo", lambda dossier: 10_000_000)
        monkeypatch.setenv("MYMAESTRO_DLSS5", str(tmp_path / "ailleurs"))
        assert client.post("/api/moteurs/dlss5/installer").status_code == 409


def test_requis_manquants_vrai_si_maestro_ou_ffmpeg_manque(client_reel):
    corps = client_reel.get("/api/moteurs").json()
    assert corps["requis_manquants"] is True
    assert {x["id"]: x["etat"] for x in corps["moteurs"]}["maestro"] == "absent"


@pytest.fixture
def client_reel(monkeypatch):
    with TestClient(creer_app(":memory:")) as client:
        yield client


# --- pré-vol « non installé » et moteurs optionnels -----------------------------------------------------


def _reel(nom, voie=Voie.GPU):
    moteur = ConnecteurSimule(nom, voie, empreintes.DEFAUTS[nom])
    moteur.simule = False
    return moteur


def test_prevol_moteur_simule_hors_mode_demo_leve_non_installe(monkeypatch):
    moteurs = registre_simule(empreintes.DEFAUTS)
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    with pytest.raises(MoteurNonInstalle, match="DLSS 5 Visual Enhancer n'est pas installé : installe-le depuis l'écran Moteurs"):
        prevol_pour(moteurs)("dlss5")
    with pytest.raises(MoteurNonInstalle, match="Maestro"):
        prevol_pour(moteurs)("codex")
    with pytest.raises(MoteurNonInstalle, match="Claude Code"):
        prevol_pour(moteurs)("claude")
    prevol_pour(moteurs)("export")  # jamais bloqué
    prevol_pour({**moteurs, "dlss5": _reel("dlss5")})("dlss5")  # réel : accepté


def test_prevol_en_mode_demo_ne_bloque_rien(monkeypatch):
    monkeypatch.setenv("MYMAESTRO_MOTEURS_REELS", "aucun")
    moteurs = registre_simule(empreintes.DEFAUTS)
    for nom in ("maestro", "codex", "dlss5", "bonsai", "claude"):
        prevol_pour(moteurs)(nom)


@pytest.mark.parametrize(
    ("etat", "variable", "attendu"),
    [
        (m.EtatInstallation.ABSENT, None, "DLSS 5 Visual Enhancer n'est pas installé : installe-le depuis l'écran Moteurs"),
        (m.EtatInstallation.VERSION_DIFFERENTE, None, "DLSS 5 Visual Enhancer : version différente, réinstalle-le depuis l'écran Moteurs"),
        (m.EtatInstallation.INCOMPLET, None, "DLSS 5 Visual Enhancer : installation incomplète, termine-la depuis l'écran Moteurs"),
        (m.EtatInstallation.INSTALLE, None, "DLSS 5 Visual Enhancer vient d'être installé : redémarre MyMaestro pour l'utiliser"),
        (m.EtatInstallation.EXTERNE, None, "DLSS 5 Visual Enhancer vient d'être installé : redémarre MyMaestro pour l'utiliser"),
        (m.EtatInstallation.INSTALLE, "maestro,bonsai", "DLSS 5 Visual Enhancer est exclu par MYMAESTRO_MOTEURS_REELS"),
    ],
)
def test_message_non_installe_suit_l_etat_detecte(monkeypatch, etat, variable, attendu):
    if variable is None:
        monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    else:
        monkeypatch.setenv("MYMAESTRO_MOTEURS_REELS", variable)
    monkeypatch.setattr(m, "detecter", lambda moteur: etat)
    with pytest.raises(MoteurNonInstalle) as info:
        prevol_pour(registre_simule(empreintes.DEFAUTS))("dlss5")
    assert str(info.value) == attendu


def test_creer_app_fige_les_moteurs_simules_autorises(monkeypatch):
    with TestClient(creer_app(":memory:")) as client:  # conftest : mode démo
        assert client.app.state.ordonnanceur.simule_autorise is True
    monkeypatch.setenv("MYMAESTRO_MOTEURS_REELS", "dlss5")  # hors démo : les moteurs simulés ne servent plus
    with TestClient(creer_app(":memory:")) as client:
        assert client.app.state.ordonnanceur.simule_autorise is False
    with TestClient(creer_app(":memory:", connecteurs=registre_simule(empreintes.DEFAUTS))) as client:  # connecteurs injectés
        assert client.app.state.ordonnanceur.simule_autorise is True


def test_registre_sans_variable_suit_l_installation(monkeypatch):
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    monkeypatch.setattr(m, "_claude_repond", lambda: True)
    dossier = config.DOSSIER_MOTEURS / "dlss5"
    manifeste = m.charger_manifeste()["dlss5"]
    for relatif in manifeste.controle:
        (dossier / relatif).parent.mkdir(parents=True, exist_ok=True)
        (dossier / relatif).write_text("x", encoding="utf-8")
    (dossier / m.FICHIER_VERSION).write_text(f'{{"id": "dlss5", "version": "{manifeste.version}"}}', encoding="utf-8")
    assert s.moteurs_reels() == frozenset({"dlss5", "claude"})  # Maestro et Bonsai absents ; codex suit maestro
    connecteurs = registre(empreintes.DEFAUTS, None)
    assert {nom for nom, c in connecteurs.items() if not c.simule} == {"dlss5", "claude"}
    monkeypatch.setenv("MYMAESTRO_MOTEURS_REELS", "aucun")  # la variable l'emporte
    assert all(c.simule for c in registre(empreintes.DEFAUTS, None).values())


@pytest.mark.skipif(not _ffmpeg_disponible(), reason="ffmpeg absent")
def test_lancer_video_avec_dlss5_actif_sans_dlss5_installe_donne_409(pret, monkeypatch):
    contexte, _, projet_id = pret
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    moteurs = registre_simule(empreintes.DEFAUTS)
    moteurs["maestro"] = _reel("maestro")  # seul DLSS5 manque
    contexte.prevol = prevol_pour(moteurs)
    avant = len(contexte.file.lister_projet(projet_id))
    with pytest.raises(phases.ErreurPhase, match="DLSS 5 Visual Enhancer n'est pas installé"):
        phases.lancer_phase(contexte, projet_id, "video")
    assert len(contexte.file.lister_projet(projet_id)) == avant  # refus avant tout enfilage


def test_recette_et_defauts_sur_bonsai_sans_claude(monkeypatch):
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    monkeypatch.setattr(m, "_claude_repond", lambda: False)
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    with base.transaction() as cx:
        [recette] = depot.lister_recettes(cx, "director_musique")
    base.fermer()
    bonsai = {"fournisseur": "bonsai", "modele": "bonsai2-27b-pq2"}
    for cle in ("ecriture", "prompts_image", "prompts_video", "prompts_son"):
        assert {k: recette.valeurs["llm"][cle][k] for k in bonsai} == bonsai
    assert recette.valeurs["llm"]["ecriture"]["effort"] == "high"  # le reste de la recette est conservé
    assert modules.valider_reglages("director_musique", recette.valeurs)["llm"]["ecriture"]["fournisseur"] == "bonsai"
    with TestClient(creer_app(":memory:")) as client:
        llm = client.get("/api/modules/director_musique/defauts").json()["llm"]
        assert all(llm[cle]["fournisseur"] == "bonsai" for cle in ("ecriture", "prompts_image", "prompts_video", "prompts_son"))
    monkeypatch.setattr(m, "_claude_repond", lambda: True)  # Claude installé : défauts inchangés
    with TestClient(creer_app(":memory:")) as client:
        assert client.get("/api/modules/director_musique/defauts").json()["llm"]["ecriture"]["fournisseur"] == "claude"


def test_mode_demo_garde_claude_dans_la_recette():
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)  # MYMAESTRO_MOTEURS_REELS=aucun (conftest) : Claude est simulé, la démo reste telle quelle
    with base.transaction() as cx:
        [recette] = depot.lister_recettes(cx, "director_musique")
    base.fermer()
    assert recette.valeurs["llm"]["ecriture"]["fournisseur"] == "claude"


def _poser_installation(moteur_id):
    """Dossier du moteur dans l'état INSTALLE (fichiers de contrôle et version du manifeste)."""
    dossier = config.DOSSIER_MOTEURS / moteur_id
    manifeste = m.charger_manifeste()[moteur_id]
    for relatif in manifeste.controle:
        (dossier / relatif).parent.mkdir(parents=True, exist_ok=True)
        (dossier / relatif).write_text("x", encoding="utf-8")
    (dossier / m.FICHIER_VERSION).write_text(f'{{"id": "{moteur_id}", "version": "{manifeste.version}"}}', encoding="utf-8")


def _recette_amorcee():
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)
    with base.transaction() as cx:
        [recette] = depot.lister_recettes(cx, "director_musique")
    base.fermer()
    return recette


def test_sans_dlss5_installe_la_passe_est_inactive_par_defaut(monkeypatch):
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    monkeypatch.setattr(m, "_claude_repond", lambda: True)  # seul DLSS5 manque
    assert _recette_amorcee().valeurs["postprod"]["dlss5"]["actif"] is False
    with TestClient(creer_app(":memory:")) as client:
        defauts = client.get("/api/modules/director_musique/defauts").json()
    assert defauts["postprod"]["dlss5"]["actif"] is False and defauts["llm"]["ecriture"]["fournisseur"] == "claude"
    _poser_installation("dlss5")  # DLSS5 installé : défauts inchangés
    assert _recette_amorcee().valeurs["postprod"]["dlss5"]["actif"] is True
    with TestClient(creer_app(":memory:")) as client:
        assert client.get("/api/modules/director_musique/defauts").json()["postprod"]["dlss5"]["actif"] is True


def test_dlss5_externe_ou_mode_demo_garde_la_passe_active(monkeypatch, tmp_path):
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    monkeypatch.setenv("MYMAESTRO_DLSS5", str(tmp_path / "ailleurs"))
    assert _recette_amorcee().valeurs["postprod"]["dlss5"]["actif"] is True
    monkeypatch.delenv("MYMAESTRO_DLSS5")
    monkeypatch.setenv("MYMAESTRO_MOTEURS_REELS", "aucun")  # démo : DLSS5 simulé, la démonstration reste telle quelle
    assert _recette_amorcee().valeurs["postprod"]["dlss5"]["actif"] is True


def test_llm_ecriture_aligne_le_modele_sur_le_fournisseur():
    from mymaestro.modules.director_musique.reglages import LlmEcriture

    assert LlmEcriture(fournisseur="bonsai").modele == config.BONSAI_MODELE
    assert LlmEcriture(fournisseur="bonsai", modele="claude-opus-5-5").modele == config.BONSAI_MODELE
    assert LlmEcriture(fournisseur="claude", modele=config.BONSAI_MODELE).modele == "claude-opus-5-5"
    assert LlmEcriture().modele == "claude-opus-5-5"
    assert LlmEcriture(fournisseur="claude", modele="claude-opus-5-5").modele == "claude-opus-5-5"


def test_llm_etape_aligne_le_modele_sur_le_fournisseur():
    from mymaestro.modules.director_musique.reglages import LlmEtape, ReglagesDirector

    assert LlmEtape(fournisseur="bonsai").modele == config.BONSAI_MODELE
    assert LlmEtape(fournisseur="bonsai", modele="opus").modele == config.BONSAI_MODELE
    assert LlmEtape(fournisseur="claude", modele="bonsai2-27b-pq2").modele == "sonnet"
    assert LlmEtape(fournisseur="claude", modele="opus").modele == "opus"
    # recette réelle du 2026-10-01 : fournisseur passé à Claude, modèle Bonsai resté → la CLI claude refusait le modèle
    llm = {
        "ecriture": {"fournisseur": "claude", "modele": "claude-opus-5-5", "effort": "high", "nombre_concepts": 3},
        "prompts_image": {"fournisseur": "claude", "modele": "sonnet", "reflexion": False},
        "prompts_video": {"fournisseur": "claude", "modele": "bonsai2-27b-pq2", "reflexion": False},
        "prompts_son": {"fournisseur": "claude", "modele": "sonnet", "reflexion": False},
    }
    assert ReglagesDirector.model_validate({"llm": llm}).llm.prompts_video.modele == "sonnet"


def test_prevol_converti_en_erreur_de_phase(monkeypatch):
    """phases._prevol convertit MoteurNonInstalle en ErreurPhase (409), comme MemoireInsuffisante."""
    from mymaestro.core.contexte import Contexte
    from mymaestro.core.file import File

    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    base = Base(":memory:")
    contexte = Contexte(base=base, file=File(base), dossier_projets=config.RACINE, prevol=prevol_pour(registre_simule(empreintes.DEFAUTS)))
    for connecteur in ("claude", "bonsai"):
        with pytest.raises(phases.ErreurPhase, match="n'est pas installé : installe-le depuis l'écran Moteurs"):
            phases._prevol(contexte, connecteur)
    base.fermer()


def _etats_phases(contexte, projet_id):
    with contexte.base.transaction() as cx:
        return depot.lire_projet(cx, projet_id).etat_phases


def test_bonsai_rate_sans_claude_installe_ne_bascule_pas_sur_le_simule(monde, monkeypatch):
    """Hors mode démo, sans Claude : pas de reprise (le répondeur simulé fabriquerait des prompts) ; l'échec reste visible."""
    from mymaestro.contrat.modeles import EtatPhase, StatutJob

    contexte, ordonnanceur, projet_id = monde
    phases.lancer_phase(contexte, projet_id, "analyse")
    ordonnanceur.vider()
    phases.proposer_concepts(contexte, projet_id)
    ordonnanceur.vider()
    phases.retenir_concept(contexte, projet_id, 0)
    phases.ecrire_decoupage(contexte, projet_id)
    ordonnanceur.vider()
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS")
    moteurs = dict(ordonnanceur.connecteurs)
    moteurs["bonsai"] = _reel("bonsai")
    phases.valider_phase(contexte, projet_id, "ecriture")  # prompts enfilés (Bonsai en démo), puis Claude devient « absent »
    contexte.prevol = prevol_pour(moteurs)  # claude reste simulé, hors démo
    ordonnanceur.connecteurs["bonsai"].echecs_restants = 2
    ordonnanceur.vider()
    jobs = [j for j in contexte.file.lister_projet(projet_id) if j.donnees.get("tache") == "prompts.video"]
    assert [(j.connecteur, j.statut) for j in jobs] == [("bonsai", StatutJob.ECHEC)]
    assert _etats_phases(contexte, projet_id)["prompts"] is EtatPhase.ECHEC
    assert "Claude n'est pas installé" in phases.etat_director(contexte, projet_id).erreurs["bascule"]


def test_reinstallation_en_echec_depuis_version_differente_reste_incomplet():
    appels: list = []

    def en_echec(argv, cwd, annule):
        appels.append(argv)
        return subprocess.CompletedProcess(argv, 1, "boum", "")

    with FauxServeurFichiers(_archive()) as serveur:
        moteur = _moteur(serveur)
        dossier = m.dossier_moteur("dlss5")
        dossier.mkdir(parents=True)
        (dossier / m.FICHIER_VERSION).write_text('{"id": "dlss5", "version": "0"}', encoding="utf-8")
        service, evenements = _service([moteur], lancer=en_echec)
        assert _etat(service, "dlss5").etat == "version_differente"
        service.installer("dlss5")
        _attendre(service)
    etat = _etat(service, "dlss5")
    assert etat.etat == "incomplet" and "boum" in etat.message
    assert evenements[-1]["etat"] == "incomplet" and not (dossier / m.FICHIER_VERSION).exists()


def test_installation_reussie_demande_le_redemarrage(monkeypatch):
    with FauxServeurFichiers(_archive()) as serveur:
        service, evenements = _service([_moteur(serveur)])
        assert service.etat().redemarrage_requis is False
        service.installer("dlss5")
        _attendre(service)
    assert service.etat().redemarrage_requis is True
    assert "redémarre MyMaestro" in evenements[-1]["message"]
    # connecteur resté simulé, moteur désormais détecté : le pré-vol le dit au lieu de proposer une installation déjà faite
    monkeypatch.delenv("MYMAESTRO_MOTEURS_REELS", raising=False)
    monkeypatch.setattr(m, "charger_manifeste", lambda: {"dlss5": _moteur(serveur)})
    with pytest.raises(MoteurNonInstalle, match="redémarre MyMaestro"):
        prevol_pour(registre_simule(empreintes.DEFAUTS))("dlss5")


def test_reessayer_compte_ce_que_les_etapes_ont_deja_pose(monkeypatch):
    """Une étape longue (préchargement des modèles) pose des Go puis échoue : la reprise ne redemande que le reste."""
    libre = {"mo": 5}  # juste assez pour le premier essai
    appels: list = []

    def posant_puis_echouant(argv, cwd, annule):
        appels.append(argv)
        if len(appels) == 1:
            (m.dossier_moteur("dlss5") / "modele.bin").write_bytes(b"\0" * (3 * 1024 * 1024))  # 3 Mo posés
            libre["mo"] = 2  # l'espace libre a baissé d'autant
            return subprocess.CompletedProcess(argv, 1, "coupure", "")
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(s, "espace_libre_mo", lambda dossier: libre["mo"])
    with FauxServeurFichiers(_archive()) as serveur:
        moteur = dataclasses.replace(_moteur(serveur), espace_mo=5)  # 5 Mo exigés au total, 3 déjà posés après l'échec
        service, _ = _service([moteur], lancer=posant_puis_echouant)
        service.installer("dlss5")
        _attendre(service)
        assert _etat(service, "dlss5").etat == "incomplet"
        service.installer("dlss5")  # 2 Mo libres suffisent pour les 2 Mo restants
        _attendre(service)
    assert _etat(service, "dlss5").etat == "installe"


def test_creation_du_venv_de_maestro_rejouable():
    """« Réinstaller » rejoue toutes les étapes sur le dossier existant : `uv venv` doit accepter un venv déjà là."""
    etape = next(e for e in m.charger_manifeste()["maestro"].etapes if e.get("type") == "commande" and "venv" in e["argv"])
    assert "--clear" in etape["argv"]
