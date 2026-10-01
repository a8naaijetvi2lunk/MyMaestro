import { describe, expect, it } from "vitest"

import { compterParType, filtrerFiches, normaliser } from "./bibliotheque"

const FICHES = [
  { type: "personnage", nom: "Lina", description: "Chanteuse, veste en cuir" },
  { type: "decor", nom: "Toit-terrasse de nuit", description: "Antennes" },
  { type: "style", nom: "Néon pluvieux", description: "Reflets humides" },
]

describe("bibliothèque", () => {
  it("normalise casse et accents", () => {
    expect(normaliser("Néon PLUVIEUX")).toBe("neon pluvieux")
  })

  it("filtre par type et par recherche", () => {
    expect(filtrerFiches(FICHES, "tout", "").map((f) => f.nom)).toHaveLength(3)
    expect(filtrerFiches(FICHES, "decor", "").map((f) => f.nom)).toEqual(["Toit-terrasse de nuit"])
    expect(filtrerFiches(FICHES, "tout", "neon").map((f) => f.nom)).toEqual(["Néon pluvieux"])
    expect(filtrerFiches(FICHES, "tout", "  CUIR ").map((f) => f.nom)).toEqual(["Lina"])
    expect(filtrerFiches(FICHES, "style", "lina")).toEqual([])
  })

  it("compte les fiches par type", () => {
    expect(compterParType(FICHES)).toEqual({ personnage: 1, decor: 1, style: 1 })
  })
})
