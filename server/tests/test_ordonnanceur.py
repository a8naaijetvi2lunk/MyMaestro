import time

import pytest

from mymaestro.connectors.base import ErreurMoteur, MoteurInterrompu
from mymaestro.connectors.simule import registre_simule
from mymaestro.contrat.modeles import EtatMoteur, StatutJob, Voie
from mymaestro.core import empreintes
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.core.ordonnanceur import Ordonnanceur


@pytest.fixture
def monde():
    base = Base(":memory:")
    journal: list[str] = []
    connecteurs = registre_simule(empreintes.DEFAUTS, journal=journal)
    ordonnanceur = Ordonnanceur(File(base), connecteurs, vram_totale_mo=12282, vram_bureau_mo=2000)
    yield ordonnanceur, journal
    ordonnanceur.arreter()
    base.fermer()


def test_regime_par_phases_de_bout_en_bout(monde):
    ordonnanceur, journal = monde
    f = ordonnanceur.file
    f.ajouter(voie=Voie.GPU, connecteur="maestro", modele="qwen", phase="images", ordre=30_000)
    f.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video", ordre=40_000)
    f.ajouter(voie=Voie.GPU, connecteur="maestro", modele="minimax_h3", phase="video", ordre=40_001)
    f.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video", ordre=40_002)
    upscale = f.ajouter(voie=Voie.GPU, connecteur="maestro", modele="flashvsr2", phase="postprod", ordre=50_000)
    f.ajouter(voie=Voie.GPU, connecteur="dlss5", modele="dlss5", phase="postprod", ordre=50_001, donnees={"apres": [upscale]})
    f.ajouter(voie=Voie.CLOUD, connecteur="claude", modele="sonnet", phase="prompts", ordre=20_000)
    assert ordonnanceur.vider() == 7
    executes = [
        entree.split(":")[0] + ":" + (f.lire(entree.split(":")[2]).modele or "") for entree in journal if ":executer:" in entree
    ]
    assert executes == [
        "claude:sonnet", "maestro:qwen", "maestro:ltx", "maestro:ltx", "maestro:minimax_h3", "maestro:flashvsr2", "dlss5:dlss5",
    ]
    assert journal.index("maestro:liberer") < journal.index("dlss5:demarrer")
    assert {j.statut for j in f.lister()} == {StatutJob.TERMINE}


def test_echec_puis_reussite_apres_liberation(monde):
    ordonnanceur, journal = monde
    ordonnanceur.connecteurs["maestro"].echecs_restants = 1
    job = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="minimax_h3", phase="video")
    ordonnanceur.vider()
    lu = ordonnanceur.file.lire(job)
    assert (lu.statut, lu.tentatives) == (StatutJob.TERMINE, 2)
    assert journal.count(f"maestro:executer:{job}") == 2
    premier = journal.index(f"maestro:executer:{job}")
    assert journal.index("maestro:liberer") > premier


def test_echec_definitif_la_file_continue(monde):
    ordonnanceur, _ = monde
    ordonnanceur.connecteurs["maestro"].echecs_restants = 5
    perdu = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video", ordre=1)
    suite = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="dlss5", modele="dlss5", phase="video", ordre=2)
    ordonnanceur.vider()
    assert ordonnanceur.file.lire(perdu).statut is StatutJob.ECHEC
    assert ordonnanceur.file.lire(suite).statut is StatutJob.TERMINE


def test_bonsai_puis_maestro_arrete_bonsai(monde):
    ordonnanceur, journal = monde
    ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="bonsai", modele="bonsai2", phase="prompts", ordre=20_000)
    ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="qwen", phase="images", ordre=30_000)
    ordonnanceur.vider()
    assert journal.index("bonsai:arreter") < journal.index("maestro:demarrer")
    assert ordonnanceur.connecteurs["bonsai"].etat is EtatMoteur.ARRETE


def test_bus_diffuse_les_evenements(monde):
    ordonnanceur, _ = monde
    abonnement = ordonnanceur.bus.abonner()
    ordonnanceur.file.ajouter(voie=Voie.CLOUD, connecteur="claude", modele="sonnet")
    ordonnanceur.vider()
    types = []
    while not abonnement.empty():
        types.append(abonnement.get_nowait()["type"])
    assert types[0] == "job" and "progression" in types and types[-1] == "job"
    ordonnanceur.bus.desabonner(abonnement)
    assert ordonnanceur.bus._abonnes == []


