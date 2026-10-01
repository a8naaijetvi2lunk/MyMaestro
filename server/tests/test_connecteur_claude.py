import json
import sys
import threading
import time
from pathlib import Path

import pytest

from mymaestro import config
from mymaestro.connectors.base import ErreurMoteur, MoteurInterrompu
from mymaestro.connectors.claude import ConnecteurClaude, extraire
from mymaestro.contrat.modeles import EtatMoteur, Regime, StatutJob, Voie
from mymaestro.core.file import JobFile

FAUSSE_CLI = Path(__file__).with_name("faux_claude.py")
SCHEMA = {"type": "object", "properties": {"reponse": {"type": "string"}}, "required": ["reponse"]}


def _connecteur():
    return ConnecteurClaude(executable=[sys.executable, str(FAUSSE_CLI)], delai_s=60)


def _job(modele="claude-opus-5-5", **donnees):
    return JobFile(
        id="job-claude", voie=Voie.CLOUD, connecteur="claude", modele=modele, projet_id="p", phase="ecriture", ordre=0,
        regime=Regime.PHASES, donnees={"tache": "ecriture.chat", **donnees}, statut=StatutJob.EN_COURS, tentatives=1,
        erreur=None, resultat=None, libelle="", progression=0.0,
    )


def test_consigne_par_stdin_hors_du_depot(tmp_path, monkeypatch):
    trace = tmp_path / "trace.json"
    monkeypatch.setenv("FAUX_CLAUDE_TRACE", str(trace))
    resultat = _connecteur().executer(_job(prompt="Affine le concept\nsur deux lignes", schema=SCHEMA, effort="high"), lambda v: None)
    assert resultat == {"reponse": "d'accord"}
    vu = json.loads(trace.read_text(encoding="utf-8"))
    assert vu["consigne"] == "Affine le concept\nsur deux lignes"
    argv = vu["argv"]
    assert argv[:5] == ["-p", "--output-format", "json", "--model", "claude-opus-5-5"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == SCHEMA
    assert argv[argv.index("--effort") + 1] == "high" and "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert not Path(vu["dossier"]).resolve().is_relative_to(config.RACINE.resolve())


def test_sorties(monkeypatch):
    monkeypatch.setenv("FAUX_CLAUDE_SORTIE", json.dumps({"result": json.dumps({"reponse": "par result"})}))
    assert _connecteur().executer(_job(prompt="x", schema=SCHEMA), lambda v: None) == {"reponse": "par result"}
    monkeypatch.setenv("FAUX_CLAUDE_SORTIE", json.dumps({"is_error": True, "result": "Quota atteint"}))
    with pytest.raises(ErreurMoteur, match="Quota"):
        _connecteur().executer(_job(prompt="x", schema=SCHEMA), lambda v: None)
    monkeypatch.setenv("FAUX_CLAUDE_SORTIE", "pas du json")
    with pytest.raises(ErreurMoteur, match="illisible"):
        _connecteur().executer(_job(prompt="x", schema=SCHEMA), lambda v: None)
    with pytest.raises(ErreurMoteur, match="schéma"):
        _connecteur().executer(_job(prompt="x"), lambda v: None)
    assert extraire({"result": "[1, 2]"}) is None and extraire({}) is None


def test_arret_reel_pendant_un_appel_lent(monkeypatch):
    monkeypatch.setenv("FAUX_CLAUDE_LENT", "1")
    connecteur = _connecteur()
    connecteur.demarrer()
    resultat: list[BaseException | None] = []

    def tourner():
        try:
            connecteur.executer(_job(prompt="x", schema=SCHEMA), lambda v: None)
            resultat.append(None)
        except BaseException as exc:  # noqa: BLE001
            resultat.append(exc)

    fil = threading.Thread(target=tourner)
    fil.start()
    limite = time.monotonic() + 10
    while not connecteur._processus and time.monotonic() < limite:
        time.sleep(0.05)
    lances = list(connecteur._processus)
    assert lances
    debut = time.monotonic()
    connecteur.arreter_sans_attendre()
    fil.join(10)
    assert not fil.is_alive() and time.monotonic() - debut < 5
    assert isinstance(resultat[0], MoteurInterrompu)
    assert all(p.poll() is not None for p in lances)
    assert connecteur.etat is EtatMoteur.ARRETE


def test_delai_depasse_message_lisible(monkeypatch):
    monkeypatch.setenv("FAUX_CLAUDE_LENT", "1")
    connecteur = _connecteur()
    connecteur.delai_s = 1
    with pytest.raises(ErreurMoteur, match="délai") as info:
        connecteur.executer(_job(prompt="x", schema=SCHEMA), lambda v: None)
    assert "--json-schema" not in str(info.value) and not isinstance(info.value, MoteurInterrompu)


def test_delai_depasse_ne_reste_pas_bloque_par_un_descendant_qui_garde_les_tubes(monkeypatch):
    import subprocess as sp
    import time

    from mymaestro.connectors import claude as module

    class FauxProcessus:
        pid, returncode = 4242, 1

        def poll(self):
            return 1  # claude est mort ; un descendant détaché garde les tubes

        def communicate(self, input=None, timeout=None):
            if timeout is None:
                time.sleep(30)  # attente sans fin de l'EOF
            raise sp.TimeoutExpired("claude", timeout)

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: FauxProcessus())
    debut = time.monotonic()
    with pytest.raises(ErreurMoteur, match="délai"):
        ConnecteurClaude(executable=["claude"], delai_s=1).executer(_job(prompt="x", schema=SCHEMA), lambda v: None)
    assert time.monotonic() - debut < 5
