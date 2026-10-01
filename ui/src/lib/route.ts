/** Routes de l'interface, portées par le fragment d'adresse (#/…) : rechargeables, sans dépendance. */
export type Route =
  | { page: "projets" }
  | { page: "projet"; projetId: string; etape: string | null }
  | { page: "bibliotheque" }
  | { page: "recettes"; recetteId: string | null }
  | { page: "file" }
  | { page: "moteurs" }

export function lireRoute(hash: string): Route {
  let morceaux: string[]
  try {
    morceaux = hash
      .replace(/^#\/?/, "")
      .split("/")
      .filter(Boolean)
      .map((morceau) => decodeURIComponent(morceau))
  } catch {
    return { page: "projets" }
  }
  switch (morceaux[0]) {
    case "projets":
      return morceaux[1] ? { page: "projet", projetId: morceaux[1], etape: morceaux[2] ?? null } : { page: "projets" }
    case "bibliotheque":
      return { page: "bibliotheque" }
    case "recettes":
      return { page: "recettes", recetteId: morceaux[1] ?? null }
    case "file":
      return { page: "file" }
    case "moteurs":
      return { page: "moteurs" }
    default:
      return { page: "projets" }
  }
}

export function versHash(route: Route): string {
  switch (route.page) {
    case "projets":
      return "#/projets"
    case "projet":
      return route.etape
        ? `#/projets/${encodeURIComponent(route.projetId)}/${encodeURIComponent(route.etape)}`
        : `#/projets/${encodeURIComponent(route.projetId)}`
    case "bibliotheque":
      return "#/bibliotheque"
    case "recettes":
      return route.recetteId ? `#/recettes/${encodeURIComponent(route.recetteId)}` : "#/recettes"
    case "file":
      return "#/file"
    case "moteurs":
      return "#/moteurs"
  }
}
