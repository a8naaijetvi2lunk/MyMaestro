export type DefinitionH3 = "480p" | "544p" | "720p" | "1080p"
export type Definitions = { h3: DefinitionH3; ltx23: "544p" | "720p" | "1080p"; ltx25: "544p" | "720p" | "1080p" }

export const TOUTES_DEFINITIONS_H3: DefinitionH3[] = ["480p", "544p", "720p", "1080p"]

/** Définitions de la section `rendu` du formulaire ; défaut 544p si la section ou une valeur manque ou est inconnue. */
export function definitionsDuFormulaire(valeurs: Record<string, unknown>): Definitions {
  const rendu = (valeurs.rendu ?? {}) as Record<string, unknown>
  const h3 = TOUTES_DEFINITIONS_H3.find((d) => d === rendu.h3) ?? "544p"
  return {
    h3,
    ltx23: rendu.ltx23 === "720p" || rendu.ltx23 === "1080p" ? rendu.ltx23 : "544p",
    ltx25: rendu.ltx25 === "720p" || rendu.ltx25 === "1080p" ? rendu.ltx25 : "544p",
  }
}

/** Définition H3 à envoyer à /api/rendu : `undefined` (défaut du serveur) si la carte ne la permet pas, car elle serait refusée (422).
 * Tant que les permises ne sont pas connues, seules 480p et 544p partent (sans doute permises dès 12 Go), et 720p / 1080p attendent. */
export function h3Interroge(h3: DefinitionH3, permises: readonly string[] | undefined): DefinitionH3 | undefined {
  if (permises) return permises.includes(h3) ? h3 : undefined
  return h3 === "480p" || h3 === "544p" ? h3 : undefined
}
