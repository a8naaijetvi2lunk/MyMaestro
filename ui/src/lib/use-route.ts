import { useSyncExternalStore } from "react"

import { lireRoute, versHash, type Route } from "./route"

function abonner(rappel: () => void): () => void {
  window.addEventListener("hashchange", rappel)
  return () => window.removeEventListener("hashchange", rappel)
}

function hashCourant(): string {
  return window.location.hash
}

/** Route courante, relue à chaque changement du fragment d'adresse. */
export function useRoute(): Route {
  return lireRoute(useSyncExternalStore(abonner, hashCourant, () => ""))
}

export function naviguer(route: Route): void {
  window.location.hash = versHash(route)
}
