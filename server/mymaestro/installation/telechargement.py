"""Téléchargement repris (Range), vérifié (taille, sha256) et annulable, sans dépendance externe."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import os
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from mymaestro.installation.manifeste import FichierManifeste


T = TypeVar("T")


class ErreurInstallation(RuntimeError):
    """Échec d'une étape d'installation : message lisible, affiché dans l'écran « Moteurs »."""


class InstallationAnnulee(ErreurInstallation):
    """Annulation demandée (bouton « Annuler » ou fermeture de MyMaestro)."""


def espace_libre_mo(dossier: Path) -> int:
    """Espace libre du disque qui porte `dossier` (le premier parent existant), en Mo."""
    courant = dossier.resolve()
    while not courant.exists() and courant.parent != courant:
        courant = courant.parent
    return shutil.disk_usage(courant).free // (1024 * 1024)


def _annulation(fichier: FichierManifeste) -> InstallationAnnulee:
    return InstallationAnnulee(f"installation annulée pendant le téléchargement de {fichier.nom}")


def _empreinte(chemin: Path, annule: threading.Event, fichier: FichierManifeste) -> str:
    condensat = hashlib.sha256()
    with chemin.open("rb") as flux:
        for bloc in iter(lambda: flux.read(1024 * 1024), b""):
            if annule.is_set():
                raise _annulation(fichier)
            condensat.update(bloc)
    return condensat.hexdigest()


def _conforme(chemin: Path, fichier: FichierManifeste, annule: threading.Event) -> bool:
    if fichier.taille is not None and chemin.stat().st_size != fichier.taille:
        return False
    if fichier.sha256 is not None and _empreinte(chemin, annule, fichier).lower() != fichier.sha256.lower():
        return False
    return True


def _sans_bloquer(appel: Callable[[], T], annule: threading.Event, fichier: FichierManifeste, abandon: Callable[[T], None] | None = None) -> T:
    """Exécute un appel réseau bloquant dans un fil jetable et rend la main dès que `annule` est posé (sans attendre le délai
    du socket). Le fil abandonné finit seul à son délai ; `abandon` reçoit alors son résultat éventuel (pour le refermer)."""
    resultat: dict[str, object] = {}
    fini = threading.Event()

    def lancer() -> None:
        try:
            resultat["valeur"] = appel()
        except BaseException as erreur:  # noqa: BLE001 - relayée à l'appelant
            resultat["erreur"] = erreur
        finally:
            fini.set()

    threading.Thread(target=lancer, daemon=True).start()
    while not fini.wait(0.2):
        if annule.is_set():
            if abandon is not None:

                def nettoyer() -> None:
                    fini.wait()
                    if "valeur" in resultat:
                        abandon(resultat["valeur"])  # type: ignore[arg-type]

                threading.Thread(target=nettoyer, daemon=True).start()
            raise _annulation(fichier)
    if "erreur" in resultat:
        raise resultat["erreur"]  # type: ignore[misc]
    return resultat["valeur"]  # type: ignore[return-value]


@contextlib.contextmanager
def _refermer(reponse: http.client.HTTPResponse):
    """Referme la réponse ; après une annulation, un fil de lecture abandonné tient peut-être le verrou : on ferme en arrière-plan."""
    try:
        yield reponse
    except InstallationAnnulee:
        threading.Thread(target=reponse.close, daemon=True).start()
        raise
    except BaseException:
        reponse.close()  # aucun fil de lecture en cours : la fermeture directe est sûre
        raise
    else:
        reponse.close()


def _supprimer(chemin: Path) -> None:
    try:
        chemin.unlink()
    except FileNotFoundError:
        pass


def _taille_totale(reponse: http.client.HTTPResponse, deja: int, fichier: FichierManifeste) -> int | None:
    """Taille complète du fichier d'après la réponse (Content-Range en 206, Content-Length en 200), sinon le manifeste."""
    contenu_range = reponse.headers.get("Content-Range")
    if reponse.status == 206 and contenu_range and "/" in contenu_range:
        total = contenu_range.rsplit("/", 1)[1].strip()
        if total.isdigit():
            return int(total)
    longueur = reponse.headers.get("Content-Length")
    if reponse.status != 206 and longueur and longueur.isdigit():
        return int(longueur)
    if reponse.status == 206 and longueur and longueur.isdigit():
        return deja + int(longueur)
    return fichier.taille