def test_fils_de_la_file(monde):
    ordonnanceur, _ = monde
    ordonnanceur.pause_s = 0.01
    jobs = [ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video", ordre=i) for i in range(3)]
    jobs.append(ordonnanceur.file.ajouter(voie=Voie.CLOUD, connecteur="claude", modele="sonnet"))
    ordonnanceur.lancer()
    assert ordonnanceur.en_marche
    limite = time.monotonic() + 10
    while time.monotonic() < limite and any(ordonnanceur.file.lire(j).statut is not StatutJob.TERMINE for j in jobs):
        time.sleep(0.02)
    ordonnanceur.arreter()
    assert not ordonnanceur.en_marche
    assert all(ordonnanceur.file.lire(j).statut is StatutJob.TERMINE for j in jobs)


def test_etat_public(monde):
    ordonnanceur, _ = monde
    ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video")
    ordonnanceur.vider()
    etat = ordonnanceur.etat()
    assert etat.gpu_occupe_par == "maestro"
    assert len(etat.jobs) == 1 and len(etat.connecteurs) == 5


def test_demarrage_refuse_compte_comme_echec_et_la_file_continue(monde):
    ordonnanceur, _ = monde

    def refuser() -> None:
        raise ErreurMoteur("GPU occupé par un Maestro lancé à la main")

    ordonnanceur.connecteurs["dlss5"].demarrer = refuser
    bloque = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="dlss5", modele="dlss5", phase="postprod", ordre=1)
    suite = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video", ordre=2)
    ordonnanceur.vider()
    lu = ordonnanceur.file.lire(bloque)
    assert (lu.statut, lu.tentatives) == (StatutJob.ECHEC, 2)
    assert "occupé" in lu.erreur
    assert ordonnanceur.file.lire(suite).statut is StatutJob.TERMINE


def test_resultat_non_serialisable_est_un_echec_ordinaire(monde):
    ordonnanceur, _ = monde
    ordonnanceur.connecteurs["maestro"].executer = lambda job, progression: {"fichier": object()}
    casse = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video", ordre=1)
    suite = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="dlss5", modele="dlss5", phase="video", ordre=2)
    ordonnanceur.vider()
    assert ordonnanceur.file.lire(casse).statut is StatutJob.ECHEC
    assert ordonnanceur.file.lire(suite).statut is StatutJob.TERMINE


def test_refus_de_demarrer_cloud_compte_comme_tentative(monde):
    ordonnanceur, _ = monde

    def refuser():
        raise ErreurMoteur("démarrage refusé")

    ordonnanceur.connecteurs["claude"].demarrer = refuser
    cloud = ordonnanceur.file.ajouter(voie=Voie.CLOUD, connecteur="claude", modele="sonnet", phase="prompts", ordre=1)
    gpu = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="qwen", phase="images", ordre=2)
    ordonnanceur.vider()
    lu = ordonnanceur.file.lire(cloud)
    assert (lu.statut, lu.tentatives) == (StatutJob.ECHEC, 2)
    assert ordonnanceur.file.lire(gpu).statut is StatutJob.TERMINE


def _job_gpu(ordonnanceur):
    return ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="ltx", phase="video", ordre=1)


def test_moteur_interrompu_remet_en_file_sans_tentative_perdue(monde):
    ordonnanceur, journal = monde
    job = _job_gpu(ordonnanceur)

    def interrompre(j, progression):
        raise MoteurInterrompu("Maestro arrêté par MyMaestro pendant le rendu")

    ordonnanceur.connecteurs["maestro"].executer = interrompre
    ordonnanceur._executer(ordonnanceur.file.lire(job), ())
    lu = ordonnanceur.file.lire(job)
    assert (lu.statut, lu.tentatives) == (StatutJob.EN_FILE, 0)
    assert "arrêté par MyMaestro" in lu.erreur
    assert "maestro:liberer" not in journal  # l'arrêt n'est pas une panne à réparer


def test_exception_ordinaire_pendant_la_fermeture_est_une_interruption(monde):
    ordonnanceur, journal = monde
    job = _job_gpu(ordonnanceur)

    def casser(j, progression):
        ordonnanceur._arret.set()  # la fermeture de MyMaestro arrive pendant le rendu
        raise RuntimeError("connexion coupée")

    ordonnanceur.connecteurs["maestro"].executer = casser
    ordonnanceur._executer(ordonnanceur.file.lire(job), ())
    lu = ordonnanceur.file.lire(job)
    assert (lu.statut, lu.tentatives) == (StatutJob.EN_FILE, 0)
    assert "maestro:liberer" not in journal


