import logging
import subprocess

from mymaestro.core import notify


def test_textes_passes_par_l_environnement(monkeypatch):
    appels = []
    monkeypatch.setattr(
        notify.subprocess, "run",
        lambda commande, **options: appels.append((commande, options)) or subprocess.CompletedProcess(commande, 0, b"", b""),
    )
    notify.notifier_windows("Clip « Nuit » prêt", "8/8 plans rendus ; & | < > \"")
    commande, options = appels[0]
    assert commande[:3] == ["powershell", "-NoProfile", "-Command"]
    assert all("Nuit" not in morceau and "plans rendus" not in morceau for morceau in commande)
    assert options["env"]["MYMAESTRO_TITRE"] == "Clip « Nuit » prêt" and options["env"]["MYMAESTRO_MESSAGE"].startswith("8/8")


def test_une_notification_ratee_ne_leve_rien(monkeypatch):
    def echouer(*args, **options):
        raise subprocess.TimeoutExpired("powershell", 30)

    monkeypatch.setattr(notify.subprocess, "run", echouer)
    notify.notifier_windows("titre", "message")


def test_code_de_retour_non_nul_journalise_sans_lever(monkeypatch, caplog):
    monkeypatch.setattr(
        notify.subprocess, "run", lambda commande, **options: subprocess.CompletedProcess(commande, 1, b"", "refusée é".encode("cp1252"))
    )
    with caplog.at_level(logging.WARNING, logger="mymaestro.notify"):
        notify.notifier_windows("titre", "message")
    assert any("refusée" in r.getMessage() and "code 1" in r.getMessage() for r in caplog.records)
