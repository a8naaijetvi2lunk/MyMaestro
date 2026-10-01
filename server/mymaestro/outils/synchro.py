"""Mesure de synchro audio par corrélation croisée (principe de scripts/mesure_sync_director.py de Maestro)."""

from __future__ import annotations

import numpy as np


def decalage_s(reference: np.ndarray, signal: np.ndarray, taux: int) -> float:
    """Décalage de `signal` par rapport à `reference`, en secondes. Positif : `signal` est en retard."""
    if reference.size == 0 or signal.size == 0:
        raise ValueError("signal audio vide")
    ref = reference - reference.mean()
    sig = signal - signal.mean()
    taille = 1 << int(np.ceil(np.log2(ref.size + sig.size - 1)))
    correlation = np.fft.irfft(np.fft.rfft(sig, taille) * np.conj(np.fft.rfft(ref, taille)), taille)
    indice = int(np.argmax(correlation))
    if indice > taille // 2:
        indice -= taille
    return indice / taux
