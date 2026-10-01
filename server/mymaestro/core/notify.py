"""Notification Windows de fin de file (spec §4.1 `core/notify`, D23) : un toast, sans dépendance.

Les textes passent par des variables d'environnement, jamais dans la ligne de commande : un titre de projet ne
peut pas injecter de PowerShell. Une notification ratée ne gêne jamais la file."""

from __future__ import annotations

import logging
import os
import subprocess

JOURNAL = logging.getLogger("mymaestro.notify")

SCRIPT_TOAST = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
    "$modele = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
    "$textes = $modele.GetElementsByTagName('text'); "
    "$textes.Item(0).AppendChild($modele.CreateTextNode($env:MYMAESTRO_TITRE)) | Out-Null; "
    "$textes.Item(1).AppendChild($modele.CreateTextNode($env:MYMAESTRO_MESSAGE)) | Out-Null; "
    "$toast = [Windows.UI.Notifications.ToastNotification]::new($modele); "
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
    "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($toast)"
)


def notifier_windows(titre: str, message: str) -> None:
    try:
        resultat = subprocess.run(
            ["powershell", "-NoProfile", "-Command", SCRIPT_TOAST],
            env={**os.environ, "MYMAESTRO_TITRE": titre, "MYMAESTRO_MESSAGE": message},
            capture_output=True, timeout=30, check=False,
        )
        if resultat.returncode != 0:
            erreur = resultat.stderr
            if isinstance(erreur, bytes):
                erreur = erreur.decode("cp1252", errors="replace")
            JOURNAL.warning("notification Windows refusée (code %s) : %s", resultat.returncode, (erreur or "")[-300:])
    except (OSError, subprocess.SubprocessError) as exc:
        JOURNAL.warning("notification Windows impossible : %s", exc)


def sans_notification(titre: str, message: str) -> None:
    return None
