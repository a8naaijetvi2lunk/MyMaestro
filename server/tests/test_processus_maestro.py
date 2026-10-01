"""Cycle de vie du processus Maestro sans ffmpeg : préalables hors du verrou, interruptions, instance orpheline."""

import threading
import time

import pytest

from faux_maestro import FauxMaestro
from mymaestro import config
from mymaestro.connectors import maestro as module
from mymaestro.connectors.base import MoteurInterrompu
from mymaestro.connectors.maestro import ProcessusMaestro


@pytest.fixture
def faux(tmp_path):
    with FauxMaestro(tmp_path / "sorties") as serveur:
        yield serveur


def _processus(faux, prealables, lancer=None, **options):
    return ProcessusMaestro(
        url=faux.url, lancer=lancer or (lambda: None), prealables=prealables, dossier_sorties=faux.dossier, intervalle_s=0.01, **options
    )


def _demarrer_en_fil(processus):
    resultat: dict[str, BaseException | None] = {"erreur": None}

    def cible() -> None:
        try:
            processus.demarrer()
        except BaseException as exc:  # noqa: BLE001
            resultat["erreur"] = exc

    fil = threading.Thread(target=cible)
    fil.start()
    return fil, resultat


def _attendre_demarrage(processus):
    while processus._phase != "demarrage":
        time.sleep(0.005)


def test_prealables_lents_ne_bloquent_pas_les_autres_fils(faux):
    processus = _processus(faux, lambda: time.sleep(1))
    fil, _ = _demarrer_en_fil(processus)
    _attendre_demarrage(processus)
    depart = time.monotonic()
    assert processus.lance() is True  # l'arbitre doit voir un démarrage en cours
    assert processus.actif() is False and processus.accepte() is False
    assert time.monotonic() - depart < 0.2
    fil.join(10)
    assert processus.actif()


def test_arret_pendant_des_prealables_lents_interrompt_le_demarrage(faux):
    lancements: list[int] = []
    processus = _processus(faux, lambda: time.sleep(0.6), lancer=lambda: lancements.append(1))
    fil, resultat = _demarrer_en_fil(processus)
    _attendre_demarrage(processus)
    processus.arreter()
    fil.join(10)
    assert isinstance(resultat["erreur"], MoteurInterrompu)
    assert lancements == [] and not processus.lance() and processus._phase == "arrete"


def test_prealables_en_oserror_relayes_puis_nouveau_demarrage_possible(faux):
    appels: list[int] = []

    def prealables() -> None:
        appels.append(1)
        if len(appels) == 1:
            raise OSError("PowerShell introuvable")

    processus = _processus(faux, prealables)
    with pytest.raises(OSError, match="PowerShell"):
        processus.demarrer()
    assert processus._phase == "arrete" and not processus.lance()
    processus.demarrer()
    assert processus.actif()


def test_second_fil_apres_un_demarrage_interrompu_recoit_l_interruption(faux):
    processus = _processus(faux, lambda: time.sleep(0.6))
    premier, _ = _demarrer_en_fil(processus)
    _attendre_demarrage(processus)
    second, resultat = _demarrer_en_fil(processus)
    time.sleep(0.1)
    processus.arreter()
    premier.join(10)
    second.join(10)
    assert isinstance(resultat["erreur"], MoteurInterrompu)


# --- Maestro orphelin ---------------------------------------------------------------------------------


def _orphelin(monkeypatch, tmp_path, *, pids, pid_fichier="4242", port_ouvert=None):
    monkeypatch.setattr(config, "DOSSIER_DONNEES", tmp_path)
    fichier = module._fichier_pid()
    if pid_fichier is not None:
        fichier.write_text(pid_fichier, encoding="utf-8")
    commandes: list[list[str]] = []
    etats = iter(port_ouvert if port_ouvert is not None else [False])
    monkeypatch.setattr(module.systeme, "processus_maestro", lambda: pids)
    monkeypatch.setattr(module.systeme, "port_ouvert", lambda port, *a, **k: next(etats, False))
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **k: commandes.append(list(cmd)))
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    return fichier, commandes