def telecharger(
    fichier: FichierManifeste,
    destination: Path,
    progression: Callable[[int, int | None], None],
    annule: threading.Event,
    *,
    bloc: int = 1024 * 1024,
    delai_s: float = 60,
) -> Path:
    """Télécharge `fichier.url` vers `destination` en passant par `destination + ".partiel"` :
    - reprend un `.partiel` existant par `Range: bytes=<taille>-` (réponse 206) ; si le serveur rend 200, repart de zéro ;
    - appelle `progression(octets_recus, taille_totale)` au plus une fois par bloc ;
    - vérifie la taille (si connue) puis le sha256 (si connu) ; en cas d'écart, supprime le `.partiel` et lève
      ErreurInstallation (« empreinte inattendue pour <nom> ») ;
    - `annule` posé : lève InstallationAnnulee en gardant le `.partiel` (reprise possible) ;
    - renomme `.partiel` en `destination` seulement après vérification ; un fichier final déjà présent et vérifié n'est pas
      retéléchargé."""
    if destination.exists():
        # Le fichier final n'existe qu'après vérification : sans empreinte ni taille connues, on s'y fie.
        if _conforme(destination, fichier, annule):
            return destination
        _supprimer(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partiel = destination.with_name(destination.name + ".partiel")

    deja = partiel.stat().st_size if partiel.exists() else 0
    if fichier.taille is not None and deja > fichier.taille:
        _supprimer(partiel)
        deja = 0

    if not (fichier.taille is not None and deja == fichier.taille and deja > 0):
        _transferer(fichier, partiel, deja, progression, annule, bloc, delai_s)

    if not _conforme(partiel, fichier, annule):
        _supprimer(partiel)
        raise ErreurInstallation(f"empreinte inattendue pour {fichier.nom} (téléchargement depuis {fichier.url})")
    os.replace(partiel, destination)
    return destination


def _transferer(
    fichier: FichierManifeste,
    partiel: Path,
    deja: int,
    progression: Callable[[int, int | None], None],
    annule: threading.Event,
    bloc: int,
    delai_s: float,
) -> None:
    entetes = {"User-Agent": "MyMaestro-installeur"}
    if deja > 0:
        entetes["Range"] = f"bytes={deja}-"
    requete = urllib.request.Request(fichier.url, headers=entetes)
    try:
        reponse = _sans_bloquer(
            lambda: urllib.request.urlopen(requete, timeout=delai_s), annule, fichier, abandon=lambda r: r.close()
        )
    except InstallationAnnulee:
        raise
    except urllib.error.HTTPError as erreur:
        if annule.is_set():
            raise _annulation(fichier) from erreur
        if erreur.code == 416 and deja > 0:  # plage hors fichier : le partiel est inutilisable, on repart de zéro
            _supprimer(partiel)
            return _transferer(fichier, partiel, 0, progression, annule, bloc, delai_s)
        raise ErreurInstallation(f"téléchargement impossible : {fichier.url} (HTTP {erreur.code})") from erreur
    except (urllib.error.URLError, OSError, http.client.HTTPException) as erreur:
        if annule.is_set():
            raise _annulation(fichier) from erreur
        raise ErreurInstallation(f"téléchargement impossible : {fichier.url} ({erreur})") from erreur

    try:
        with _refermer(reponse):
            if reponse.status == 206:
                mode = "ab"
                recus = deja
            else:  # 200 : le serveur ignore Range, on repart de zéro
                mode = "wb"
                recus = 0
            total = _taille_totale(reponse, deja if reponse.status == 206 else 0, fichier)
            with partiel.open(mode) as sortie:
                while True:
                    if annule.is_set():
                        raise _annulation(fichier)
                    donnees = _sans_bloquer(lambda: reponse.read(bloc), annule, fichier)
                    if not donnees:
                        break
                    sortie.write(donnees)
                    recus += len(donnees)
                    progression(recus, total)
    except InstallationAnnulee:
        raise
    except (urllib.error.URLError, OSError, http.client.HTTPException) as erreur:
        if annule.is_set():
            raise _annulation(fichier) from erreur
        raise ErreurInstallation(f"téléchargement interrompu : {fichier.url} ({erreur})") from erreur

    if total is not None and recus < total:
        raise ErreurInstallation(f"téléchargement interrompu : {fichier.url} ({recus} octets reçus sur {total})")
