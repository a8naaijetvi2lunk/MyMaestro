from mymaestro.connectors.base import Empreinte
from mymaestro.connectors.simule import ConnecteurSimule
from mymaestro.contrat.modeles import EtatMoteur, Regime, StatutJob, Voie
from mymaestro.core import arbitre
from mymaestro.core.file import JobFile


def _job(id_, connecteur, modele=None, phase="video", ordre=0, regime=Regime.PHASES, voie=Voie.GPU):
    return JobFile(
        id=id_, voie=voie, connecteur=connecteur, modele=modele, projet_id=None, phase=phase, ordre=ordre, regime=regime,
        donnees={}, statut=StatutJob.EN_FILE, tentatives=0, erreur=None, resultat=None, libelle="", progression=0.0,
    )


def _registre():
    return {
        "maestro": ConnecteurSimule("maestro", Voie.GPU, Empreinte(11000, 1500)),
        "dlss5": ConnecteurSimule("dlss5", Voie.GPU, Empreinte(6000, 0)),
        "bonsai": ConnecteurSimule("bonsai", Voie.GPU, Empreinte(9440, 9440)),
        "claude": ConnecteurSimule("claude", Voie.CLOUD, Empreinte(0, 0)),
    }


def test_la_phase_de_tete_passe_avant_le_moteur_charge():
    jobs = [
        _job("img", "maestro", "qwen", phase="images", ordre=30_001),
        _job("vid", "maestro", "minimax_h3", phase="video", ordre=40_000),
    ]
    assert arbitre.ordonner(jobs, "maestro", "minimax_h3").id == "img"


def test_meme_modele_regroupe_dans_la_phase():
    jobs = [_job("h3-a", "maestro", "minimax_h3", ordre=1), _job("ltx", "maestro", "ltx", ordre=2), _job("h3-b", "maestro", "minimax_h3", ordre=3)]
    assert arbitre.ordonner(jobs, "maestro", "minimax_h3").id == "h3-a"
    assert arbitre.ordonner(jobs[1:], "maestro", "minimax_h3").id == "h3-b"
    assert arbitre.ordonner([jobs[1]], "maestro", "minimax_h3").id == "ltx"


def test_liberer_ou_arreter_selon_la_vram():
    registre = _registre()
    registre["maestro"].etat = EtatMoteur.CHARGE
    assert arbitre.preparer(_job("d", "dlss5"), registre, 12282, 2000) == (
        arbitre.Preparation("maestro", "liberer"),
        arbitre.Preparation("dlss5", "demarrer"),
    )
    assert arbitre.preparer(_job("b", "bonsai"), registre, 12282, 2000) == (
        arbitre.Preparation("maestro", "arreter"),
        arbitre.Preparation("bonsai", "demarrer"),
    )


def test_bonsai_resident_arrete_avant_maestro():
    registre = _registre()
    registre["bonsai"].etat = EtatMoteur.DEMARRE
    decision = arbitre.choisir([_job("m", "maestro", "minimax_h3")], registre, None, 12282, 2000)
    assert decision.preparations == (arbitre.Preparation("bonsai", "arreter"), arbitre.Preparation("maestro", "demarrer"))


def test_voie_cloud_sans_preparation_gpu():
    registre = _registre()
    registre["maestro"].etat = EtatMoteur.CHARGE
    assert arbitre.preparer(_job("c", "claude", voie=Voie.CLOUD), registre, 12282, 2000) == (
        arbitre.Preparation("claude", "demarrer"),
    )


def test_moteur_a_residuel_nul_est_libere_pas_arrete():
    registre = _registre()
    registre["dlss5"].etat = EtatMoteur.CHARGE
    assert arbitre.preparer(_job("m", "maestro", "minimax_h3"), registre, 12282, 2000) == (
        arbitre.Preparation("dlss5", "liberer"),
        arbitre.Preparation("maestro", "demarrer"),
    )
