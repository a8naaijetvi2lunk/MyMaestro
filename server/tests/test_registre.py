import pytest
from fastapi.testclient import TestClient

from mymaestro import config
from mymaestro.app import creer_app
from mymaestro.connectors.base import Empreinte
from mymaestro.connectors.maestro import ConnecteurCodex, ConnecteurMaestro, ProcessusMaestro
from mymaestro.connectors.registre import prevol_pour, registre
from mymaestro.connectors.simule import ConnecteurSimule, registre_simule
from mymaestro.contrat.modeles import EtatMoteur, ProjetEntree, StatutJob, Voie
from mymaestro.core import amorce, depot, empreintes
from mymaestro.core.contexte import Contexte
from mymaestro.core.db import Base
from mymaestro.core.file import File
from mymaestro.core.ordonnanceur import Ordonnanceur
from mymaestro.fixtures import demo
from mymaestro.modules.director_musique import phases
from mymaestro.outils import systeme


def test_moteurs_reels_selon_la_configuration():
    processus = ProcessusMaestro(lancer=lambda: None, prealables=lambda: None)
    moteurs = registre(empreintes.DEFAUTS, None, reels=frozenset({"maestro", "codex"}), processus=processus)
    assert isinstance(moteurs["maestro"], ConnecteurMaestro) and isinstance(moteurs["codex"], ConnecteurCodex)
    assert moteurs["maestro"].processus is moteurs["codex"].processus is processus
    assert isinstance(moteurs["dlss5"], ConnecteurSimule) and isinstance(moteurs["bonsai"], ConnecteurSimule)
    moteurs["bonsai"].etat = EtatMoteur.CHARGE
    assert not moteurs["codex"].peut_executer()  # Maestro arrêté et Bonsai sur le GPU : Codex attend
    moteurs["bonsai"].etat = EtatMoteur.ARRETE
    assert moteurs["codex"].peut_executer()
    assert all(isinstance(m, ConnecteurSimule) for m in registre(empreintes.DEFAUTS, None, reels=frozenset()).values())
    assert config._moteurs_reels("maestro, Codex") == frozenset({"maestro", "codex"})
    assert config._moteurs_reels("aucun") == frozenset()


def test_tous_les_moteurs_reels():
    from mymaestro.connectors.bonsai import ConnecteurBonsai
    from mymaestro.connectors.claude import ConnecteurClaude
    from mymaestro.connectors.dlss5 import ConnecteurDlss5

    moteurs = registre(empreintes.DEFAUTS, None, reels=frozenset({"maestro", "codex", "dlss5", "bonsai", "claude"}),
                       processus=ProcessusMaestro(lancer=lambda: None, prealables=lambda: None))
    assert isinstance(moteurs["dlss5"], ConnecteurDlss5) and isinstance(moteurs["bonsai"], ConnecteurBonsai)
    assert isinstance(moteurs["claude"], ConnecteurClaude)
    assert not any(m.simule for m in moteurs.values())
    assert all(m.etat is EtatMoteur.ARRETE for m in moteurs.values())  # rien n'est lancé à la construction
    assert config._moteurs_reels("maestro,codex,dlss5,bonsai,claude") == frozenset({"maestro", "codex", "dlss5", "bonsai", "claude"})


def test_prevol_seulement_pour_un_maestro_reel_arrete(monkeypatch):
    appels: list[float] = []
    monkeypatch.setattr(systeme, "exiger_marge", lambda marge, lecteur=None: appels.append(marge))
    reels = registre(empreintes.DEFAUTS, None, reels=frozenset({"maestro"}), processus=ProcessusMaestro(lancer=lambda: None, prealables=lambda: None))
    prevol_pour(reels)("maestro")
    prevol_pour(registre(empreintes.DEFAUTS, None, reels=frozenset()))("maestro")
    prevol_pour(reels)("claude")
    assert appels == [config.MARGE_MEMOIRE_MAESTRO_GO]


class _Patient(ConnecteurSimule):
    pret = False

    def peut_executer(self) -> bool:
        return self.pret


