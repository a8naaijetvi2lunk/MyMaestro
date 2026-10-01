"""Connecteur réel Bonsai 2 (spec §4.2, D10) : `bonsai.ps1 -Action Start/Stop`, puis appel direct de
`/v1/chat/completions` avec `response_format` json_schema (jamais la CLI `claude` redirigée vers llama-server).
Le modèle reste chargé tant que le serveur tourne : sa VRAM est tenue jusqu'à l'arrêt (l'arbitre le sait)."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import config
from ..contrat.modeles import EtatMoteur, Voie
from ..outils.http import attendre, post_json
from .base import Connecteur, Empreinte, ErreurMoteur

if TYPE_CHECKING:
    from ..core.file import JobFile

MAX_JETONS = 6144  # la réflexion compte dans max_tokens : trop bas, elle consomme tout (tâche 0)


def _bonsai_ps1(action: str) -> None:
    """`bonsai.ps1` lève tout de suite si un fichier manque, si le port est pris ou si le moteur tombe au chargement."""
    resultat = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(config.BONSAI_RACINE / "bonsai.ps1"),
         "-Action", action, "-NoBrowser"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, check=False,
    )
    if resultat.returncode != 0:
        raise ErreurMoteur(f"bonsai.ps1 -Action {action} : code {resultat.returncode} {(resultat.stderr or resultat.stdout or '')[-300:].strip()}")


ARGUMENTS_LLAMA_SERVER = (
    "-m models/Ternary-Bonsai-2-27B-PQ2_0.gguf --no-mmproj --host 127.0.0.1 --port 8088 --cors-origins localhost -lv 4 "
    "--alias bonsai2-27b-pq2 -ngl 99 -fa on -c 172032 -np 1 -b 128 -ub 128 -t 12 -ctk q4_0 -ctv q4_0 --temp 1.0 "
    "--top-p 0.95 --top-k 20 --min-p 0 --repeat-penalty 1.0 --jinja --chat-template-file models/bonsai2-chat-template.jinja "
    "--reasoning-format deepseek --reasoning-budget 2048"
).split()  # commande validée sur la machine de référence, sans le projecteur d'images


def _fichier_pid() -> Path:
    return config.DOSSIER_DONNEES / f"bonsai-{config.BONSAI_PORT}.pid"


def _tuer_arbre(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


def _ecouteur_bonsai() -> tuple[int, Path] | None:
    """(PID, exécutable) du processus qui écoute sur le port de Bonsai, ou None."""
    script = (
        f"$c = Get-NetTCPConnection -LocalPort {config.BONSAI_PORT} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; "
        "if ($c) { $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; if ($p -and $p.Path) { \"$($c.OwningProcess)|$($p.Path)\" } }"
    )
    try:
        resultat = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pid, _, chemin = (resultat.stdout or "").strip().partition("|")
    return (int(pid), Path(chemin)) if pid.isdigit() and chemin else None


def _chemin_processus(pid: int) -> Path | None:
    """Exécutable du processus `pid` (None s'il n'existe plus) : un PID du fichier peut avoir été réattribué."""
    script = f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; if ($p -and $p.Path) {{ $p.Path }}"
    try:
        resultat = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    chemin = (resultat.stdout or "").strip()
    return Path(chemin) if chemin else None


def _sous_racine(chemin: Path | None) -> bool:
    return chemin is not None and chemin.resolve().is_relative_to(config.BONSAI_RACINE.resolve())


def _arreter_residuel(*, strict: bool) -> None:
    """Arrête tout llama-server de Bonsai resté vivant (PID du fichier, puis écouteur du port), jamais un processus étranger.
    `strict` (au Start) : un écouteur étranger sur le port est une erreur, et on attend que le port se libère."""
    fichier = _fichier_pid()
    try:
        pid = int(fichier.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = None
    if pid is not None and _sous_racine(_chemin_processus(pid)):
        _tuer_arbre(pid)
    fichier.unlink(missing_ok=True)
    ecouteur = _ecouteur_bonsai()
    if ecouteur is None:
        return
    if _sous_racine(ecouteur[1]):
        _tuer_arbre(ecouteur[0])
        if strict:
            for _ in range(20):
                if _ecouteur_bonsai() is None:
                    return
                time.sleep(0.5)
            raise ErreurMoteur(f"port {config.BONSAI_PORT} toujours occupé par un ancien llama-server")
    elif strict:
        raise ErreurMoteur(f"port {config.BONSAI_PORT} déjà pris par un autre processus ({ecouteur[1].name})")


def _lanceur_integre(action: str) -> None:
    """Lanceur de l'installation faite par MyMaestro (pas de `bonsai.ps1`) : llama-server de PrismML, détaché."""
    racine = config.BONSAI_RACINE
    if action != "Start":
        _arreter_residuel(strict=False)
        return
    _arreter_residuel(strict=True)  # un orphelin d'un plantage précédent garderait la VRAM et fausserait le fichier PID
    config.DOSSIER_JOURNAUX.mkdir(parents=True, exist_ok=True)
    journal = config.DOSSIER_JOURNAUX / f"bonsai-{datetime.now():%Y%m%d-%H%M%S}.log"
    try:
        with journal.open("a", encoding="utf-8") as erreurs:
            processus = subprocess.Popen(
                [str(racine / "bin" / "llama-server.exe"), *ARGUMENTS_LLAMA_SERVER], cwd=racine,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=erreurs,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
    except OSError as exc:
        raise ErreurMoteur(f"llama-server ne démarre pas : {exc}") from None
    _fichier_pid().parent.mkdir(parents=True, exist_ok=True)
    _fichier_pid().write_text(str(processus.pid), encoding="utf-8")


def _lanceur_par_defaut(action: str) -> None:
    """`bonsai.ps1` s'il existe (installation externe), sinon le lanceur intégré."""
    if (config.BONSAI_RACINE / "bonsai.ps1").exists():
        _bonsai_ps1(action)
    else:
        _lanceur_integre(action)


class ConnecteurBonsai(Connecteur):
    nom = "bonsai"
    voie = Voie.GPU

    def __init__(
        self,
        empreinte: Empreinte,
        *,
        url: str = f"http://127.0.0.1:{config.BONSAI_PORT}",
        lanceur: Callable[[str], None] | None = None,
        delai_demarrage_s: float = 600,
    ) -> None:
        super().__init__()
        self.empreinte = empreinte
        self.url = url
        self._lanceur = lanceur or _lanceur_par_defaut
        self.delai_demarrage_s = delai_demarrage_s

    def demarrer(self) -> None:
        self.etat = EtatMoteur.DEMARRE  # un Bonsai en démarrage tient déjà le GPU : l'arbitre et la fermeture doivent le voir
        cause: Exception | None = None
        try:
            self._lanceur("Start")
            pret = attendre(f"{self.url}/v1/models", delai_s=self.delai_demarrage_s, intervalle_s=2)
        except Exception as exc:  # noqa: BLE001
            cause = exc
            pret = False
        if not pret:
            try:
                self._lanceur("Stop")
            except Exception:  # noqa: BLE001, S110 - arrêt de secours : la cause d'origine prime
                pass
            finally:
                self.etat = EtatMoteur.ARRETE
            if cause is not None:
                raise ErreurMoteur(f"Bonsai n'a pas démarré ({type(cause).__name__}: {cause})") from None
            raise ErreurMoteur(f"Bonsai n'a pas répondu en {self.delai_demarrage_s:.0f} s")
        self.etat = EtatMoteur.CHARGE

    def arreter(self) -> None:
        try:
            self._lanceur("Stop")
        finally:
            self.etat = EtatMoteur.ARRETE

    def liberer(self) -> None:
        return None  # llama-server ne rend pas sa VRAM sans être arrêté

    def executer(self, job: JobFile, progression: Callable[[float], None]) -> dict[str, Any]:
        d = job.donnees
        consigne, schema = d.get("prompt"), d.get("schema")
        if not isinstance(consigne, str) or not consigne.strip() or not isinstance(schema, dict):
            raise ErreurMoteur("Travail sans consigne ou sans schéma JSON")
        corps: dict[str, Any] = {
            "model": config.BONSAI_MODELE,
            "messages": [{"role": "user", "content": consigne}],
            "max_tokens": MAX_JETONS,
            "response_format": {"type": "json_schema", "json_schema": {"name": "reponse", "strict": True, "schema": schema}},
        }
        if not d.get("reflexion"):
            corps["chat_template_kwargs"] = {"enable_thinking": False}
        progression(0.1)
        try:
            reponse = post_json(f"{self.url}/v1/chat/completions", corps, timeout=900)
            contenu = reponse["choices"][0]["message"].get("content") or ""
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            refuse = isinstance(exc, ConnectionRefusedError) or (
                isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ConnectionRefusedError)
            )
            if refuse:  # le serveur est mort : l'arbitre doit préparer un « demarrer » à la relance
                self.etat = EtatMoteur.ARRETE
                raise ErreurMoteur("Bonsai ne répond plus (serveur arrêté) : il sera redémarré") from None
            raise ErreurMoteur(f"Bonsai : réponse inattendue ({exc})") from None
        try:
            donnees = json.loads(contenu)
        except json.JSONDecodeError:
            raise ErreurMoteur("Bonsai : JSON invalide") from None
        if not isinstance(donnees, dict):
            raise ErreurMoteur("Bonsai : JSON invalide (objet attendu)")
        progression(1.0)
        return donnees
