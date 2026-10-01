import { describe, expect, it } from "vitest"

import { definitionsDuFormulaire, h3Interroge } from "./rendu"

describe("definitionsDuFormulaire", () => {
  it("transmet les quatre définitions H3 telles quelles", () => {
    for (const h3 of ["480p", "544p", "720p", "1080p"]) {
      expect(definitionsDuFormulaire({ rendu: { h3 } }).h3).toBe(h3)
    }
  })
  it("retombe sur 544p si la valeur manque ou est inconnue", () => {
    expect(definitionsDuFormulaire({}).h3).toBe("544p")
    expect(definitionsDuFormulaire({ rendu: { h3: "4k" } }).h3).toBe("544p")
  })
})

describe("h3Interroge", () => {
  it("envoie la définition permise", () => {
    expect(h3Interroge("720p", ["480p", "544p", "720p"])).toBe("720p")
  })
  it("avant lecture des permises, n'envoie que 480p et 544p (permises sur toute carte à partir de 12 Go)", () => {
    expect(h3Interroge("480p", undefined)).toBe("480p")
    expect(h3Interroge("544p", undefined)).toBe("544p")
    expect(h3Interroge("720p", undefined)).toBeUndefined()
    expect(h3Interroge("1080p", undefined)).toBeUndefined()
  })
  it("n'envoie pas une définition non permise (évite le 422)", () => {
    expect(h3Interroge("1080p", ["480p", "544p"])).toBeUndefined()
  })
})
