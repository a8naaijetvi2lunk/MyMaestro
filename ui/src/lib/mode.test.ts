import { afterEach, describe, expect, it, vi } from "vitest"

import { appliquerMode, lireMode } from "./mode"

function stockage(initial: Record<string, string> = {}) {
  const donnees = new Map(Object.entries(initial))
  return {
    donnees,
    getItem: (cle: string) => donnees.get(cle) ?? null,
    setItem: (cle: string, valeur: string) => {
      donnees.set(cle, valeur)
    },
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("mode d'affichage", () => {
  it("est clair par défaut", () => {
    vi.stubGlobal("localStorage", stockage())
    expect(lireMode()).toBe("clair")
  })

  it("relit le mode sombre mémorisé", () => {
    vi.stubGlobal("localStorage", stockage({ "mymaestro.mode": "sombre" }))
    expect(lireMode()).toBe("sombre")
  })

  it("reste clair si le stockage est inaccessible", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("bloqué")
      },
    })
    expect(lireMode()).toBe("clair")
  })

  it("pose le mode sur <html> et le mémorise", () => {
    const memoire = stockage()
    const racine = { dataset: {} as Record<string, string> }
    vi.stubGlobal("localStorage", memoire)
    vi.stubGlobal("document", { documentElement: racine })
    appliquerMode("sombre")
    expect(racine.dataset.mode).toBe("dark")
    expect(memoire.donnees.get("mymaestro.mode")).toBe("sombre")
    appliquerMode("clair")
    expect(racine.dataset.mode).toBe("light")
  })
})
