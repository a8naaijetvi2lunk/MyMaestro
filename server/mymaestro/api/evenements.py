"""Flux SSE des événements de la file (progression en direct, spec §3)."""

from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator

from fastapi.sse import ServerSentEvent

from ..core.ordonnanceur import Bus


async def flux(bus: Bus, delai_s: float, limite: int | None = None) -> AsyncIterator[ServerSentEvent]:
    """Événements du bus, précédés d'un « connecte ». Sans événement pendant `delai_s`, un
    commentaire garde la connexion ouverte ; `limite` borne le nombre d'événements émis (tests)."""
    abonnement = bus.abonner()
    emis = 0
    try:
        yield ServerSentEvent(event="connecte", data={"statut": "ok"})
        emis += 1
        while limite is None or emis < limite:
            try:
                evenement = await asyncio.to_thread(abonnement.get, True, delai_s)
            except queue.Empty:
                yield ServerSentEvent(comment="toujours là")
                continue
            yield ServerSentEvent(event=str(evenement.get("type", "evenement")), data=evenement)
            emis += 1
    finally:
        bus.desabonner(abonnement)
