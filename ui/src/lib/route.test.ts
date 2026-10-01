import { describe, expect, it } from "vitest"

import { lireRoute, versHash, type Route } from "./route"

describe("routes", () => {
  it("lit chaque page", () => {
    expect(lireRoute("")).toEqual({ page: "projets" })
    expect(lireRoute("#/projets")).toEqual({ page: "projets" })
    expect(lireRoute("#/projets/demo-nuit-blanche")).toEqual({ page: "projet", projetId: "demo-nuit-blanche", etape: null })
    expect(lireRoute("#/projets/p1/ecriture")).toEqual({ page: "projet", projetId: "p1", etape: "ecriture" })
    expect(lireRoute("#/bibliotheque")).toEqual({ page: "bibliotheque" })
    expect(lireRoute("#/recettes")).toEqual({ page: "recettes", recetteId: null })
    expect(lireRoute("#/recettes/recette-clip-nuit")).toEqual({ page: "recettes", recetteId: "recette-clip-nuit" })
    expect(lireRoute("#/file")).toEqual({ page: "file" })
    expect(lireRoute("#/moteurs")).toEqual({ page: "moteurs" })
  })

  it("retombe sur les projets pour une adresse inconnue ou malformée", () => {
    expect(lireRoute("#/inconnue")).toEqual({ page: "projets" })
    expect(lireRoute("#/projets/%E0%A4%A")).toEqual({ page: "projets" })
  })

  it("fait l'aller-retour, identifiants encodés compris", () => {
    const routes: Route[] = [
      { page: "projets" },
      { page: "projet", projetId: "a b/c", etape: null },
      { page: "projet", projetId: "p1", etape: "prompts" },
      { page: "bibliotheque" },
      { page: "recettes", recetteId: null },
      { page: "recettes", recetteId: "r-1" },
      { page: "file" },
      { page: "moteurs" },
    ]
    for (const route of routes) expect(lireRoute(versHash(route))).toEqual(route)
  })
})
