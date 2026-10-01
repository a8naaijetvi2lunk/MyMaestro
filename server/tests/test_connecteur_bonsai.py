import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mymaestro.connectors.base import Empreinte, ErreurMoteur
from mymaestro.connectors.bonsai import ConnecteurBonsai, _bonsai_ps1
from mymaestro.contrat.modeles import EtatMoteur, Regime, StatutJob, Voie
from mymaestro.core.file import JobFile

SCHEMA = {"type": "object", "properties": {"prompts": {"type": "array"}}, "required": ["prompts"]}


class FauxBonsai:
    def __init__(self) -> None:
        self.contenu = json.dumps({"prompts": [{"plan_id": "p1", "prompt": "Already moving"}]})
        self.requetes: list[dict] = []
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                return None

            def _json(self, corps) -> None:
                donnees = json.dumps(corps).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def do_GET(self) -> None:  # noqa: N802
                self._json({"data": [{"id": "bonsai2-27b-pq2"}]})

            def do_POST(self) -> None:  # noqa: N802
                faux.requetes.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self._json({"choices": [{"message": {"content": faux.contenu}, "finish_reason": "stop"}]})

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"


@pytest.fixture
def faux():
    serveur = FauxBonsai()
    yield serveur
    serveur.serveur.shutdown()
    serveur.serveur.server_close()


def _job(**donnees):
    return JobFile(
        id="job-bonsai", voie=Voie.GPU, connecteur="bonsai", modele="bonsai2-27b-pq2", projet_id="p", phase="prompts", ordre=0,
        regime=Regime.PHASES, donnees={"tache": "prompts.video", **donnees}, statut=StatutJob.EN_COURS, tentatives=1,
        erreur=None, resultat=None, libelle="", progression=0.0,
    )


def test_demarrage_prompts_contraints_et_arret(faux):
    actions: list[str] = []
    bonsai = ConnecteurBonsai(Empreinte(9440, 9440), url=faux.url, lanceur=actions.append, delai_demarrage_s=5)
    bonsai.demarrer()
    assert actions == ["Start"] and bonsai.etat is EtatMoteur.CHARGE
    resultat = bonsai.executer(_job(prompt="Écris les prompts", schema=SCHEMA, reflexion=False), lambda v: None)
    assert resultat == {"prompts": [{"plan_id": "p1", "prompt": "Already moving"}]}
    corps = faux.requetes[-1]
    assert corps["response_format"]["json_schema"]["schema"] == SCHEMA and corps["response_format"]["json_schema"]["strict"] is True
    assert corps["chat_template_kwargs"] == {"enable_thinking": False} and corps["messages"][0]["content"] == "Écris les prompts"
    bonsai.executer(_job(prompt="x", schema=SCHEMA, reflexion=True), lambda v: None)
    assert "chat_template_kwargs" not in faux.requetes[-1]
    bonsai.arreter()
    assert actions == ["Start", "Stop"] and bonsai.etat is EtatMoteur.ARRETE


def test_json_invalide_et_travail_sans_schema(faux):
    bonsai = ConnecteurBonsai(Empreinte(9440, 9440), url=faux.url, lanceur=lambda action: None, delai_demarrage_s=5)
    faux.contenu = "{pas du json"
    with pytest.raises(ErreurMoteur, match="JSON invalide"):
        bonsai.executer(_job(prompt="x", schema=SCHEMA), lambda v: None)
    with pytest.raises(ErreurMoteur, match="schéma"):
        bonsai.executer(_job(prompt="x"), lambda v: None)


def test_etat_demarre_pendant_le_start_et_arret_si_echec(faux):
    vus: list[EtatMoteur] = []
    bonsai: ConnecteurBonsai

    def lanceur(action: str) -> None:
        vus.append(bonsai.etat)

    bonsai = ConnecteurBonsai(Empreinte(9440, 9440), url=faux.url, lanceur=lanceur, delai_demarrage_s=5)
    bonsai.demarrer()
    assert vus == [EtatMoteur.DEMARRE] and bonsai.etat is EtatMoteur.CHARGE

    def lanceur_qui_echoue(action: str) -> None:
        if action == "Start":
            raise OSError("powershell introuvable")

    casse = ConnecteurBonsai(Empreinte(9440, 9440), url=faux.url, lanceur=lanceur_qui_echoue, delai_demarrage_s=0.1)
    with pytest.raises(ErreurMoteur):
        casse.demarrer()
    assert casse.etat is EtatMoteur.ARRETE


def test_echec_du_start_garde_la_cause():
    def lanceur(action: str) -> None:
        if action == "Start":
            raise OSError("bonsai.ps1 introuvable")

    bonsai = ConnecteurBonsai(Empreinte(9440, 9440), url="http://127.0.0.1:9", lanceur=lanceur, delai_demarrage_s=600)
    with pytest.raises(ErreurMoteur, match="bonsai.ps1 introuvable") as info:
        bonsai.demarrer()
    assert "600 s" not in str(info.value) and bonsai.etat is EtatMoteur.ARRETE


def test_lanceur_qui_leve_toujours_reste_une_erreur_moteur():
    def lanceur(action: str) -> None:
        raise OSError(f"{action} impossible")

    bonsai = ConnecteurBonsai(Empreinte(9440, 9440), url="http://127.0.0.1:9", lanceur=lanceur, delai_demarrage_s=0.1)
    with pytest.raises(ErreurMoteur):
        bonsai.demarrer()
    assert bonsai.etat is EtatMoteur.ARRETE
    with pytest.raises(OSError):
        bonsai.arreter()
    assert bonsai.etat is EtatMoteur.ARRETE


def test_serveur_arrete_apres_demarrer_repasse_a_arrete(faux):
    bonsai = ConnecteurBonsai(Empreinte(9440, 9440), url=faux.url, lanceur=lambda action: None, delai_demarrage_s=5)
    bonsai.demarrer()
    faux.serveur.shutdown()
    faux.serveur.server_close()
    with pytest.raises(ErreurMoteur, match="redémarré"):
        bonsai.executer(_job(prompt="x", schema=SCHEMA), lambda v: None)
    assert bonsai.etat is EtatMoteur.ARRETE


def test_bonsai_ps1_remonte_la_cause(monkeypatch):
    def faux_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="Port 8088 déjà utilisé")

    monkeypatch.setattr("mymaestro.connectors.bonsai.subprocess.run", faux_run)
    with pytest.raises(ErreurMoteur, match="8088"):
        _bonsai_ps1("Start")
