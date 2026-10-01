"""Réglages communs des tests : un dossier de données jetable, jamais le data/ de la machine."""

import os
import tempfile

os.environ["MYMAESTRO_DONNEES"] = tempfile.mkdtemp(prefix="mymaestro-tests-")  # forcé : jamais le data/ réel
os.environ["MYMAESTRO_MOTEURS_REELS"] = "aucun"  # forcé : aucun test ne détecte ni ne lance un moteur réel (mode démo)

import pytest  # noqa: E402

from mymaestro.outils import gpu  # noqa: E402


@pytest.fixture(autouse=True)
def carte_de_reference(monkeypatch):
    """Tous les tests voient la carte de référence : nvidia-smi n'est jamais appelé."""
    gpu.vider_cache()
    monkeypatch.setattr(gpu, "detecter_gpu", lambda: gpu.Gpu("NVIDIA GeForce RTX 4070 Ti", 12282, "nvidia-smi"))
    yield
