import struct

from mymaestro.connectors.simule import ConnecteurSimule, registre_simule
from mymaestro.connectors.base import Empreinte
from mymaestro.contrat.modeles import StatutJob, Voie
from mymaestro.core import empreintes
from mymaestro.core.file import JobFile
from mymaestro.modules.director_musique import simulation
from mymaestro.modules.director_musique.modeles import Analyse, ReponseConcepts, ReponseDecoupage, ReponsePrompts


def _job(tache, **donnees):
    return JobFile(
        id="job-abc123", voie=Voie.CLOUD, connecteur="claude", modele=None, projet_id="projet-1", phase="ecriture", ordre=0,
        regime="phases", donnees={"module": "director_musique", "tache": tache, **donnees}, statut=StatutJob.EN_COURS,
        tentatives=1, erreur=None, resultat=None, libelle="", progression=0.0,
    )


def test_png_uni_valide():
    png = simulation.png_uni(8, 4, (240, 164, 204))
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    largeur, hauteur = struct.unpack(">II", png[16:24])
    assert (largeur, hauteur) == (8, 4)


def test_analyse_simulee_cale_les_paroles_sur_la_voix():
    analyse = simulation.analyse_simulee(60.0, "Ligne un\n\nLigne deux\nLigne trois")
    assert analyse.simule and analyse.bpm == 120
    assert [l.texte for l in analyse.lignes] == ["Ligne un", "Ligne deux", "Ligne trois"]
    for ligne in analyse.lignes:
        assert any(v.debut_s <= ligne.debut_s and ligne.fin_s <= v.fin_s + 1e-6 for v in analyse.voix)
    assert analyse.sections[-1].fin_s == 60.0


def test_analyse_simulee_longue_chanson_garde_une_seule_outro():
    a = simulation.analyse_simulee(201.3, "\n".join(f"ligne {n}" for n in range(30)))
    noms = [s.nom for s in a.sections]
    assert noms.count("Outro") == 1 and noms[-1] == "Outro"
    assert a.voix[-1].fin_s > 190
    court = simulation.analyse_simulee(200.0, "")
    assert [s.nom for s in court.sections].count("Outro") == 1


def test_decoupage_simule_couvre_la_chanson():
    analyse = simulation.analyse_simulee(45.0, "A\nB\nC")
    reponse = ReponseDecoupage.model_validate(
        simulation.decoupage_simule(analyse, 45.0, {"titre": "La veilleuse"}, [{"id": "fiche-lina", "type": "personnage"}])
    )
    assert reponse.plans[0].debut_s == 0 and reponse.plans[-1].fin_s == 45.0
    assert all(p.fin_s - p.debut_s <= 10.0 + 1e-6 for p in reponse.plans if p.role == "chante")
    assert any(p.role == "chante" and p.fiches == ["fiche-lina"] for p in reponse.plans)


def test_repondeur_par_tache(tmp_path):
    repondre = simulation.fabriquer_repondeur(tmp_path)
    assert Analyse.model_validate(repondre(_job("analyse", duree_s=30.0, paroles=""))).simule
    concepts = ReponseConcepts.model_validate(repondre(_job("ecriture.concepts", brief={"ambiance": "nuit"}, nombre=3)))
    assert len(concepts.concepts) == 3 and "simulé" in concepts.concepts[0].pitch
    assert "simulée" in repondre(_job("ecriture.chat", message="Plus de pluie"))["reponse"]
    prompts = ReponsePrompts.model_validate(
        repondre(_job("prompts.video", etape="video", plans=[{"id": "p-00", "role": "chante", "description": "Lina chante"}]))
    )
    assert prompts.prompts[0].prompt.startswith("Already singing")
    image = repondre(_job("images.plan", plan_id="p-00", indice=0, format="9:16"))
    assert image["fichier"] == "images/p-00-job-abc123.png"
    assert (tmp_path / "projet-1" / "images" / "p-00-job-abc123.png").read_bytes().startswith(b"\x89PNG")


def test_connecteur_simule_avec_repondeur_et_codex():
    connecteur = ConnecteurSimule("claude", Voie.CLOUD, Empreinte(0, 0), repondeur=lambda job: {"reponse": job.id})
    connecteur.demarrer()
    assert connecteur.executer(_job("ecriture.chat"), lambda v: None) == {"reponse": "job-abc123"}
    registre = registre_simule(empreintes.DEFAUTS)
    assert registre["codex"].voie is Voie.CLOUD and len(registre) == 5
