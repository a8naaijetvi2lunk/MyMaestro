"""Téléchargement repris (Range), vérifié (taille, sha256) et annulable."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest

from mymaestro.installation import telechargement as t
from mymaestro.installation.manifeste import FichierManifeste
from tests.faux_serveur_fichiers import FauxServeurFichiers

CONTENU = bytes(range(256)) * 400  # 102 400 octets
BLOC = 4096


def _fichier(url: str, contenu: bytes = CONTENU, *, sha256: str | None = None, taille: int | None = None) -> FichierManifeste:
    return FichierManifeste(
        nom="fichier.bin",
        url=url,
        taille=len(contenu) if taille is None else taille,
        sha256=hashlib.sha256(contenu).hexdigest() if sha256 is None else sha256,
        controles_contenu={},
    )


def _rien(recus: int, total: int | None) -> None:
    pass


def test_telechargement_complet(tmp_path: Path) -> None:
    destination = tmp_path / "sortie" / "fichier.bin"
    with FauxServeurFichiers(CONTENU) as serveur:
        resultat = t.telecharger(_fichier(serveur.url), destination, _rien, threading.Event(), bloc=BLOC)
    assert resultat == destination
    assert destination.read_bytes() == CONTENU
    assert not destination.with_name("fichier.bin.partiel").exists()


def test_coupure_puis_reprise_par_range(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    with FauxServeurFichiers(CONTENU) as serveur:
        serveur.couper_apres = 30_000
        fichier = _fichier(serveur.url)
        with pytest.raises(t.ErreurInstallation):
            t.telecharger(fichier, destination, _rien, threading.Event(), bloc=BLOC)
        partiel = destination.with_name("fichier.bin.partiel")
        assert partiel.exists()
        assert 0 < partiel.stat().st_size < len(CONTENU)
        taille_partielle = partiel.stat().st_size
        t.telecharger(fichier, destination, _rien, threading.Event(), bloc=BLOC)
        assert serveur.requetes[-1]["range"] == f"bytes={taille_partielle}-"
    assert destination.read_bytes() == CONTENU
    assert not partiel.exists()


def test_serveur_qui_ignore_range_repart_de_zero(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    with FauxServeurFichiers(CONTENU) as serveur:
        serveur.couper_apres = 30_000
        fichier = _fichier(serveur.url)
        with pytest.raises(t.ErreurInstallation):
            t.telecharger(fichier, destination, _rien, threading.Event(), bloc=BLOC)
        serveur.ignorer_range = True
        t.telecharger(fichier, destination, _rien, threading.Event(), bloc=BLOC)
    assert destination.read_bytes() == CONTENU


def test_empreinte_fausse_supprime_le_partiel(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    with FauxServeurFichiers(CONTENU) as serveur:
        serveur.corrompu = True
        with pytest.raises(t.ErreurInstallation, match="empreinte inattendue pour fichier.bin"):
            t.telecharger(_fichier(serveur.url), destination, _rien, threading.Event(), bloc=BLOC)
    assert not destination.exists()
    assert not destination.with_name("fichier.bin.partiel").exists()


def test_annulation_conserve_le_partiel(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    annule = threading.Event()

    def progression(recus: int, total: int | None) -> None:
        if recus >= 2 * BLOC:
            annule.set()

    with FauxServeurFichiers(CONTENU) as serveur:
        with pytest.raises(t.InstallationAnnulee):
            t.telecharger(_fichier(serveur.url), destination, progression, annule, bloc=BLOC)
    assert not destination.exists()
    partiel = destination.with_name("fichier.bin.partiel")
    assert partiel.exists() and partiel.stat().st_size >= 2 * BLOC


def test_annulation_pendant_un_silence_du_serveur(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    annule = threading.Event()
    with FauxServeurFichiers(CONTENU) as serveur:
        serveur.se_taire_apres = 4096
        threading.Timer(0.5, annule.set).start()
        debut = time.monotonic()
        with pytest.raises(t.InstallationAnnulee):
            t.telecharger(_fichier(serveur.url), destination, _rien, annule, bloc=BLOC, delai_s=10)
        assert time.monotonic() - debut < 3
    assert destination.with_name("fichier.bin.partiel").exists()


def test_annulation_pendant_le_calcul_d_empreinte(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    destination.write_bytes(CONTENU)
    annule = threading.Event()
    annule.set()
    fichier = _fichier("http://127.0.0.1:1/jamais", sha256="0" * 64)
    with pytest.raises(t.InstallationAnnulee):
        t.telecharger(fichier, destination, _rien, annule)
    assert destination.exists()


def test_fichier_final_deja_verifie_aucune_requete(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    destination.write_bytes(CONTENU)
    with FauxServeurFichiers(CONTENU) as serveur:
        t.telecharger(_fichier(serveur.url), destination, _rien, threading.Event(), bloc=BLOC)
        assert serveur.requetes == []
    assert destination.read_bytes() == CONTENU


def test_404_mentionne_l_url(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    with FauxServeurFichiers(CONTENU) as serveur:
        serveur.repondre_404 = True
        with pytest.raises(t.ErreurInstallation) as erreur:
            t.telecharger(_fichier(serveur.url), destination, _rien, threading.Event(), bloc=BLOC)
    assert serveur.url in str(erreur.value)
    assert not destination.exists()


def test_progression_croissante(tmp_path: Path) -> None:
    destination = tmp_path / "fichier.bin"
    appels: list[tuple[int, int | None]] = []
    with FauxServeurFichiers(CONTENU) as serveur:
        t.telecharger(_fichier(serveur.url), destination, lambda r, tot: appels.append((r, tot)), threading.Event(), bloc=BLOC)
    recus = [r for r, _ in appels]
    assert recus == sorted(recus) and len(set(recus)) == len(recus)
    assert recus[-1] == len(CONTENU)
    assert len(appels) <= len(CONTENU) // BLOC + 1
    assert all(total == len(CONTENU) for _, total in appels)


def test_espace_libre_mo(tmp_path: Path) -> None:
    assert t.espace_libre_mo(tmp_path) > 0
    assert t.espace_libre_mo(tmp_path / "n" / "existe" / "pas") > 0
