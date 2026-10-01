import pytest

from mymaestro.contrat.modeles import Regime, StatutJob, Voie
from mymaestro.core.db import Base
from mymaestro.core.file import File


@pytest.fixture
def file():
    base = Base(":memory:")
    yield File(base)
    base.fermer()


def test_ajout_et_ordre(file):
    b = file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=20, libelle="B")
    a = file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=10, libelle="A")
    c = file.ajouter(voie=Voie.CLOUD, connecteur="claude", ordre=5)
    assert [j.id for j in file.eligibles(Voie.GPU)] == [a, b]
    assert [j.id for j in file.eligibles(Voie.CLOUD)] == [c]
    assert [j.id for j in file.lister()] == [c, a, b]
    assert file.lire(a).public().libelle == "A"


def test_un_job_ne_demarre_qu_une_fois(file):
    job = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    assert file.demarrer(job) is True
    assert file.demarrer(job) is False
    assert file.lire(job).tentatives == 1


def test_nouvelle_tentative_puis_echec(file):
    job = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    file.demarrer(job)
    assert file.echouer(job, "OOM") is StatutJob.EN_FILE
    file.demarrer(job)
    assert file.echouer(job, "OOM encore") is StatutJob.ECHEC
    lu = file.lire(job)
    assert (lu.statut, lu.tentatives, lu.erreur) == (StatutJob.ECHEC, 2, "OOM encore")


def test_reprise_apres_crash(file):
    premier = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    second = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    file.demarrer(premier)
    file.demarrer(second)
    file.echouer(second, "x")
    file.demarrer(second)  # 2e tentative en cours au moment du crash
    assert file.reprendre_apres_crash() == 2
    assert file.lire(premier).statut is StatutJob.EN_FILE
    assert file.lire(second).statut is StatutJob.ECHEC


def test_prerequis(file):
    source = file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=1)
    suite = file.ajouter(voie=Voie.GPU, connecteur="dlss5", ordre=2, donnees={"apres": [source]})
    assert [j.id for j in file.eligibles(Voie.GPU)] == [source]
    file.demarrer(source)
    file.terminer(source, {"fichier": "a.mp4"})
    assert [j.id for j in file.eligibles(Voie.GPU)] == [suite]


def test_prerequis_en_echec_annule_la_suite(file):
    source = file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=1)
    suite = file.ajouter(voie=Voie.GPU, connecteur="dlss5", ordre=2, donnees={"apres": [source]})
    orphelin = file.ajouter(voie=Voie.GPU, connecteur="dlss5", ordre=3, donnees={"apres": ["job-inexistant"]})
    for _ in range(2):
        file.demarrer(source)
        file.echouer(source, "panne")
    assert file.eligibles(Voie.GPU) == []
    assert file.lire(suite).statut is StatutJob.ANNULE
    assert file.lire(orphelin).statut is StatutJob.ANNULE


def test_annulation_et_progression(file):
    job = file.ajouter(voie=Voie.GPU, connecteur="maestro", regime=Regime.CARTE)
    assert file.annuler(job) is True
    assert file.annuler(job) is False
    autre = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    file.demarrer(autre)
    file.progresser(autre, 1.7)
    assert file.lire(autre).progression == 1.0
    file.terminer(autre, None)
    assert file.lire(autre).statut is StatutJob.TERMINE


def test_lister_garde_les_jobs_actifs_malgre_l_historique(file):
    for i in range(200):
        j = file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=40_000 + i)
        with file.base.transaction() as cx:
            cx.execute("UPDATE jobs SET statut = 'termine' WHERE id = ?", (j,))
    a = file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=1_000_000)
    b = file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=40_000)
    ids = [j.id for j in file.lister()]
    assert a in ids and b in ids
    assert len(ids) == 200


def test_lister_garde_la_tete_de_file_au_dela_de_la_limite(file):
    ids = [file.ajouter(voie=Voie.GPU, connecteur="maestro", ordre=i) for i in range(250)]
    assert file.demarrer(ids[100]) is True
    listes = [j.id for j in file.lister()]
    assert len(listes) == 200
    assert ids[100] in listes
    assert set(ids[:199]) <= set(listes)
