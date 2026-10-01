import pytest
from pydantic import ValidationError

from mymaestro import modules
from mymaestro.fixtures import demo
from mymaestro.modules.director_musique.manifeste import ORDRE_PHASES, ordre_job


def test_recette_de_demo_valide_et_completee():
    valeurs = modules.valider_reglages("director_musique", demo.recettes_demo()[0].valeurs)
    assert valeurs["llm"]["prompts_video"] == {"fournisseur": "bonsai", "modele": "bonsai2-27b-pq2", "reflexion": False}
    assert valeurs["postprod"]["dlss5"]["ton_local"] == 1.0


def test_reglages_invalides_refuses():
    with pytest.raises(ValidationError):
        modules.valider_reglages("director_musique", {"format": "4:3"})
    with pytest.raises(ValidationError):
        modules.valider_reglages("director_musique", {"inconnu": True})
    with pytest.raises(KeyError):
        modules.valider_reglages("module_inconnu", {})


def test_schema_de_recette_porte_les_titres_francais():
    schema = modules.manifestes()[0].schema_reglages
    assert schema["$defs"]["Arrets"]["properties"]["analyse"]["title"] == "Après l'analyse"
    assert schema["properties"]["llm"]["title"] == "Modèles de langage"


def test_phases_du_director_dans_l_ordre():
    assert ORDRE_PHASES == ["analyse", "ecriture", "prompts", "images", "video", "postprod", "export"]
    assert ordre_job("images", 3) < ordre_job("video", 0) < ordre_job("postprod", 0)


def test_reglages_par_defaut_complets():
    valeurs = modules.valider_reglages("director_musique", {})
    assert valeurs["arrets"] == {"analyse": False, "ecriture": True, "prompts": True, "images": True}
    assert valeurs["moteurs_precoches"]["chante"] == "ltx2_22B_distilled_1_1_omninft"  # défaut du projet : LTX-2.3 + OmniNFT
