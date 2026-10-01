"""Application FastAPI de MyMaestro."""

from __future__ import annotations

import logging
import math
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__, config, modules
from .api import routes
from .connectors.base import Connecteur
from .connectors.export import ConnecteurExport
from .connectors.registre import prevol_pour, registre
from .contrat.modeles import EtatMoteur
from .core import empreintes, notify
from .core.amorce import amorcer_si_vide
from .core.contexte import Contexte
from .core.db import Base
from .core.file import File
from .core.ordonnanceur import Ordonnanceur
from .installation.service import ServiceInstallation, mode_demo
from .outils import gpu


METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS"})


def origines_autorisees() -> frozenset[str]:
    """L'application elle-même (127.0.0.1 ou localhost sur son port) et le serveur de développement Vite (port 3000)."""
    return frozenset(
        f"http://{hote}:{port}" for hote in ("127.0.0.1", "localhost") for port in (config.PORT, 3000)
    )


class RefusAutreOrigine:
    """Middleware ASGI : une page d'un autre site ne peut pas piloter MyMaestro depuis le navigateur de l'utilisateur
    (le serveur n'écoute que sur 127.0.0.1, mais le navigateur, lui, y accède). Toute requête qui modifie quelque chose
    (hors GET, HEAD, OPTIONS) est refusée (403) si son `Origin` n'est pas autorisé ou si `Sec-Fetch-Site` vaut `cross-site`.
    Les requêtes sans `Origin` (tests, curl) passent."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in METHODES_SURES:
            en_tetes = {cle.decode("latin-1").lower(): valeur.decode("latin-1") for cle, valeur in scope["headers"]}
            origine = en_tetes.get("origin")
            if (origine is not None and origine not in origines_autorisees()) or en_tetes.get("sec-fetch-site") == "cross-site":
                reponse = JSONResponse(status_code=403, content={"detail": "Requête d'une autre origine refusée"})
                await reponse(scope, receive, send)
                return
        await self.app(scope, receive, send)


def creer_app(
    chemin_base: Path | str | None = None,
    servir_ui: bool = False,
    connecteurs: Mapping[str, Connecteur] | None = None,
    demarrer_file: bool = False,
    delai_sse_s: float = 15.0,
    dossier_medias: Path | None = None,
    dossier_projets: Path | None = None,
) -> FastAPI:
    """Construit l'application.

    `chemin_base` : ':memory:' pour les tests. `servir_ui` : sert ui/dist (repli SPA de FastAPI 0.142).
    `connecteurs` : moteurs pilotés (par défaut `connectors.registre.registre(...)` : réels selon `MYMAESTRO_MOTEURS_REELS`,
    les cinq moteurs par défaut (`maestro,codex,dlss5,bonsai,claude`), « aucun » pour tout simuler). `demarrer_file` : lance les
    fils de l'ordonnanceur au démarrage ; les tests le pilotent pas à pas avec `vider()`.
    `dossier_medias` : racine des médias servis (tests : dossier temporaire).
    `dossier_projets` : dossier des médias des projets (tests : dossier temporaire).
    """
    cible = config.CHEMIN_BASE if chemin_base is None else chemin_base

    @asynccontextmanager
    async def cycle_de_vie(app: FastAPI) -> AsyncIterator[None]:
        config.ecrire_config_par_defaut()
        base = Base(cible)
        dossier = Path(dossier_projets) if dossier_projets is not None else config.DOSSIER_PROJETS
        amorcer_si_vide(base, dossier, app.state.medias)
        file = File(base)
        moteurs = dict(
            connecteurs
            if connecteurs is not None
            else registre(empreintes.charger(), modules.repondeur_simule(dossier))
        )
        moteurs.setdefault("export", ConnecteurExport())  # montage ffmpeg local : toujours réel
        # Moteurs simulés tolérés : connecteurs fournis par l'appelant (tests) ou mode démo, figé au démarrage.
        ordonnanceur = Ordonnanceur(
            file, moteurs, simule_autorise=connecteurs is not None or mode_demo(), vram_totale_mo=gpu.vram_mo()
        )
        installation = ServiceInstallation(publier=ordonnanceur.bus.publier)
        contexte = Contexte(base=base, file=file, dossier_projets=dossier, publier=ordonnanceur.bus.publier, dossier_medias=app.state.medias, prevol=prevol_pour(moteurs, demo=True if connecteurs is not None else None), notifier=notify.notifier_windows if sys.platform == "win32" else notify.sans_notification)
        file.rappels.append(lambda job: modules.apres_job(contexte, job))
        file.reprendre_apres_crash()
        app.state.base = base
        app.state.db = base.connexion
        app.state.file = file
        app.state.ordonnanceur = ordonnanceur
        app.state.contexte = contexte
        app.state.installation = installation
        app.state.delai_sse_s = delai_sse_s
        if demarrer_file:
            ordonnanceur.lancer()
        try:
            yield
        finally:
            installation.arreter()
            ordonnanceur.arreter()
            file.suspendre_en_cours()
            for moteur in moteurs.values():
                if not moteur.simule and moteur.etat is not EtatMoteur.ARRETE:
                    try:
                        moteur.arreter_sans_attendre()  # moteur réel démarré : ne pas le laisser tenir la VRAM après MyMaestro
                    except Exception:  # noqa: BLE001 — la fermeture continue
                        logging.getLogger("mymaestro").exception("arrêt du moteur %s en erreur", moteur.nom)
            base.fermer()

    app = FastAPI(title="MyMaestro", version=__version__, lifespan=cycle_de_vie)
    app.add_middleware(RefusAutreOrigine)
    app.state.medias = Path(dossier_medias) if dossier_medias is not None else config.DOSSIER_MEDIAS
    @app.exception_handler(RequestValidationError)
    async def refus_de_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        """422 habituel de FastAPI, sans renvoyer un flottant infini ou NaN (non sérialisable en JSON : ce serait un 500)."""
        erreurs = [
            {cle: valeur for cle, valeur in erreur.items() if not (cle == "input" and isinstance(valeur, float) and not math.isfinite(valeur))}
            for erreur in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(erreurs)})

    app.include_router(routes.routeur)
    for routeur_module in modules.ROUTEURS:
        app.include_router(routeur_module)
    if servir_ui:
        app.frontend("/", directory=config.DOSSIER_UI, fallback="index.html", check_dir=False)
    return app


app = creer_app(servir_ui=True, demarrer_file=True)
