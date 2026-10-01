import pytest
from fastapi.testclient import TestClient

from mymaestro.api import routes
from mymaestro.app import creer_app
from mymaestro.connectors.simule import registre_simule
from mymaestro.core import empreintes
from mymaestro.core.medias import CheminInterdit, chemin_sur

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG = b"\xff\xd8\xff" + b"1" * 32


@pytest.fixture
def client(tmp_path):
    app = creer_app(":memory:", connecteurs=registre_simule(empreintes.DEFAUTS), dossier_medias=tmp_path)
    with TestClient(app) as c:
        yield c


def _envoyer(client, fiche_id, role, contenu=PNG, type_contenu="image/png"):
    return client.put(f"/api/bibliotheque/{fiche_id}/images/{role}", content=contenu, headers={"Content-Type": type_contenu})


def test_chemin_borne_au_dossier(tmp_path):
    assert chemin_sur(tmp_path, "bibliotheque/f/a.png") == (tmp_path / "bibliotheque" / "f" / "a.png").resolve()
    for interdit in ("../secret.txt", "bibliotheque/../../x", "", ".", "C:/Windows/win.ini",
                     "//192.0.2.1/partage/x.png", "\\\\192.0.2.1\\partage\\x.png", "/etc/x", "a\x00b.png", "D:x"):
        with pytest.raises(CheminInterdit):
            chemin_sur(tmp_path, interdit)


def test_image_televersee_puis_servie(client):
    reponse = _envoyer(client, "fiche-lina", "portrait_pied")
    assert reponse.status_code == 200
    images = {i["role"]: i["chemin"] for i in reponse.json()["images"]}
    assert images["portrait_pied"] == "bibliotheque/fiche-lina/portrait_pied.png"
    assert images["gros_plan"] == "bibliotheque/fiche-lina/gros-plan.png"
    servie = client.get("/api/medias/bibliotheque/fiche-lina/portrait_pied.png")
    assert servie.status_code == 200 and servie.content == PNG
    assert servie.headers["cache-control"] == "no-cache"


def test_nouvelle_image_remplace_l_ancienne(client, tmp_path):
    _envoyer(client, "fiche-toit", "reference")
    _envoyer(client, "fiche-toit", "reference", JPEG, "image/jpeg")
    assert sorted(p.name for p in (tmp_path / "bibliotheque" / "fiche-toit").iterdir()) == ["reference.jpg"]


def test_televersements_refuses(client, monkeypatch):
    assert _envoyer(client, "fiche-lina", "gros_plan", b"texte", "text/plain").status_code == 415
    assert _envoyer(client, "inconnue", "gros_plan").status_code == 404
    assert _envoyer(client, "fiche-lina", "gros_plan", b"").status_code == 400
    monkeypatch.setattr(routes, "TAILLE_MAX_IMAGE", 10)
    assert _envoyer(client, "fiche-lina", "gros_plan").status_code == 413


def test_media_hors_dossier_introuvable(client):
    assert client.get("/api/medias/bibliotheque/absent.png").status_code == 404
    assert client.get("/api/medias/%2e%2e/secret.txt").status_code == 404


def test_image_et_fiche_supprimees(client, tmp_path):
    _envoyer(client, "fiche-lina", "gros_plan")
    assert client.delete("/api/bibliotheque/fiche-lina/images/gros_plan").status_code == 204
    fiche = next(f for f in client.get("/api/bibliotheque").json() if f["id"] == "fiche-lina")
    assert "gros_plan" not in {i["role"] for i in fiche["images"]}
    assert not (tmp_path / "bibliotheque" / "fiche-lina" / "gros_plan.png").exists()
    assert client.delete("/api/bibliotheque/fiche-lina/images/gros_plan").status_code == 404
    _envoyer(client, "fiche-lina", "portrait_pied")
    assert client.delete("/api/bibliotheque/fiche-lina").status_code == 204
    assert not (tmp_path / "bibliotheque" / "fiche-lina").exists()


def test_unc_et_octet_nul_donnent_404(client):
    assert client.get("/api/medias///hote/partage/x.png").status_code == 404
    assert client.get("/api/medias/%5C%5Chote%5Cpartage%5Cx.png").status_code == 404
    assert client.get("/api/medias/a%00b.png").status_code == 404


def test_envois_de_roles_differents_pendant_l_un_l_autre(client, monkeypatch):
    """Un envoi lent ne doit pas écraser un autre rôle terminé entre-temps."""
    import asyncio
    import threading

    from mymaestro.core import medias as m

    original = m.ecrire_flux
    libere = threading.Event()

    async def lent(flux, cible, taille_max):
        total = await original(flux, cible, taille_max)
        if cible.name.startswith("portrait_pied"):
            while not libere.is_set():
                await asyncio.sleep(0.01)
        return total

    monkeypatch.setattr(m, "ecrire_flux", lent)
    resultat = {}
    lent_envoi = threading.Thread(target=lambda: resultat.update(r=_envoyer(client, "fiche-toit", "portrait_pied")))
    lent_envoi.start()
    import time
    time.sleep(0.3)
    assert _envoyer(client, "fiche-toit", "gros_plan").status_code == 200
    libere.set()
    lent_envoi.join(10)
    assert resultat["r"].status_code == 200
    fiche = next(f for f in client.get("/api/bibliotheque").json() if f["id"] == "fiche-toit")
    assert {"portrait_pied", "gros_plan"} <= {i["role"] for i in fiche["images"]}


def test_envoi_pendant_suppression_de_la_fiche(client, monkeypatch):
    """Fiche supprimée pendant un envoi : 404, elle ne réapparaît pas et aucun fichier orphelin ne reste."""
    import asyncio
    import threading

    from mymaestro.core import medias as m

    original = m.ecrire_flux
    libere = threading.Event()

    async def lent(flux, cible, taille_max):
        total = await original(flux, cible, taille_max)
        while not libere.is_set():
            await asyncio.sleep(0.01)
        return total

    monkeypatch.setattr(m, "ecrire_flux", lent)
    resultat = {}
    envoi = threading.Thread(target=lambda: resultat.update(r=_envoyer(client, "fiche-toit", "reference")))
    envoi.start()
    import time
    time.sleep(0.3)
    assert client.delete("/api/bibliotheque/fiche-toit").status_code == 204
    libere.set()
    envoi.join(10)
    assert resultat["r"].status_code == 404
    assert "fiche-toit" not in {f["id"] for f in client.get("/api/bibliotheque").json()}
