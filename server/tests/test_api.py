import asyncio

import pytest
from fastapi.testclient import TestClient

from mymaestro import modules
from mymaestro.api.evenements import flux
from mymaestro.app import creer_app
from mymaestro.connectors.simule import registre_simule
from mymaestro.contrat.modeles import EtatMoteur, StatutJob, Voie
from mymaestro.core import empreintes
from mymaestro.core.ordonnanceur import Bus
from mymaestro.fixtures import demo


@pytest.fixture
def client(tmp_path):
    projets = tmp_path / "projets"
    app = creer_app(
        ":memory:", dossier_medias=tmp_path / "medias", dossier_projets=projets,
        connecteurs=registre_simule(empreintes.DEFAUTS, repondeur=modules.repondeur_simule(projets)),
    )
    with TestClient(app) as c:
        yield c


def test_modules_exposent_le_schema_de_recette(client):
    manifestes = client.get("/api/modules").json()
    assert [m["id"] for m in manifestes] == ["director_musique"]
    assert manifestes[0]["schema_reglages"]["properties"]["arrets"]["title"] == "Arrêts pour validation"


def test_recette_h3_1080p_refusee_sur_la_carte_de_reference_acceptee_sur_32_go(client, monkeypatch):
    from mymaestro.outils import gpu

    corps = {"module": "director_musique", "nom": "H3 1080p", "valeurs": {"rendu": {"h3": "1080p"}}}
    existante = client.get("/api/recettes", params={"module": "director_musique"}).json()[0]["id"]
    refus = client.put(f"/api/recettes/{existante}", json=corps)
    assert refus.status_code == 422 and "32 Go" in str(refus.json()["detail"])
    assert client.post("/api/recettes", json=corps).status_code == 422
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("NVIDIA GeForce RTX 5090", 32768, "nvidia-smi"))
    assert client.put(f"/api/recettes/{existante}", json=corps).status_code == 200
    assert client.post("/api/recettes", json=corps).status_code == 201
    assert client.get("/api/recettes", params={"module": "director_musique"}).status_code == 200  # la lecture ne lève jamais


def test_recette_creee_modifiee_et_refusee(client):
    creee = client.post("/api/recettes", json={"module": "director_musique", "nom": "Reel vertical", "valeurs": {"format": "9:16"}})
    assert creee.status_code == 201
    recette = creee.json()
    assert recette["valeurs"]["format"] == "9:16" and recette["valeurs"]["arrets"]["prompts"] is True
    modifiee = client.put(f"/api/recettes/{recette['id']}", json={"module": "director_musique", "nom": "Reel 2", "valeurs": {}})
    assert modifiee.json()["nom"] == "Reel 2"
    assert client.put("/api/recettes/inconnue", json={"module": "director_musique", "nom": "x", "valeurs": {}}).status_code == 404
    assert client.post("/api/recettes", json={"module": "director_musique", "nom": "x", "valeurs": {"format": "4:3"}}).status_code == 422
    assert client.post("/api/recettes", json={"module": "inconnu", "nom": "x", "valeurs": {}}).status_code == 422
    assert len(client.get("/api/recettes", params={"module": "director_musique"}).json()) == 2


def test_bibliotheque_crud(client):
    creee = client.post("/api/bibliotheque", json={"type": "decor", "nom": "Cuisine de nuit", "description": "Hotte allumée"})
    assert creee.status_code == 201
    fiche_id = creee.json()["id"]
    assert client.put(f"/api/bibliotheque/{fiche_id}", json={"type": "decor", "nom": "Cuisine", "description": ""}).json()["nom"] == "Cuisine"
    assert client.delete(f"/api/bibliotheque/{fiche_id}").status_code == 204
    assert client.delete(f"/api/bibliotheque/{fiche_id}").status_code == 404
    assert len(client.get("/api/bibliotheque").json()) == 3