def test_arret_pose_avant_l_execution_ne_demarre_rien(monde):
    ordonnanceur, journal = monde
    job = _job_gpu(ordonnanceur)
    ordonnanceur._arret.set()
    assert ordonnanceur._executer(ordonnanceur.file.lire(job), ()) is None
    lu = ordonnanceur.file.lire(job)
    assert (lu.statut, lu.tentatives) == (StatutJob.EN_FILE, 0)
    assert not any(":executer:" in e or ":demarrer" in e for e in journal)


def test_fermeture_ne_reserve_plus_aucun_job_de_la_liste_deja_lue(monde):
    ordonnanceur, _ = monde
    jobs = [ordonnanceur.file.ajouter(voie=Voie.CLOUD, connecteur="claude", modele="sonnet", phase="prompts", ordre=i) for i in range(3)]
    publies: list[dict] = []
    ordonnanceur._publier = lambda type_, **donnees: publies.append({"type": type_, **donnees})
    ordonnanceur._arret.set()
    assert ordonnanceur.etape_cloud() is None and ordonnanceur.etape_gpu() is None
    for job in jobs:
        lu = ordonnanceur.file.lire(job)
        assert (lu.statut, lu.tentatives, lu.erreur) == (StatutJob.EN_FILE, 0, None)
    assert publies == []


def _ordonnanceur_simule(simule_autorise: bool):
    base = Base(":memory:")
    journal: list[str] = []
    ordonnanceur = Ordonnanceur(
        File(base), registre_simule(empreintes.DEFAUTS, journal=journal), vram_totale_mo=12282, vram_bureau_mo=2000,
        simule_autorise=simule_autorise,
    )
    return base, ordonnanceur, journal


def test_moteur_simule_hors_mode_demo_echoue_sans_executer(monkeypatch):
    from mymaestro.installation import manifeste as m

    monkeypatch.setattr(m, "detecter", lambda moteur: m.EtatInstallation.ABSENT)
    base, ordonnanceur, journal = _ordonnanceur_simule(False)
    evenements = ordonnanceur.bus.abonner()
    gpu = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="qwen", phase="images")
    cloud = ordonnanceur.file.ajouter(voie=Voie.CLOUD, connecteur="claude", modele="sonnet", phase="prompts")
    ordonnanceur.vider()
    for job_id in (gpu, cloud):
        lu = ordonnanceur.file.lire(job_id)
        assert lu.statut is StatutJob.ECHEC and "n'est pas installé : installe-le depuis l'écran Moteurs" in lu.erreur
        assert lu.tentatives == 0  # aucune tentative consommée : « Relancer » repart à neuf
    assert journal == []  # ni préparation (démarrer) ni exécution
    publies = []
    while not evenements.empty():
        publies.append(evenements.get_nowait())
    assert any(e["type"] == "job" and e["id"] == gpu and e["statut"] == "echec" for e in publies)
    ordonnanceur.arreter()
    base.fermer()


def test_moteur_simule_autorise_s_execute_normalement():
    base, ordonnanceur, journal = _ordonnanceur_simule(True)
    job = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="qwen", phase="images")
    ordonnanceur.vider()
    assert ordonnanceur.file.lire(job).statut is StatutJob.TERMINE
    assert any(":executer:" in entree for entree in journal)
    ordonnanceur.arreter()
    base.fermer()


def test_relance_manuelle_sur_moteur_simule_hors_demo_echoue_encore(monkeypatch):
    from mymaestro.installation import manifeste as m

    monkeypatch.setattr(m, "detecter", lambda moteur: m.EtatInstallation.ABSENT)
    base, ordonnanceur, journal = _ordonnanceur_simule(False)
    job = ordonnanceur.file.ajouter(voie=Voie.GPU, connecteur="maestro", modele="qwen", phase="images")
    ordonnanceur.vider()
    assert ordonnanceur.file.relancer(job)
    ordonnanceur.vider()
    assert ordonnanceur.file.lire(job).statut is StatutJob.ECHEC and journal == []
    ordonnanceur.arreter()
    base.fermer()