def test_fichier_pid_porte_le_port(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOSSIER_DONNEES", tmp_path)
    assert module._fichier_pid() == tmp_path / f"maestro-{config.MAESTRO_PORT}.pid"


def test_orphelin_present_dans_la_liste_est_arrete(monkeypatch, tmp_path):
    fichier, commandes = _orphelin(monkeypatch, tmp_path, pids=[4242, 99], port_ouvert=[True, True, False])
    module._arreter_orphelin()
    assert commandes == [["taskkill", "/PID", "4242", "/T", "/F"]]
    assert not fichier.exists()


def test_pid_absent_de_la_liste_ne_tue_rien(monkeypatch, tmp_path):
    fichier, commandes = _orphelin(monkeypatch, tmp_path, pids=[99])
    module._arreter_orphelin()
    assert commandes == [] and not fichier.exists()


def test_fichier_absent_ou_illisible_ne_fait_rien(monkeypatch, tmp_path):
    fichier, commandes = _orphelin(monkeypatch, tmp_path, pids=[4242], pid_fichier=None)
    module._arreter_orphelin()
    assert commandes == []
    fichier.write_text("pas un nombre", encoding="utf-8")
    module._arreter_orphelin()
    assert commandes == []


def test_prealables_maestro_arretent_l_orphelin_en_premier(monkeypatch):
    ordre: list[str] = []
    monkeypatch.setattr(module, "_arreter_orphelin", lambda: ordre.append("orphelin"))
    monkeypatch.setattr(module.systeme, "maestro_manuel_actif", lambda: ordre.append("manuel") or False)
    monkeypatch.setattr(module.systeme, "port_ouvert", lambda port, *a, **k: False)
    monkeypatch.setattr(module.systeme, "exiger_marge", lambda marge, *a, **k: None)
    module._prealables_maestro()
    assert ordre == ["orphelin", "manuel"]


def test_tuer_supprime_le_fichier_pid_de_ce_processus(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DOSSIER_DONNEES", tmp_path)
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **k: None)

    class Faux:
        pid = 777
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, delai):
            self.returncode = 1

    fichier = module._fichier_pid()
    fichier.write_text("777", encoding="utf-8")
    module._tuer(Faux())
    assert not fichier.exists()
    fichier.write_text("1", encoding="utf-8")  # PID d'une autre instance : conservé
    module._tuer(Faux())
    assert fichier.exists()


def test_soumission_ratee_pendant_un_arret_est_une_interruption():
    processus = ProcessusMaestro(url="http://127.0.0.1:9", lancer=lambda: None, prealables=lambda: None)
    with pytest.raises(MoteurInterrompu):  # génération changée : un arrêt décidé par MyMaestro
        processus._suivre_job("/api/v1/generate", {}, lambda v: None, 5, processus._generation - 1)
    with pytest.raises(module.ErreurMoteur) as echec:  # même génération : Maestro injoignable, échec ordinaire
        processus._suivre_job("/api/v1/generate", {}, lambda v: None, 5, processus._generation)
    assert not isinstance(echec.value, MoteurInterrompu)


def test_pid_reattribue_sans_port_7870_ouvert_ne_tue_rien(monkeypatch, tmp_path):
    # notre instance est morte (port fermé) ; son ancien PID appartient désormais à un Maestro manuel
    fichier, commandes = _orphelin(monkeypatch, tmp_path, pids=[4242], port_ouvert=[False])
    module._arreter_orphelin()
    assert commandes == [] and not fichier.exists()


def test_prealables_sans_marge_gardent_l_orphelin_et_le_port(monkeypatch):
    ordre: list[str] = []
    monkeypatch.setattr(module, "_arreter_orphelin", lambda: ordre.append("orphelin"))
    monkeypatch.setattr(module.systeme, "maestro_manuel_actif", lambda: ordre.append("manuel") or False)
    monkeypatch.setattr(module.systeme, "port_ouvert", lambda port, *a, **k: ordre.append("port") or True)
    monkeypatch.setattr(module.systeme, "exiger_marge", lambda *a, **k: ordre.append("marge"))
    with pytest.raises(module.ErreurMoteur, match="déjà pris"):
        module._prealables_maestro(marge_memoire=False)
    assert ordre == ["orphelin", "manuel", "port"]  # tout sauf la marge mémoire
