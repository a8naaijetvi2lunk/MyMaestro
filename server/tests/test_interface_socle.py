import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mymaestro import modules
from mymaestro.app import creer_app
from mymaestro.connectors.simule import registre_simule
from mymaestro.core import empreintes
from mymaestro.fixtures import demo
from mymaestro.modules.director_musique.reglages import ReglagesDirector


@pytest.fixture
def client():
    with TestClient(creer_app(":memory:", connecteurs=registre_simule(empreintes.DEFAUTS))) as c:
        yield c


def test_nombre_de_concepts_borne():
    assert modules.valider_reglages("director_musique", {})["llm"]["ecriture"]["nombre_concepts"] == 3
    with pytest.raises(ValidationError):
        modules.valider_reglages("director_musique", {"llm": {"ecriture": {"nombre_concepts": 6}}})


def test_annotations_d_interface_dans_le_schema():
    schema = ReglagesDirector.model_json_schema()
    effort = schema["$defs"]["LlmEcriture"]["properties"]["effort"]
    assert effort["x-libelles"]["high"] == "Élevé" and effort["x-controle"] == "segments"
    assert schema["properties"]["format"]["x-controle"] == "segments"
    assert schema["x-titre-general"] == "Rendu"
    assert schema["$defs"]["LlmEcriture"]["properties"]["fournisseur"]["x-libelles"]["bonsai"] == "Bonsai 2"  # modifiable : revenir à Claude une fois installé
    assert schema["$defs"]["MoteursPrecoches"]["properties"]["chante"]["x-libelles"]["minimax_h3"] == "MiniMax H3 (FL2VA)"
    assert "autonomie" in schema["$defs"]["Arrets"]["description"]


def test_defauts_du_module(client):
    defauts = client.get("/api/modules/director_musique/defauts").json()
    assert defauts["arrets"]["ecriture"] is True and defauts["format"] == "16:9"
    assert client.get("/api/modules/inconnu/defauts").status_code == 404


def test_infos_de_rendu(client):
    def par_moteur(reponse):
        return {m["moteur"]: m for m in reponse.json()["moteurs"]}

    vertical = client.get("/api/rendu", params={"format": "9:16"})
    assert (vertical.json()["largeur_sortie"], vertical.json()["hauteur_sortie"]) == (1080, 1920)
    h3 = par_moteur(vertical)["minimax_h3"]
    assert (h3["largeur"], h3["hauteur"], h3["images_max"], h3["definition"]) == (544, 960, 243, "544p")
    defaut = par_moteur(client.get("/api/rendu"))
    assert len(defaut) == 3 and all(m["largeur"] == 960 and not m["saute_flashvsr"] for m in defaut.values())
    assert client.get("/api/rendu", params={"format": "4:3"}).status_code == 422


def test_infos_de_rendu_par_definition(client):
    ltx = client.get("/api/rendu", params={"ltx23": "1080p"}).json()["moteurs"]
    ltx23 = next(m for m in ltx if m["moteur"] == "ltx2_22B_distilled_1_1_omninft")
    assert (ltx23["largeur"], ltx23["hauteur"], ltx23["saute_flashvsr"]) == (1920, 1088, True)
    h3 = next(m for m in client.get("/api/rendu", params={"h3": "480p"}).json()["moteurs"] if m["moteur"] == "minimax_h3")
    assert (h3["images_max"], h3["duree_max_s"]) == (345, 14.375)
    assert client.get("/api/rendu", params={"h3": "1080p"}).status_code == 422
    assert client.get("/api/rendu", params={"ltx25": "480p"}).status_code == 422


def test_infos_de_rendu_definitions_permises(client):
    moteurs = {m["moteur"]: m for m in client.get("/api/rendu").json()["moteurs"]}
    assert moteurs["minimax_h3"]["definitions_permises"] == ["480p", "544p"]
    assert moteurs["ltx2_22B_distilled_1_1_omninft"]["definitions_permises"] == ["544p", "720p", "1080p"]


def test_resume_de_projet_porte_sa_recette(client):
    resumes = {r["id"]: r for r in client.get("/api/projets").json()}
    assert resumes[demo.PROJET_DEMO]["recette_id"] == demo.RECETTE_DEMO


def test_fiche_indique_les_projets_qui_l_utilisent(client):
    fiches = {f["id"]: f for f in client.get("/api/bibliotheque").json()}
    assert fiches["fiche-lina"]["projets"] == ["Nuit blanche (démo)"]
    nouvelle = client.post("/api/bibliotheque", json={"type": "style", "nom": "Aube", "description": ""}).json()
    assert nouvelle["projets"] == []