def test_actions_programmees_puis_lancees(client):
    url = f"/api/projets/{demo.PROJET_DEMO}/actions"
    assert client.post(url, json={"type": "passe_dlss5", "plan_id": "plan-02", "reglages": {"intensite": 0.8}}).status_code == 201
    changement = {"type": "changer_moteur", "plan_id": "plan-06", "reglages": {"moteur": "ltx2_22B_distilled_1_1_omninft"}}
    assert client.post(url, json=changement).status_code == 201
    assert client.post(url, json={"type": "changer_moteur", "plan_id": "plan-06", "reglages": {}}).status_code == 422
    assert client.post(url, json={"type": "refaire", "plan_id": "plan-99"}).status_code == 422
    assert client.post("/api/projets/inconnu/actions", json={"type": "refaire"}).status_code == 404
    assert len(client.get(url).json()) == 2
    lancement = client.post(f"{url}/lancer").json()
    assert len(lancement["jobs"]) == 4  # changement de moteur : rendu, FlashVSR, DLSS5 ; passe DLSS5 : un job
    assert client.get(url).json() == []
    file = client.get("/api/file").json()
    par_libelle = {j["libelle"]: j for j in file["jobs"]}
    assert par_libelle["Plan 3 — DLSS5"]["connecteur"] == "dlss5"
    assert par_libelle["Plan 7 — rendu LTX-2.3"]["regime"] == "carte"
    assert len(file["connecteurs"]) == 6 and file["en_marche"] is False


def test_file_executee_par_l_ordonnanceur(client):
    client.post(f"/api/projets/{demo.PROJET_DEMO}/actions", json={"type": "bruitage", "plan_id": "plan-00"})
    job_id = client.post(f"/api/projets/{demo.PROJET_DEMO}/actions/lancer").json()["jobs"][0]
    ordonnanceur = client.app.state.ordonnanceur
    assert ordonnanceur.vider() == 1
    assert ordonnanceur.file.lire(job_id).statut is StatutJob.TERMINE
    assert client.get("/api/file").json()["gpu_occupe_par"] == "maestro"
    clips = client.get(f"/api/projets/{demo.PROJET_DEMO}/timeline").json()["clips"]
    assert any((c["fichier_audio"] or "").startswith("sons/bruitage-") for c in clips)


def test_flux_d_evenements():
    bus = Bus()

    async def lire():
        generateur = flux(bus, delai_s=0.05, limite=2)
        premier = await generateur.__anext__()
        bus.publier({"type": "job", "id": "j1"})
        second = await generateur.__anext__()
        await generateur.aclose()
        return premier, second

    premier, second = asyncio.run(lire())
    assert premier.event == "connecte"
    assert (second.event, second.data["id"]) == ("job", "j1")
    assert bus._abonnes == []


def test_action_reglages_et_clip_invalides_refuses(client):
    url = f"/api/projets/{demo.PROJET_DEMO}/actions"
    assert client.post(url, json={"type": "refaire", "plan_id": "plan-02", "reglages": {"moteur": ["x"]}}).status_code == 422
    assert client.post(url, json={"type": "refaire", "plan_id": "plan-02", "reglages": {"moteur": {"a": 1}}}).status_code == 422
    assert client.post(url, json={"type": "refaire", "plan_id": "plan-02", "reglages": {"moteur": "inconnu"}}).status_code == 422
    assert client.post(url, json={"type": "changer_moteur", "plan_id": "plan-02", "reglages": {"moteur": ["x"]}}).status_code == 422
    assert client.post(url, json={"type": "refaire", "clip_id": "clip-inexistant"}).status_code == 422
    assert client.post(url, json={"type": "refaire", "plan_id": "plan-02"}).status_code == 201
    assert len(client.get(url).json()) == 1


def test_action_sur_clip_reprend_le_plan_et_refuse_les_cibles_incoherentes(client):
    url = f"/api/projets/{demo.PROJET_DEMO}/actions"
    assert client.post(url, json={"type": "refaire", "clip_id": "clip-plan-03"}).status_code == 201
    assert client.post(url, json={"type": "refaire"}).status_code == 422
    assert client.post(url, json={"type": "refaire", "clip_id": "clip-chanson"}).status_code == 422
    assert client.post(url, json={"type": "passe_dlss5"}).status_code == 422
    assert client.post(url, json={"type": "refaire", "plan_id": "plan-01", "clip_id": "clip-plan-05"}).status_code == 422
    client.post(f"{url}/lancer")
    libelles = [j["libelle"] for j in client.get("/api/file").json()["jobs"]]
    assert libelles == ["Plan 4 — rendu H3", "Plan 4 — FlashVSR ×2", "Plan 4 — DLSS5"]