def test_la_voie_cloud_saute_un_connecteur_qui_attend():
    base = Base(":memory:")
    file = File(base)
    patient = _Patient("codex", Voie.CLOUD, Empreinte(0, 0))
    ordonnanceur = Ordonnanceur(file, {"codex": patient})
    job = file.ajouter(voie=Voie.CLOUD, connecteur="codex")
    assert ordonnanceur.vider() == 0 and file.lire(job).statut is StatutJob.EN_FILE and file.lire(job).tentatives == 0
    patient.pret = True
    assert ordonnanceur.vider() == 1 and file.lire(job).statut is StatutJob.TERMINE
    base.fermer()


def test_bonsai_inactif_s_arrete_pour_laisser_le_gpu_a_codex():
    base = Base(":memory:")
    file = File(base)
    moteurs = registre_simule(empreintes.DEFAUTS, journal=[])

    class _Codex(ConnecteurSimule):
        def peut_executer(self) -> bool:
            return moteurs["bonsai"].etat is EtatMoteur.ARRETE

        def attend_le_gpu(self) -> bool:
            return not self.peut_executer()

    moteurs["codex"] = _Codex("codex", Voie.CLOUD, Empreinte(0, 0))
    ordonnanceur = Ordonnanceur(file, moteurs)
    file.ajouter(voie=Voie.GPU, connecteur="bonsai", modele="bonsai")
    ordonnanceur.vider()
    assert moteurs["bonsai"].etat is EtatMoteur.CHARGE
    image = file.ajouter(voie=Voie.CLOUD, connecteur="codex")
    ordonnanceur.vider()
    assert file.lire(image).statut is StatutJob.TERMINE and moteurs["bonsai"].etat is EtatMoteur.ARRETE
    base.fermer()


def test_arret_propre_sans_tentative_perdue():
    base = Base(":memory:")
    file = File(base)
    job = file.ajouter(voie=Voie.GPU, connecteur="maestro")
    file.demarrer(job)
    assert file.suspendre_en_cours() == 1
    repris = file.lire(job)
    assert (repris.statut, repris.tentatives) == (StatutJob.EN_FILE, 0) and "arrêt de MyMaestro" in repris.erreur
    base.fermer()


def test_phases_refusent_de_partir_sans_memoire(tmp_path):
    base = Base(":memory:")
    amorce.amorcer_si_vide(base)

    def refuser(connecteur: str) -> None:
        raise systeme.MemoireInsuffisante("Mémoire engagée insuffisante : quitte Docker Desktop")

    contexte = Contexte(base=base, file=File(base), dossier_projets=tmp_path, prevol=refuser)
    with base.transaction() as cx:
        projet = depot.creer_projet(cx, ProjetEntree(titre="Essai", recette_id=demo.RECETTE_DEMO), phases.MODULE, phases.etat_initial())
    phases.televerser_fini(contexte, projet.id, "chanson.wav", 30.0)
    with pytest.raises(phases.ErreurPhase, match="Docker"):
        phases.lancer_phase(contexte, projet.id, "analyse")
    assert contexte.file.lister_projet(projet.id) == []
    base.fermer()


def test_fermeture_arrete_maestro_demarre_par_codex_seul():
    processus = ProcessusMaestro(lancer=lambda: None, prealables=lambda: None)
    moteurs = registre(empreintes.DEFAUTS, None, reels=frozenset({"codex"}), processus=processus)
    assert moteurs["maestro"].simule and not moteurs["codex"].simule
    processus._externe = True  # Maestro lancé par Codex (faux processus vivant)
    moteurs["codex"].demarrer()
    assert processus.lance()
    with TestClient(creer_app(":memory:", connecteurs=moteurs)):
        pass
    assert not processus.lance() and moteurs["codex"].etat is EtatMoteur.ARRETE


