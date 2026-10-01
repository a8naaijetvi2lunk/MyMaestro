import { describe, expect, it } from "vitest"

import { formatDecimal, formatDuree, formatEspace, libelleConnecteur, libelleEtatPhase, libelleModele, libelleMoteurVideo, libellePhase, libelleRole } from "./format"

describe("formatEspace", () => {
  it("compte un Go pour 1 000 Mo, comme le README et le manifeste", () => {
    expect(formatEspace(110000)).toBe("110 Go")
    expect(formatEspace(9500)).toBe("9,5 Go")
    expect(formatEspace(1000)).toBe("1,0 Go")
    expect(formatEspace(999)).toBe("999 Mo")
  })
})

describe("formatDuree", () => {
  it("formate minutes, secondes et dixièmes", () => {
    expect(formatDuree(70.125)).toBe("1:10,1")
    expect(formatDuree(10.125)).toBe("0:10,1")
    expect(formatDuree(0)).toBe("0:00,0")
  })

  it("arrondit au dixième sans produire « 0:60,0 »", () => {
    expect(formatDuree(59.96)).toBe("1:00,0")
  })

  it("renvoie un tiret pour une valeur invalide", () => {
    expect(formatDuree(-1)).toBe("—")
    expect(formatDuree(Number.NaN)).toBe("—")
  })
})

describe("libellés", () => {
  it("traduit rôles et moteurs", () => {
    expect(libelleRole("chante")).toBe("Chanté")
    expect(libelleRole("coupe")).toBe("Coupe")
    expect(libelleMoteurVideo("minimax_h3")).toBe("MiniMax H3")
    expect(libelleMoteurVideo(null)).toBe("—")
    expect(libelleMoteurVideo("inconnu")).toBe("inconnu")
  })
})

describe("libellés de la file et des phases", () => {
  it("traduit connecteurs, modèles, phases et états", () => {
    expect(libelleConnecteur("dlss5")).toBe("DLSS 5")
    expect(libelleConnecteur("inconnu")).toBe("inconnu")
    expect(libelleModele("flashvsr2")).toBe("FlashVSR ×2")
    expect(libelleModele("minimax_h3")).toBe("MiniMax H3")
    expect(libelleModele(null)).toBe("—")
    expect(libellePhase("ecriture")).toBe("Écriture")
    expect(libelleEtatPhase("a_valider")).toBe("À valider")
  })

  it("formate un décimal à la française", () => {
    expect(formatDecimal(10.125)).toBe("10,1")
    expect(formatDecimal(1, 2)).toBe("1,00")
  })
})
