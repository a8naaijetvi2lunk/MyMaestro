"""Médias de démonstration générés en Python pur (bibliothèque standard seulement).

Une vitrine sans image cassée ni chanson illisible, sans ffmpeg ni dépendance : un PNG en dégradé
vertical (léger vignettage) et une nappe de synthèse à 118 BPM.
"""

from __future__ import annotations

import math
import struct
import wave
import zlib
from functools import lru_cache
from pathlib import Path

FREQUENCE_HZ = 22_050
BPM = 118
_CRETE = 10 ** (-6 / 20)  # -6 dBFS
_ACCORD_HZ = (220.00, 261.63, 329.63)  # la mineur : la3, do4, mi4
_BLOC_TRAMES = 22_050


def _chunk(type_: bytes, donnees: bytes) -> bytes:
    return struct.pack(">I", len(donnees)) + type_ + donnees + struct.pack(">I", zlib.crc32(type_ + donnees))


@lru_cache(maxsize=32)
def _png(largeur: int, hauteur: int, haut: tuple[int, int, int], bas: tuple[int, int, int]) -> bytes:
    dx2 = [((x / max(largeur - 1, 1) - 0.5) * 2) ** 2 for x in range(largeur)]
    lignes = bytearray()
    for y in range(hauteur):
        t = y / max(hauteur - 1, 1)
        dy2 = ((t - 0.5) * 2) ** 2
        base = [haut[i] + (bas[i] - haut[i]) * t for i in range(3)]
        ligne = bytearray(3 * largeur)
        for canal in range(3):
            # vignettage : 1 - 0,175 (dx² + dy²), de 1 au centre à 0,65 dans les coins
            fixe = base[canal] * (1.0 - 0.175 * dy2)
            pente = base[canal] * 0.175
            ligne[canal::3] = bytes(max(0, min(255, round(fixe - pente * d))) for d in dx2)
        lignes.append(0)  # filtre « aucun »
        lignes += ligne
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(lignes), 6))
        + _chunk(b"IEND", b"")
    )


def ecrire_png_degrade(
    chemin: Path, largeur: int, hauteur: int, haut: tuple[int, int, int], bas: tuple[int, int, int]
) -> None:
    """PNG RGB 8 bits : dégradé vertical de `haut` à `bas`, assombri vers les bords (vignettage)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(_png(largeur, hauteur, tuple(haut), tuple(bas)))


def _bloc(debut: int, fin: int, total: int, fondu: float) -> bytes:
    pas_pulsation = 60.0 / BPM
    bloc = bytearray()
    for i in range(debut, fin):
        t = i / FREQUENCE_HZ
        nappe = sum(math.sin(2 * math.pi * f * t) for f in _ACCORD_HZ) / 3
        nappe += 0.5 * math.sin(2 * math.pi * (_ACCORD_HZ[0] + 0.4) * t) / 3  # battement lent (0,4 Hz)
        nappe *= 0.8 + 0.2 * math.sin(2 * math.pi * 0.1 * t)
        phase = (t % pas_pulsation) / pas_pulsation
        pulsation = 0.3 * math.sin(2 * math.pi * 55 * t) * math.exp(-phase * 14)
        enveloppe = min(1.0, i / fondu, (total - 1 - i) / fondu)
        valeur = (nappe * 0.5 + pulsation) * enveloppe * _CRETE  # |nappe*0,5 + pulsation| < 0,9 : crête sous -6 dBFS
        bloc += struct.pack("<h", max(-32768, min(32767, round(valeur * 32767))))
    return bytes(bloc)


@lru_cache(maxsize=2)
def _chanson(duree_s: float) -> bytes:
    """Les trames de la chanson, calculées une fois par processus (la synthèse en Python pur prend quelques secondes)."""
    total = round(duree_s * FREQUENCE_HZ)
    fondu = max(1.0, min(2.0, duree_s / 4) * FREQUENCE_HZ)
    return b"".join(_bloc(d, min(d + _BLOC_TRAMES, total), total, fondu) for d in range(0, total, _BLOC_TRAMES))


def ecrire_chanson_wav(chemin: Path, duree_s: float = 60.0) -> None:
    """WAV PCM 16 bits mono à 22 050 Hz : nappe de la mineur (battement lent) et pulsation discrète à 118 BPM."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FREQUENCE_HZ)
        donnees = _chanson(float(duree_s))
        for debut in range(0, len(donnees), _BLOC_TRAMES * 2):  # par blocs : jamais une seconde copie géante
            w.writeframes(donnees[debut : debut + _BLOC_TRAMES * 2])
