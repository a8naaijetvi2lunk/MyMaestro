/** Étapes d'un projet Director, de la chanson à l'export. */

export type Etape = { id: string; libelle: string; disponible: boolean }

export const ETAPES: readonly Etape[] = [
  { id: "creation", libelle: "Chanson", disponible: true },
  { id: "analyse", libelle: "Analyse", disponible: true },
  { id: "ecriture", libelle: "Écriture", disponible: true },
  { id: "prompts", libelle: "Prompts et moteurs", disponible: true },
  { id: "images", libelle: "Images", disponible: true },
  { id: "video", libelle: "Vidéo et timeline", disponible: true },
  { id: "export", libelle: "Export", disponible: true },
]

export function etapeCourante(etats: Record<string, string>): string {
  const ouverte = ETAPES.find((etape) => etape.disponible && etats[etape.id] !== "termine")
  return ouverte?.id ?? "export"
}

export const LIBELLES_COURTS_VIDEO: Record<string, string> = {
  minimax_h3: "H3",
  ltx2_22B_distilled_1_1_omninft: "LTX-2.3",
  ltx2_25_omninft: "LTX-2.5",
}

const LIBELLES_RESUME_VIDEO: Record<string, string> = {
  minimax_h3: "MiniMax H3",
  ltx2_22B_distilled_1_1_omninft: "LTX-2.3",
  ltx2_25_omninft: "LTX-2.5",
}

const LIBELLES_RESUME_IMAGE: Record<string, string> = {
  qwen_image_edit_2511_20B_fp8_lightning_8step: "Qwen",
  codex_imagegen: "Codex",
}

function compter(valeurs: readonly (string | null)[], libelles: Record<string, string>): string[] {
  const comptes = new Map<string, number>()
  for (const valeur of valeurs) {
    if (!valeur) continue
    const libelle = libelles[valeur] ?? valeur
    comptes.set(libelle, (comptes.get(libelle) ?? 0) + 1)
  }
  return [...comptes].map(([libelle, nombre]) => `${nombre} ${libelle}`)
}

export function resumeMoteurs(plans: readonly { moteur_video: string | null; moteur_image: string | null }[]): string {
  const video = compter(plans.map((p) => p.moteur_video), LIBELLES_RESUME_VIDEO)
  const images = compter(plans.map((p) => p.moteur_image), LIBELLES_RESUME_IMAGE)
  return [`${plans.length} plan${plans.length > 1 ? "s" : ""}`, ...video, `images : ${images.join(", ")}`].join(" · ")
}

type Compatibilite = { moteur: string; compatible: boolean; note: string | null; avertissement: string | null }

/** Une ligne sous le choix du moteur : avertissement du moteur choisi, sinon moteur indisponible, sinon recalage possible. */
export function indicationMoteur(
  compatibilites: readonly Compatibilite[],
  choisi: string | null,
): { texte: string; alerte: boolean } | null {
  const actuel = compatibilites.find((c) => c.moteur === choisi)
  if (actuel?.avertissement) return { texte: actuel.avertissement, alerte: true }
  const indisponible = compatibilites.find((c) => !c.compatible && c.note)
  if (indisponible) return { texte: `${LIBELLES_COURTS_VIDEO[indisponible.moteur] ?? indisponible.moteur} indisponible : ${indisponible.note}`, alerte: false }
  const recalable = compatibilites.find((c) => c.compatible && c.note && c.moteur !== choisi)
  if (recalable) return { texte: `${LIBELLES_COURTS_VIDEO[recalable.moteur] ?? recalable.moteur} possible : ${recalable.note}`, alerte: false }
  return null
}
