"""Faux Maestro pour les tests des connecteurs réels : sous-ensemble de la même API HTTP, sorties produites par ffmpeg."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mymaestro.modules.director_musique.simulation import png_uni
from mymaestro.outils import ffmpeg

ANALYSE = {
    "duration": 12.0,
    "sample_rate": 44100,
    "bpm": 118.0,
    "beats": [{"time": 0.5, "strength": 0.8}, {"time": 1.0, "strength": 0.6}],
    "downbeats": [0.5],
    "sections": [{"start": 0.0, "end": 6.0, "label": "intro", "energy": 0.3}, {"start": 6.0, "end": 12.0, "label": "chorus", "energy": 0.8}],
    "onset_envelope": [],
    "lyrics": [{"start": 6.2, "end": 8.0, "text": "Je marche seule", "speaker": None}],
    "vocals_path": None,
}


class FauxMaestro:
    def __init__(self, dossier: Path) -> None:
        self.dossier = dossier
        self.requetes: list[tuple[str, dict[str, Any]]] = []
        self.jobs: dict[str, dict[str, Any]] = {}
        self.annules: list[str] = []
        self.liberations = 0
        self.statut_final = "completed"  # « failed » : le prochain job échoue
        self.erreur: str | None = None
        self.images_en_moins = 0  # > 0 : vidéo tronquée
        self.noir = False  # vidéo noire
        self.lenteur = 0  # > 0 : chaque nouveau job répond « running » autant de fois avant d'être terminé
        self.journal: list[tuple[str, str]] = []  # ordre des fins de jobs et des release-model
        self.status_en_panne = 0  # nombre de réponses 500 sur /status
        self.modeles: set[str] = set()  # modèles téléchargeables ; un id inconnu rend 404 (téléchargements de l'installeur)
        self.telechargements_demandes: list[str] = []
        self.telechargements: dict[str, dict[str, Any]] = {}
        self.statut_telechargement = "completed"  # issue des téléchargements demandés (« failed » : échec)
        self.erreur_telechargement: str | None = None
        self.polls_avant_fin = 1  # nombre d'interrogations de /models/downloads/status avant l'issue
        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), self._gestionnaire())
        self._fil = threading.Thread(target=self.serveur.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def __enter__(self) -> FauxMaestro:
        self._fil.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.serveur.shutdown()
        self.serveur.server_close()

    def _gestionnaire(self) -> type[BaseHTTPRequestHandler]:
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return None

            def _json(self, code: int, corps: Any) -> None:
                donnees = json.dumps(corps).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/api/v1/jobs":  # même forme que le vrai Maestro : {"jobs": [jobs en file ou en cours]}
                    actifs = [{"job_id": i, "status": j["status"]} for i, j in faux.jobs.items() if j["status"] in ("queued", "running")]
                    return self._json(200, {"jobs": actifs})
                if self.path == "/api/v1/models/downloads/status":
                    for suivi in faux.telechargements.values():
                        if suivi["status"] == "downloading":
                            suivi["restants"] -= 1
                            if suivi["restants"] <= 0:
                                suivi["status"] = faux.statut_telechargement
                                suivi["error"] = faux.erreur_telechargement if faux.statut_telechargement == "failed" else None
                    return self._json(200, {"downloads": {i: {"status": s["status"], "error": s["error"]} for i, s in faux.telechargements.items()}})
                if self.path == "/api/v1/downloads/active":
                    actifs = [{"downloaded_bytes": 50, "total_bytes": 100} for s in faux.telechargements.values() if s["status"] == "downloading"]
                    return self._json(200, {"downloads": actifs})
                if self.path.startswith("/api/v1/status/"):
                    if faux.status_en_panne > 0:
                        faux.status_en_panne -= 1
                        return self._json(500, {"detail": "occupé"})
                    job_id = self.path.rsplit("/", 1)[-1]
                    job = faux.jobs.get(job_id)
                    if job is None:
                        return self._json(404, {"detail": "inconnu"})
                    if job.get("restants", 0) > 0:
                        job["restants"] -= 1
                        if job["restants"] == 0:
                            job["status"] = "completed"
                            faux.journal.append(("termine", job_id))
                    return self._json(200, {k: v for k, v in job.items() if k != "restants"})
                return self._json(404, {})

            def do_POST(self) -> None:  # noqa: N802
                longueur = int(self.headers.get("Content-Length") or 0)
                corps = json.loads(self.rfile.read(longueur) or b"{}")
                faux.requetes.append((self.path, corps))
                if self.path == "/api/v1/system/release-model":
                    faux.liberations += 1
                    faux.journal.append(("release", ""))
                    return self._json(200, {"ok": True})
                if self.path.startswith("/api/v1/cancel/"):
                    faux.annules.append(self.path.rsplit("/", 1)[-1])
                    return self._json(200, {"ok": True})
                if self.path.startswith("/api/v1/models/") and self.path.endswith("/download"):
                    modele = self.path[len("/api/v1/models/"):-len("/download")]
                    if modele not in faux.modeles:
                        return self._json(404, {"detail": "modèle inconnu"})
                    faux.telechargements_demandes.append(modele)
                    faux.telechargements[modele] = {"status": "downloading", "error": None, "restants": faux.polls_avant_fin}
                    return self._json(200, {"ok": True})
                if self.path == "/api/v1/audio/analyze":
                    return self._json(200, ANALYSE)
                if self.path in ("/api/v1/generate", "/api/v1/tools/upscale"):
                    return self._json(200, faux._creer_job(self.path, corps))
                return self._json(404, {})

        return Gestionnaire

    def _creer_job(self, route: str, corps: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:8]
        if self.statut_final != "completed":
            self.jobs[job_id] = {"status": self.statut_final, "error": self.erreur, "output_files": [], "progress": 0}
        else:
            espace = self.dossier / str(corps.get("workspace") or "defaut")
            espace.mkdir(parents=True, exist_ok=True)
            nom = self._produire(route, corps, espace, job_id)
            if self.lenteur > 0:
                self.jobs[job_id] = {"status": "running", "error": None, "output_files": [nom], "progress": 50, "restants": self.lenteur}
            else:
                self.jobs[job_id] = {"status": "completed", "error": None, "output_files": [nom], "progress": 100}
                self.journal.append(("termine", job_id))
        return {"job_id": job_id, "status": "queued"}

    def _produire(self, route: str, corps: dict[str, Any], espace: Path, job_id: str) -> str:
        exe = ffmpeg.trouver("ffmpeg")
        if route == "/api/v1/tools/upscale":
            nom = f"upscale-{job_id}.mp4"
            shutil.copyfile(corps["video_path"], espace / nom)
            return nom
        if corps.get("model_type") in ("qwen_image_edit_2511_20B_fp8_lightning_8step", "codex_imagegen"):
            nom = f"image-{job_id}.png"
            (espace / nom).write_bytes(png_uni(8, 8, (200, 120, 60)))
            return nom
        if corps.get("sfx_mode"):
            nom = f"sfx-{job_id}.mp4"
            duree = str(corps.get("duration_seconds", 2))
            subprocess.run(
                [exe, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=64x36:r=24", "-f", "lavfi",
                 "-i", "sine=frequency=330:sample_rate=48000", "-t", duree, "-c:v", "libx264", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", str(espace / nom)],
                check=True, capture_output=True, timeout=60,
            )
            return nom
        images = int(corps["video_length"]) - self.images_en_moins
        couleur = "black" if self.noir else "0x95BAE8"
        nom = f"video-{job_id}.mp4"
        subprocess.run(
            [exe, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={couleur}:s=64x36:r=24", "-frames:v", str(images),
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(espace / nom)],
            check=True, capture_output=True, timeout=60,
        )
        return nom
