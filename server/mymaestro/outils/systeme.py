"""Mesures système utiles aux connecteurs réels : mémoire engagée (Windows), ports, instance de Maestro lancée à la main."""

from __future__ import annotations

import ctypes
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import config

GO = 1024**3


@dataclass(frozen=True)
class MemoireEngagee:
    limite_octets: int  # limite de mémoire engagée : RAM + fichier d'échange
    disponible_octets: int  # ce qui peut encore être engagé


class _EtatMemoire(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def memoire_engagee() -> MemoireEngagee | None:
    """Limite et disponible de la mémoire engagée (GlobalMemoryStatusEx) ; None hors Windows ou en cas d'échec."""
    if sys.platform != "win32":
        return None
    etat = _EtatMemoire()
    etat.dwLength = ctypes.sizeof(_EtatMemoire)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(etat)):
        return None
    return MemoireEngagee(limite_octets=int(etat.ullTotalPageFile), disponible_octets=int(etat.ullAvailPageFile))


class MemoireInsuffisante(RuntimeError):
    """Pas assez de mémoire engagée disponible pour démarrer un moteur sans risque de mort silencieuse."""


def exiger_marge(marge_go: float, lecteur: Callable[[], MemoireEngagee | None] = memoire_engagee) -> None:
    etat = lecteur()
    if etat is None:
        return
    if etat.disponible_octets < marge_go * GO:
        raise MemoireInsuffisante(
            f"Mémoire engagée insuffisante : {etat.disponible_octets / GO:.0f} Go disponibles sur {etat.limite_octets / GO:.0f} Go, "
            f"il en faut {marge_go:.0f} pour Maestro. Quitte Docker Desktop (puis « wsl --shutdown ») ou fixe le fichier "
            "d'échange à 32–64 Go (puis redémarre)."
        )


def port_ouvert(port: int, hote: str = "127.0.0.1") -> bool:
    with socket.socket() as prise:
        prise.settimeout(0.5)
        return prise.connect_ex((hote, port)) == 0


def lignes_processus_maestro(texte: str, dossier_app: str) -> list[int]:
    """PID des processus Python qui exécutent `launch.py` de Maestro, d'après des lignes
    « pid<TAB>exécutable<TAB>ligne de commande<TAB>exécutable du parent »."""
    racine = dossier_app.lower().rstrip("\\/")
    pids: list[int] = []
    for ligne in texte.splitlines():
        morceaux = ligne.split("\t")
        if len(morceaux) < 3 or not morceaux[0].strip().isdigit():
            continue
        tout = "\t".join(morceaux[1:]).lower()
        if "launch.py" in morceaux[2].lower() and racine in tout:
            pids.append(int(morceaux[0]))
    return pids


def processus_maestro() -> list[int]:
    """Processus Python qui font tourner Maestro (`launch.py` du dossier de Maestro), quel que soit leur lanceur."""
    script = (
        "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\"; "
        "$ids = @{}; foreach ($x in $p) { $ids[$x.ProcessId] = $x.ExecutablePath }; "
        "foreach ($x in $p) { \"$($x.ProcessId)`t$($x.ExecutablePath)`t$($x.CommandLine)`t$($ids[$x.ParentProcessId])\" }"
    )
    try:
        sortie = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return lignes_processus_maestro(sortie.stdout, str(Path(config.MAESTRO_APP)))


def maestro_manuel_actif() -> bool:
    """Un Maestro lancé à la main occupe-t-il le GPU ? (port 7860 à l'écoute, ou processus du dossier de Maestro)."""
    return port_ouvert(config.MAESTRO_PORT_MANUEL) or bool(processus_maestro())
