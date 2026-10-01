import { describe, expect, it } from "vitest"

import type { EtatConnecteur, Job } from "@/api/client"

import { departFile, formatGo, grouperParMoteur, ordonnerCommeArbitre, vramTenue } from "./file"

function job(id: string, connecteur: string, modele: string | null): Job {
  return {
    id,
    voie: "gpu",
    connecteur,
    modele,
    statut: "en_file",
    tentatives: 0,
    progression: 0,
    libelle: "",
    erreur: null,
    phase: "video",
    ordre: 0,
    regime: "phases",
    projet_id: null,
  }
}

function moteur(nom: string, etat: EtatConnecteur["etat"], vram: number, residuelle: number): EtatConnecteur {
  return { nom, voie: nom === "claude" ? "cloud" : "gpu", etat, empreinte_vram_mo: vram, vram_residuelle_mo: residuelle, simule: true }
}

describe("file GPU", () => {
  it("regroupe les jobs consécutifs de même moteur et même modèle", () => {
    const groupes = grouperParMoteur([
      job("a", "maestro", "minimax_h3"),
      job("b", "maestro", "minimax_h3"),
      job("c", "maestro", "flashvsr2"),
      job("d", "dlss5", "dlss5"),
      job("e", "maestro", "minimax_h3"),
    ])
    expect(groupes.map((g) => [g.connecteur, g.modele, g.jobs.map((j) => j.id).join("")])).toEqual([
      ["maestro", "minimax_h3", "ab"],
      ["maestro", "flashvsr2", "c"],
      ["dlss5", "dlss5", "d"],
      ["maestro", "minimax_h3", "e"],
    ])
  })

  it("ordonne comme l'arbitre : moteur et modèle courants d'abord, puis plus petit ordre", () => {
    const carte = (id: string, connecteur: string, modele: string, ordre: number): Job => ({
      ...job(id, connecteur, modele),
      regime: "carte",
      phase: null,
      ordre,
    })
    const jobs = [carte("p1h3", "maestro", "minimax_h3", 1), carte("p1d", "dlss5", "dlss5", 2), carte("p2h3", "maestro", "minimax_h3", 3)]
    const apresH3 = ordonnerCommeArbitre(jobs.slice(1), { connecteur: "maestro", modele: "minimax_h3" })
    expect(apresH3.map((j) => j.id)).toEqual(["p2h3", "p1d"])
    const depart = [
      carte("a", "maestro", "minimax_h3", 1),
      carte("b", "dlss5", "dlss5", 2),
      carte("c", "maestro", "minimax_h3", 3),
      carte("d", "dlss5", "dlss5", 4),
    ]
    const groupes = grouperParMoteur(ordonnerCommeArbitre(depart, { connecteur: null, modele: null }))
    expect(groupes.map((g) => g.jobs.map((j) => j.id).join(""))).toEqual(["ac", "bd"])
  })

  it("part du moteur chargé, pas d'un moteur seulement démarré", () => {
    expect(departFile([], [moteur("maestro", "demarre", 11000, 1500), moteur("dlss5", "arrete", 6000, 0)])).toEqual({
      connecteur: null,
      modele: null,
    })
    expect(departFile([], [moteur("maestro", "demarre", 11000, 1500), moteur("dlss5", "charge", 6000, 0)]).connecteur).toBe("dlss5")
    const enCours = { ...job("x", "maestro", "minimax_h3"), statut: "en_cours" as const }
    expect(departFile([enCours], [moteur("dlss5", "charge", 6000, 0)])).toEqual({ connecteur: "maestro", modele: "minimax_h3" })
  })

  it("additionne la VRAM tenue par les moteurs GPU", () => {
    expect(
      vramTenue([
        moteur("maestro", "charge", 11000, 1500),
        moteur("dlss5", "demarre", 6000, 0),
        moteur("bonsai", "arrete", 9440, 9440),
        moteur("claude", "charge", 0, 0),
      ]),
    ).toBe(11000)
    expect(vramTenue([moteur("maestro", "demarre", 11000, 1500)])).toBe(1500)
  })

  it("formate des mégaoctets en gigaoctets", () => {
    expect(formatGo(12282)).toBe("12,0")
    expect(formatGo(11000)).toBe("10,7")
  })
})