def test_action_retiree(client):
    url = f"/api/projets/{demo.PROJET_DEMO}/actions"
    action = client.post(url, json={"type": "bruitage", "plan_id": "plan-00"}).json()
    assert client.delete(f"{url}/{action['id']}").status_code == 204
    assert client.delete(f"{url}/{action['id']}").status_code == 404
    assert client.get(url).json() == []


def test_fermeture_arrete_les_moteurs_reels(tmp_path):
    from mymaestro.connectors.simule import ConnecteurSimule

    class Reel(ConnecteurSimule):
        simule = False
        arrets = 0

        def arreter_sans_attendre(self) -> None:
            Reel.arrets += 1
            super().arreter_sans_attendre()

    moteurs = registre_simule(empreintes.DEFAUTS)
    moteurs["maestro"] = Reel("maestro", Voie.GPU, empreintes.DEFAUTS["maestro"])
    moteurs["maestro"].etat = EtatMoteur.DEMARRE  # démarré : il doit être arrêté ; un moteur réel jamais démarré ne l'est pas
    with TestClient(creer_app(":memory:", connecteurs=moteurs, dossier_projets=tmp_path)):
        pass
    assert Reel.arrets == 1


def _client_sur_carte(tmp_path, monkeypatch, vram_mo):
    from mymaestro.outils import gpu

    monkeypatch.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("Carte de test", vram_mo, "nvidia-smi"))
    projets = tmp_path / "projets"
    return TestClient(creer_app(
        ":memory:", dossier_medias=tmp_path / "medias", dossier_projets=projets,
        connecteurs=registre_simule(empreintes.DEFAUTS, repondeur=modules.repondeur_simule(projets)),
    ))


def test_recette_h3_1080p_relue_sur_12_go_ne_fait_pas_planter_les_lectures(tmp_path, monkeypatch):
    from mymaestro.outils import gpu

    with _client_sur_carte(tmp_path, monkeypatch, 32768) as client:
        existante = client.get("/api/recettes", params={"module": "director_musique"}).json()[0]["id"]
        corps = {"module": "director_musique", "nom": "H3 1080p", "valeurs": {"rendu": {"h3": "1080p"}}}
        assert client.put(f"/api/recettes/{existante}", json=corps).status_code == 200
        assert client.get(f"/api/projets/{demo.PROJET_DEMO}/compatibilites").status_code == 200
        monkeypatch.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("NVIDIA GeForce RTX 4070 Ti", 12282, "nvidia-smi"))
        reponse = client.get(f"/api/projets/{demo.PROJET_DEMO}/compatibilites")
        assert reponse.status_code == 200
        h3 = [c for par_plan in reponse.json().values() for c in par_plan if c["moteur"] == "minimax_h3"]
        assert h3 and all(not c["compatible"] and "32 Go" in c["note"] for c in h3)
        assert client.get(f"/api/projets/{demo.PROJET_DEMO}/video/estimation").status_code == 200


def test_carte_de_8_go_demarre_et_h3_prend_480p_par_defaut(tmp_path, monkeypatch):
    with _client_sur_carte(tmp_path, monkeypatch, 8188) as client:  # l'amorçage de la démo ne doit pas échouer
        rendu = client.get("/api/rendu")
        assert rendu.status_code == 200
        assert [m["definition"] for m in rendu.json()["moteurs"] if m["moteur"] == "minimax_h3"] == ["480p"]
        defauts = client.get("/api/modules/director_musique/defauts").json()
        assert defauts["rendu"]["h3"] == "480p"
        assert client.post("/api/recettes", json={"module": "director_musique", "nom": "Défauts", "valeurs": {}}).status_code == 201
        assert client.post(
            "/api/recettes", json={"module": "director_musique", "nom": "H3 544p", "valeurs": {"rendu": {"h3": "544p"}}}
        ).status_code == 422
