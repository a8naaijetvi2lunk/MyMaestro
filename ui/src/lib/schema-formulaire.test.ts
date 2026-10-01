import { describe, expect, it } from "vitest"

import { construireGroupe, ecrireValeur, fusionner, lireValeur, type SchemaJson } from "./schema-formulaire"

const SCHEMA: SchemaJson = {
  title: "ReglagesDirector",
  type: "object",
  "x-titre-general": "Rendu",
  properties: {
    format: {
      $ref: "#/$defs/FormatImage",
      default: "16:9",
      title: "Format",
      "x-controle": "segments",
      "x-libelles": { "16:9": "16:9 · paysage", "9:16": "9:16 · vertical" },
    },
    arrets: { $ref: "#/$defs/Arrets", title: "Arrêts pour validation" },
    llm: { $ref: "#/$defs/Llm", title: "Modèles de langage" },
  },
  $defs: {
    FormatImage: { enum: ["16:9", "9:16"], title: "FormatImage", type: "string" },
    Arrets: {
      description: "Vidéo en autonomie.",
      title: "Arrets",
      type: "object",
      properties: { analyse: { default: false, title: "Après l'analyse", type: "boolean" } },
    },
    Effort: { enum: ["low", "high"], title: "Effort", type: "string" },
    Llm: { title: "Llm", type: "object", properties: { ecriture: { $ref: "#/$defs/Ecriture", title: "Écriture" } } },
    Ecriture: {
      title: "Ecriture",
      type: "object",
      properties: {
        fournisseur: {
          const: "claude",
          default: "claude",
          title: "Fournisseur",
          type: "string",
          "x-controle": "fige",
          "x-libelles": { claude: "Claude" },
        },
        effort: { $ref: "#/$defs/Effort", default: "high", title: "Effort de réflexion", "x-libelles": { low: "Faible", high: "Élevé" } },
        nombre_concepts: { default: 3, maximum: 5, minimum: 1, title: "Concepts proposés au départ", type: "integer" },
        intensite: { default: 1, maximum: 2, minimum: 0, title: "Intensité", type: "number" },
        modele: { default: "sonnet", title: "Modèle", type: "string" },
      },
    },
  },
}

describe("construireGroupe", () => {
  const racine = construireGroupe(SCHEMA)

  it("garde les champs simples à la racine et fait un groupe par objet", () => {
    expect(racine.champs.map((c) => c.chemin.join("."))).toEqual(["format"])
    expect(racine.groupes.map((g) => g.titre)).toEqual(["Arrêts pour validation", "Modèles de langage"])
    expect(racine.groupes[0].description).toBe("Vidéo en autonomie.")
    expect(racine.groupes[1].groupes[0].titre).toBe("Écriture")
  })

  it("choisit le contrôle selon le type et les annotations", () => {
    expect(racine.champs[0].controle).toEqual({
      type: "segments",
      options: [
        { valeur: "16:9", libelle: "16:9 · paysage" },
        { valeur: "9:16", libelle: "9:16 · vertical" },
      ],
    })
    expect(racine.groupes[0].champs[0].controle).toEqual({ type: "case" })
    const ecriture = racine.groupes[1].groupes[0]
    const parCle = Object.fromEntries(ecriture.champs.map((c) => [c.chemin[c.chemin.length - 1], c.controle]))
    expect(parCle.fournisseur).toEqual({ type: "fige", libelles: { claude: "Claude" } })
    expect(parCle.effort).toEqual({
      type: "liste",
      options: [
        { valeur: "low", libelle: "Faible" },
        { valeur: "high", libelle: "Élevé" },
      ],
    })
    expect(parCle.nombre_concepts).toEqual({ type: "nombre", min: 1, max: 5 })
    expect(parCle.intensite).toEqual({ type: "curseur", min: 0, max: 2, pas: 0.1 })
    expect(parCle.modele).toEqual({ type: "texte" })
  })
})

describe("valeurs", () => {
  it("lit et écrit sans muter", () => {
    const valeurs = { llm: { ecriture: { effort: "high" } } }
    const modifiees = ecrireValeur(valeurs, ["llm", "ecriture", "effort"], "low")
    expect(lireValeur(modifiees, ["llm", "ecriture", "effort"])).toBe("low")
    expect(valeurs.llm.ecriture.effort).toBe("high")
    expect(lireValeur(valeurs, ["absent", "x"])).toBeUndefined()
  })

  it("complète des valeurs partielles avec les défauts", () => {
    const defauts = { arrets: { analyse: false, images: true }, format: "16:9" }
    expect(fusionner(defauts, { arrets: { analyse: true } })).toEqual({
      arrets: { analyse: true, images: true },
      format: "16:9",
    })
  })
})
