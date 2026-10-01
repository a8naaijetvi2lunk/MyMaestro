import { describe, expect, it } from "vitest"

import {
  aimanter,
  aimanterPlacement,
  appliquerGeste,
  chevauche,
  compterMots,
  fichierDePrise,
  formatHorloge,
  formatTaille,
  graduations,
  libelleAction,
  libelleEtatClip,
  libellePiste,
  segmentAuTemps,
  zoomInitial,
} from "./timeline"

describe("échelle et graduations", () => {
  it("fait tenir la chanson dans la largeur, dans les bornes du zoom", () => {
    expect(zoomInitial(60)).toBeCloseTo(17.6)
    expect(zoomInitial(0)).toBe(20)
    expect(zoomInitial(10000)).toBe(4)
  })

  it("choisit un pas lisible", () => {
    const reperes = graduations(60, 17.6)
    expect(reperes.slice(0, 3).map((r) => r.libelle)).toEqual(["0:00", "0:05", "0:10"])
    expect(reperes).toHaveLength(13)
    expect(graduations(600, 4)).toHaveLength(41)
    expect(formatHorloge(65)).toBe("1:05")
  })
})

describe("magnétisme", () => {
  it("colle au repère le plus proche sous le seuil", () => {
    expect(aimanter(10.07, [10, 10.5], 0.1)).toBe(10)
    expect(aimanter(10.3, [10, 10.5], 0.1)).toBe(10.3)
  })

  it("colle le bord déplacé par le geste", () => {
    const placement = { position_s: 2, entree_s: 0, sortie_s: 9.95 }
    expect(aimanterPlacement(placement, "rogner-fin", [12], 0.1, null).sortie_s).toBeCloseTo(10)
    expect(aimanterPlacement(placement, "rogner-fin", [12], 0.1, 9.96).sortie_s).toBe(9.95)
    expect(aimanterPlacement(placement, "deplacer", [2.04], 0.1, null).position_s).toBe(2.04)
    const rogne = aimanterPlacement({ position_s: 5.02, entree_s: 1.02, sortie_s: 9 }, "rogner-debut", [5], 0.1, null)
    expect(rogne.position_s).toBe(5)
    expect(rogne.entree_s).toBeCloseTo(1)
  })

  it("refuse un aimant qui laisserait moins d'une image", () => {
    // Le repère 15 amènerait l'entrée à 4,9 s, soit la sortie : zéro image restante.
    const placement = { position_s: 14.9583, entree_s: 4.8583, sortie_s: 4.9 }
    expect(aimanterPlacement(placement, "rogner-debut", [15], 0.45, 4.9, 24)).toEqual(placement)
    // Avec 0,3 s restantes, l'aimant reste permis.
    expect(aimanterPlacement({ ...placement, sortie_s: 5.2 }, "rogner-debut", [15], 0.45, 5.2, 24).position_s).toBe(15)
  })
})

