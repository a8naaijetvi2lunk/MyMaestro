import json

import pytest

from mymaestro.connectors.base import Empreinte, ErreurMoteur
from mymaestro.connectors.simule import ConnecteurSimule, registre_simule
from mymaestro.contrat.modeles import EtatMoteur, Voie
from mymaestro.core import empreintes


class _JobFactice:
    id = "job-1"


def test_connecteur_simule_trace_ses_actions():
    journal: list[str] = []
    connecteur = ConnecteurSimule("maestro", Voie.GPU, Empreinte(11000, 1500), journal=journal)
    assert connecteur.etat is EtatMoteur.ARRETE
    connecteur.demarrer()
    valeurs: list[float] = []
    assert connecteur.executer(_JobFactice(), valeurs.append) == {"fichier": "simule/job-1.mp4"}
    assert connecteur.etat is EtatMoteur.CHARGE
    connecteur.liberer()
    assert connecteur.etat is EtatMoteur.DEMARRE
    connecteur.arreter()
    assert journal == ["maestro:demarrer", "maestro:executer:job-1", "maestro:liberer", "maestro:arreter"]
    assert valeurs == [0.5, 1.0]
    assert connecteur.etat_public().etat is EtatMoteur.ARRETE


def test_connecteur_simule_echoue_le_nombre_de_fois_demande():
    connecteur = ConnecteurSimule("dlss5", Voie.GPU, Empreinte(6000, 0), echecs=1)
    connecteur.demarrer()
    with pytest.raises(ErreurMoteur):
        connecteur.executer(_JobFactice(), lambda v: None)
    assert connecteur.executer(_JobFactice(), lambda v: None)["fichier"].endswith(".mp4")


def test_empreintes_par_defaut_sans_mesures(tmp_path):
    assert empreintes.charger(tmp_path / "absent.json") == empreintes.DEFAUTS


def test_empreintes_lues_dans_les_mesures(tmp_path):
    fichier = tmp_path / "tache0.json"
    fichier.write_text(
        json.dumps(
            {
                "bonsai": {"vram_avant_mo": 2211, "demarrage": {"pret": True, "vram_chargee_mo": 11651}},
                "maestro": {"vram_avant_mo": 1100, "h3_segment_124": {"statut": "exception", "vram_pic_mo": 12000}},
                "dlss5": {
                    "vram_avant_mo": 1000,
                    "neural_rendering": {"code_retour": 0, "vram_pic_mo": 5000},
                    "interpolation": {"code_retour": 1, "vram_pic_mo": 9000},
                },
            }
        ),
        encoding="utf-8",
    )
    lues = empreintes.charger(fichier)
    assert lues["bonsai"] == Empreinte(9440, 9440)
    assert lues["maestro"] == empreintes.DEFAUTS["maestro"]
    assert lues["dlss5"] == Empreinte(4000, 0)


def test_bonsai_demarrage_echoue_garde_le_defaut(tmp_path):
    fichier = tmp_path / "tache0.json"
    fichier.write_text(
        json.dumps({"bonsai": {"vram_avant_mo": 2211, "demarrage": {"code_retour": 1, "pret": False, "vram_chargee_mo": 2400}}}),
        encoding="utf-8",
    )
    assert empreintes.charger(fichier)["bonsai"] == empreintes.DEFAUTS["bonsai"]


def test_registre_simule_couvre_les_cinq_moteurs():
    registre = registre_simule(empreintes.DEFAUTS)
    assert {nom: c.voie for nom, c in registre.items()} == {
        "maestro": Voie.GPU, "dlss5": Voie.GPU, "bonsai": Voie.GPU, "claude": Voie.CLOUD, "codex": Voie.CLOUD,
    }
