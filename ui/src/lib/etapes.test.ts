import { describe, expect, it } from "vitest"

import { etapeCourante, indicationMoteur, resumeMoteurs } from "./etapes"

describe("étapes du projet", () => {
  it("ouvre la première étape disponible non terminée", () => {
    expect(etapeCourante({ creation: "termine", analyse: "termine", ecriture: "en_cours" })).toBe("ecriture")
    expect(etapeCourante({})).toBe("creation")
    expect(etapeCourante({ creation: "termine", analyse: "termine", ecriture: "termine", prompts: "termine", images: "termine" })).toBe("video")
    expect(
      etapeCourante({ creation: "termine", analyse: "termine", ecriture: "termine", prompts: "termine", images: "termine", video: "termine", export: "termine" }),
    ).toBe("export")
  })

  it("résume moteurs vidéo et moteurs d'image", () => {
    expect(
      resumeMoteurs([
        { moteur_video: "minimax_h3", moteur_image: "qwen_image_edit_2511_20B_fp8_lightning_8step" },
        { moteur_video: "minimax_h3", moteur_image: "codex_imagegen" },
        { moteur_video: "ltx2_22B_distilled_1_1_omninft", moteur_image: "qwen_image_edit_2511_20B_fp8_lightning_8step" },
      ]),
    ).toBe("3 plans · 2 MiniMax H3 · 1 LTX-2.3 · images : 2 Qwen, 1 Codex")
  })
})

describe("indication sous le choix du moteur", () => {
  const compat = [
    { moteur: "minimax_h3", compatible: false, images: null, duree_s: null, note: "4,8 s < 5,2 s minimum", avertissement: null },
    { moteur: "ltx2_22B_distilled_1_1_omninft", compatible: true, images: 121, duree_s: 4.84, note: null, avertissement: null },
    { moteur: "ltx2_25_omninft", compatible: true, images: 113, duree_s: 4.7, note: null, avertissement: "LTX-2.5 : lip-sync écarté (A/B du 16/08)" },
  ] as const

  it("met l'avertissement du moteur choisi en premier", () => {
    expect(indicationMoteur([...compat], "ltx2_25_omninft")).toEqual({ texte: "LTX-2.5 : lip-sync écarté (A/B du 16/08)", alerte: true })
  })

  it("explique un moteur indisponible", () => {
    expect(indicationMoteur([...compat], "ltx2_22B_distilled_1_1_omninft")).toEqual({ texte: "H3 indisponible : 4,8 s < 5,2 s minimum", alerte: false })
  })

  it("signale un recalage possible", () => {
    const recalable = [{ ...compat[0], compatible: true, images: 124, duree_s: 5.17, note: "recalé à 5,2 s" }, compat[1]]
    expect(indicationMoteur(recalable, "ltx2_22B_distilled_1_1_omninft")).toEqual({ texte: "H3 possible : recalé à 5,2 s", alerte: false })
    expect(indicationMoteur([compat[1]], "ltx2_22B_distilled_1_1_omninft")).toBeNull()
  })
})