describe("gestes de montage", () => {
  const ancre = { id: "c", piste: "V1", position_s: 4.84, entree_s: 0, sortie_s: 10.125, verrou_chanson: true }

  it("un plan ancré ne se déplace pas mais se rogne en gardant sa synchro", () => {
    expect(appliquerGeste(ancre, "deplacer", 1, 10.125, 24)).toBeNull()
    const rogne = appliquerGeste(ancre, "rogner-debut", 1, 10.125, 24)
    expect(rogne?.entree_s).toBeCloseTo(1)
    expect((rogne?.position_s ?? 0) - (rogne?.entree_s ?? 0)).toBeCloseTo(4.84)
    expect(appliquerGeste(ancre, "rogner-debut", -3, 10.125, 24)).toEqual({ position_s: 4.84, entree_s: 0, sortie_s: 10.125 })
  })

  it("un clip libre reste dans la chanson et dans sa source", () => {
    const libre = { ...ancre, id: "d", verrou_chanson: false, position_s: 2 }
    expect(appliquerGeste(libre, "deplacer", -5, null, 24)?.position_s).toBe(0)
    expect(appliquerGeste(libre, "rogner-fin", 10, 8, 24)?.sortie_s).toBe(8)
    expect(appliquerGeste(libre, "rogner-fin", -100, 8, 24)?.sortie_s).toBeCloseTo(1 / 24)
  })

  it("un clip libre ne se déplace pas au-delà de la fin de la chanson", () => {
    const libre = { ...ancre, id: "d", verrou_chanson: false, position_s: 2, entree_s: 0, sortie_s: 5.2 }
    expect(appliquerGeste(libre, "deplacer", 1000, 5.2, 24, 60)?.position_s ?? Infinity).toBeLessThanOrEqual(60 - 1 / 24)
  })

  it("détecte un chevauchement dans la même piste seulement", () => {
    const clips = [
      { id: "a", piste: "V1", position_s: 0, entree_s: 0, sortie_s: 5, verrou_chanson: false },
      { id: "b", piste: "V1", position_s: 5, entree_s: 0, sortie_s: 5, verrou_chanson: false },
    ]
    expect(chevauche(clips, { ...clips[0], sortie_s: 5.5 })).toBe(true)
    expect(chevauche(clips, { ...clips[0], piste: "V2", sortie_s: 5.5 })).toBe(false)
    expect(chevauche(clips, { ...clips[0], sortie_s: 5 })).toBe(false)
  })
})

describe("projection et libellés", () => {
  it("trouve le segment d'un instant", () => {
    const segments = [{ debut_s: 0, fin_s: 2 }, { debut_s: 2, fin_s: 5 }]
    expect(segmentAuTemps(segments, 2)).toBe(segments[1])
    expect(segmentAuTemps(segments, 5)).toBeNull()
  })

  it("nomme états, pistes et actions", () => {
    expect(libelleEtatClip("en_rendu", 0.42)).toBe("42 %")
    expect(libelleEtatClip("dlss5", null)).toBe("DLSS5")
    expect(libelleEtatClip(null, null)).toBe("—")
    expect([libellePiste("A0"), libellePiste("V2"), libellePiste("A3")]).toEqual(["Chanson", "Vidéo", "Sons"])
    const indices = { "plan-02": 2, "plan-06": 6 }
    expect(libelleAction({ type: "refaire", plan_id: "plan-06", reglages: { moteur: "ltx2_22B_distilled_1_1_omninft" } }, indices)).toBe(
      "Plan 7 · refaire en LTX-2.3",
    )
    expect(libelleAction({ type: "passe_dlss5", plan_id: "plan-02", reglages: { intensite: 0.8 } }, indices)).toBe("Plan 3 · passe DLSS5 0,8")
    expect(libelleAction({ type: "refaire", plan_id: "plan-02", reglages: { a_la_position: true } }, indices)).toBe(
      "Plan 3 · refaire à cette position",
    )
    expect(libelleAction({ type: "bruitage", plan_id: null, reglages: {} }, indices)).toBe("Projet · bruitage")
  })

  it("compte les mots, choisit le fichier d'une prise, affiche une taille", () => {
    expect(compterMots("  un deux\ntrois ")).toBe(3)
    expect(compterMots("")).toBe(0)
    const sorties = [{ id: "s1", statut: "termine", fichier: "prises/p/1-flashvsr.mp4" }]
    expect(fichierDePrise({ statut: "termine", fichier_brut: "prises/p/brut.mp4", sortie_active_id: "s1", sorties })).toBe("prises/p/1-flashvsr.mp4")
    expect(fichierDePrise({ statut: "termine", fichier_brut: "prises/p/brut.mp4", sortie_active_id: null, sorties })).toBe("prises/p/brut.mp4")
    expect(fichierDePrise({ statut: "echec", fichier_brut: null, sortie_active_id: null, sorties: [] })).toBeNull()
    expect(formatTaille(1.2e9)).toBe("1,2 Go")
    expect(formatTaille(3.5e8)).toBe("350 Mo")
  })
})