def test_prevol_codex_controle_le_processus_partage_seulement_s_il_n_est_pas_lance(monkeypatch):
    appels: list[float] = []
    monkeypatch.setattr(systeme, "exiger_marge", lambda marge, lecteur=None: appels.append(marge))
    processus = ProcessusMaestro(lancer=lambda: None, prealables=lambda: None)
    moteurs = registre(empreintes.DEFAUTS, None, reels=frozenset({"codex"}), processus=processus)
    prevol_pour(moteurs)("codex")
    assert appels == [config.MARGE_MEMOIRE_MAESTRO_GO]
    processus._externe = True  # le Maestro partagé tourne déjà : sa marge a été contrôlée à son démarrage
    prevol_pour(moteurs)("codex")
    assert appels == [config.MARGE_MEMOIRE_MAESTRO_GO]
    assert moteurs["maestro"].simule
    prevol_pour(moteurs)("maestro")  # maestro simulé : pas de contrôle
    assert len(appels) == 1


def test_bonsai_ne_s_arrete_pas_pour_un_maestro_en_demarrage():
    base = Base(":memory:")
    file = File(base)
    moteurs = registre_simule(empreintes.DEFAUTS, journal=[])
    processus = ProcessusMaestro(lancer=lambda: None, prealables=lambda: None)
    codex = ConnecteurCodex(processus, gpu_libre=lambda: moteurs["bonsai"].etat is EtatMoteur.ARRETE)
    moteurs["codex"] = codex
    ordonnanceur = Ordonnanceur(file, moteurs)
    file.ajouter(voie=Voie.GPU, connecteur="bonsai", modele="bonsai")
    ordonnanceur.vider()
    file.ajouter(voie=Voie.CLOUD, connecteur="codex")
    processus._phase = "demarrage"  # Maestro démarre déjà : Codex attend ce démarrage, pas la libération du GPU
    assert processus.lance() and not codex.peut_executer() and not codex.attend_le_gpu()
    ordonnanceur.etape_gpu()
    assert moteurs["bonsai"].etat is EtatMoteur.CHARGE
    processus._phase = "arrete"  # arrêté, Bonsai sur le GPU : là, Codex attend bien le GPU
    assert codex.attend_le_gpu()
    ordonnanceur.etape_gpu()
    assert moteurs["bonsai"].etat is EtatMoteur.ARRETE
    base.fermer()


def test_echec_d_arret_de_bonsai_publie_une_seule_erreur_puis_reessaie():
    base = Base(":memory:")
    file = File(base)
    moteurs = registre_simule(empreintes.DEFAUTS, journal=[])

    class _Codex(ConnecteurSimule):
        def attend_le_gpu(self) -> bool:
            return True

    moteurs["codex"] = _Codex("codex", Voie.CLOUD, Empreinte(0, 0))
    ordonnanceur = Ordonnanceur(file, moteurs)
    file.ajouter(voie=Voie.GPU, connecteur="bonsai", modele="bonsai")
    ordonnanceur.vider()
    file.ajouter(voie=Voie.CLOUD, connecteur="codex")
    moteurs["codex"].peut_executer = lambda: False
    bonsai = moteurs["bonsai"]
    reussir = {"oui": False}
    vrai_arret = bonsai.arreter

    def arreter() -> None:
        if not reussir["oui"]:
            raise OSError("taskkill refusé")
        vrai_arret()

    bonsai.arreter = arreter
    abonnement = ordonnanceur.bus.abonner()
    for _ in range(3):
        ordonnanceur.etape_gpu()
    erreurs = []
    while not abonnement.empty():
        evenement = abonnement.get_nowait()
        if evenement["type"] == "erreur_ordonnanceur":
            erreurs.append(evenement)
    assert len(erreurs) == 1 and "taskkill" in erreurs[0]["message"]
    assert bonsai.etat is EtatMoteur.CHARGE and not ordonnanceur._gpu_libere
    reussir["oui"] = True
    ordonnanceur.etape_gpu()
    assert bonsai.etat is EtatMoteur.ARRETE and ordonnanceur._gpu_libere and ordonnanceur._echec_liberation is None
    base.fermer()
