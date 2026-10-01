import { describe, expect, it } from "vitest"

import { messageApi, urlMedia } from "./requetes"

describe("messages d'erreur de l'API", () => {
  it("reprend le détail textuel", () => {
    expect(messageApi({ detail: "Projet introuvable" }, 404)).toBe("Projet introuvable")
  })

  it("résume les erreurs de validation", () => {
    expect(messageApi({ detail: [{ msg: "valeur invalide" }, { msg: "champ requis" }] }, 422)).toBe(
      "valeur invalide ; champ requis",
    )
  })

  it("retombe sur le code HTTP", () => {
    expect(messageApi(undefined, 500)).toBe("Erreur 500")
  })
})

describe("adresse d'un média", () => {
  it("encode chaque segment et ajoute la version", () => {
    expect(urlMedia("bibliotheque/fiche lina/a.png")).toBe("/api/medias/bibliotheque/fiche%20lina/a.png")
    expect(urlMedia("bibliotheque/f/a.png", 2)).toBe("/api/medias/bibliotheque/f/a.png?v=2")
  })
})
