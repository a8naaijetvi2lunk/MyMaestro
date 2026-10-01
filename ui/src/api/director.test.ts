import { describe, expect, it } from "vitest"

import { urlMediaProjet } from "./director"

describe("urlMediaProjet", () => {
  it("n'ajoute pas de version par défaut", () => {
    expect(urlMediaProjet("p 1", "chanson.wav")).toBe("/api/projets/p%201/medias/chanson.wav")
  })

  it("ajoute la version pour forcer le rechargement d'un média remplacé", () => {
    expect(urlMediaProjet("p1", "chanson.wav", 2)).toBe("/api/projets/p1/medias/chanson.wav?v=2")
  })
})
