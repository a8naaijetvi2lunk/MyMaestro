import pytest

from mymaestro import modules
from mymaestro.contrat.modeles import StatutJob, Voie
from mymaestro.core.contexte import Contexte
from mymaestro.core.db import Base
from mymaestro.core.file import File


@pytest.fixture
def file():
    base = Base(":memory:")
    file = File(base)
    yield file
    base.fermer()


def test_rappels_sur_chaque_etat_final(file):
    vus: list[tuple[str, StatutJob]] = []
    file.rappels.append(lambda job: vus.append((job.id, job.statut)))
    fini = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    rate = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    annule = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    orphelin = file.ajouter(voie=Voie.GPU, connecteur="maestro", donnees={"apres": ["inexistant"]})
    file.demarrer(fini)
    file.terminer(fini, {"ok": True})
    file.demarrer(rate)
    file.echouer(rate, "une")
    assert (rate, StatutJob.ECHEC) not in vus  # nouvelle tentative : pas encore final
    file.demarrer(rate)
    file.echouer(rate, "deux")
    file.annuler(annule)
    file.eligibles(Voie.GPU)
    assert vus == [(fini, StatutJob.TERMINE), (rate, StatutJob.ECHEC), (annule, StatutJob.ANNULE), (orphelin, StatutJob.ANNULE)]


def test_rappel_apres_crash(file):
    vus: list[str] = []
    file.rappels.append(lambda job: vus.append(job.id))
    job = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    for _ in range(2):
        file.demarrer(job)
        if file.lire(job).tentatives < 2:
            file.echouer(job, "x")
    file.reprendre_apres_crash()
    assert vus == [job]


def test_un_rappel_en_erreur_n_arrete_rien(file):
    vus: list[str] = []

    def casse(job):
        raise RuntimeError("rappel cassé")

    file.rappels += [casse, lambda job: vus.append(job.id)]
    job = file.ajouter(voie=Voie.CLOUD, connecteur="claude")
    file.demarrer(job)
    file.terminer(job, None)
    assert vus == [job]


def test_jobs_d_un_lancement_et_d_un_projet(file):
    a = file.ajouter(voie=Voie.GPU, connecteur="maestro", donnees={"lancement": "L1"})
    file.ajouter(voie=Voie.GPU, connecteur="maestro", donnees={"lancement": "L2"})
    assert [j.id for j in file.lister_lancement("L1")] == [a]
    assert file.lister_projet("aucun") == []


def test_aiguillage_par_module(file, tmp_path, monkeypatch):
    vus: list[str] = []
    monkeypatch.setitem(modules.APRES_JOB, "module_test", lambda contexte, job: vus.append(job.id))
    contexte = Contexte(base=file.base, file=file, dossier_projets=tmp_path)
    file.rappels.append(lambda job: modules.apres_job(contexte, job))
    avec = file.ajouter(voie=Voie.CLOUD, connecteur="claude", donnees={"module": "module_test"})
    sans = file.ajouter(voie=Voie.CLOUD, connecteur="claude")
    for job in (avec, sans):
        file.demarrer(job)
        file.terminer(job, None)
    assert vus == [avec]


def test_fin_de_lancement_vue_une_seule_fois_avec_deux_fils_cloud():
    import time

    from mymaestro.connectors.simule import registre_simule
    from mymaestro.core import empreintes
    from mymaestro.core.ordonnanceur import Ordonnanceur

    base = Base(":memory:")
    file = File(base)
    ordonnanceur = Ordonnanceur(file, registre_simule(empreintes.DEFAUTS, duree_s=0.05), fils_cloud=2, pause_s=0.01)
    finis: list[int] = []

    def rappel(job):
        if job.donnees.get("lancement") and all(
            j.statut in (StatutJob.TERMINE, StatutJob.ECHEC, StatutJob.ANNULE) for j in file.lister_lancement("L")
        ):
            finis.append(1)

    file.rappels.append(rappel)
    try:
        for _ in range(2):
            file.ajouter(voie=Voie.CLOUD, connecteur="claude", modele="sonnet", donnees={"lancement": "L"})
        ordonnanceur.lancer()
        fin = time.monotonic() + 10
        while time.monotonic() < fin and not all(j.statut is StatutJob.TERMINE for j in file.lister_lancement("L")):
            time.sleep(0.02)
        time.sleep(0.3)
        assert len(finis) == 1
    finally:
        ordonnanceur.arreter()
        base.fermer()
