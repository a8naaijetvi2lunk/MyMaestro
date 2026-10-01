import json
import math
import struct
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from mymaestro.outils import ffmpeg, gpu, http, synchro


def test_parser_vram_premiere_ligne():
    assert gpu.parser_vram("3350, 12282\n") == (3350, 12282)
    assert gpu.parser_vram(" 100 , 200 \n 5, 6") == (100, 200)


def test_echantillonneur_releve_le_pic():
    valeurs = iter([1000, 5000, 3000] + [2000] * 1000)
    with gpu.EchantillonneurVram(intervalle_s=0.01, lecteur=lambda: (next(valeurs), 12000)) as vram:
        limite = time.monotonic() + 2
        while len(vram.releves) < 4 and time.monotonic() < limite:
            time.sleep(0.01)
    assert vram.pic_mo == 5000


class _Gestionnaire(BaseHTTPRequestHandler):
    def _repondre(self, corps: dict) -> None:
        donnees = json.dumps(corps).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def do_GET(self):  # noqa: N802 — nom imposé par http.server
        self._repondre({"chemin": self.path})

    def do_POST(self):  # noqa: N802
        longueur = int(self.headers.get("Content-Length", "0"))
        self._repondre({"recu": json.loads(self.rfile.read(longueur) or b"{}")})

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def serveur_local():
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), _Gestionnaire)
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    yield f"http://127.0.0.1:{serveur.server_address[1]}"
    serveur.shutdown()


def test_http_get_post_et_attente(serveur_local):
    assert http.get_json(f"{serveur_local}/api/v1/jobs") == {"chemin": "/api/v1/jobs"}
    assert http.post_json(f"{serveur_local}/x", {"a": 1}) == {"recu": {"a": 1}}
    assert http.attendre(f"{serveur_local}/pret", delai_s=2)
    assert not http.attendre("http://127.0.0.1:9/ferme", delai_s=0.5, intervalle_s=0.1)


def test_synchro_retrouve_un_retard_et_une_avance():
    rng = np.random.default_rng(7)
    reference = rng.standard_normal(16000).astype(np.float32)
    en_retard = np.concatenate([np.zeros(800, dtype=np.float32), reference])[:16000]
    assert synchro.decalage_s(reference, en_retard, 16000) == pytest.approx(0.05, abs=1e-3)
    en_avance = reference[800:]
    assert synchro.decalage_s(reference, en_avance, 16000) == pytest.approx(-0.05, abs=1e-3)
    assert synchro.decalage_s(reference, reference, 16000) == pytest.approx(0.0, abs=1e-3)


def _ecrire_wav(chemin, secondes: float, taux: int = 48000) -> None:
    with wave.open(str(chemin), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(taux)
        echantillons = (int(12000 * math.sin(2 * math.pi * 440 * i / taux)) for i in range(int(secondes * taux)))
        f.writeframes(b"".join(struct.pack("<hh", e, e) for e in echantillons))


def test_ffmpeg_decoupe_sonde_et_decode(tmp_path):
    try:
        ffmpeg.trouver("ffmpeg")
        ffmpeg.trouver("ffprobe")
    except FileNotFoundError:
        pytest.skip("ffmpeg absent")
    source = tmp_path / "source.wav"
    _ecrire_wav(source, 2.0)
    extrait = ffmpeg.decouper_audio(source, 0.5, 1.0, tmp_path / "sortie" / "extrait.wav")
    assert ffmpeg.sonder(extrait)["duree_s"] == pytest.approx(1.0, abs=0.02)
    assert ffmpeg.sonder(extrait)["audio"] is True
    pcm = ffmpeg.lire_pcm_mono(extrait)
    assert abs(pcm.size - 16000) < 50
