/** Filtres de la bibliothèque (recherche insensible à la casse et aux accents). */

type FicheFiltrable = { type: string; nom: string; description: string }

export function normaliser(texte: string): string {
  return texte.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase()
}

export function filtrerFiches<T extends FicheFiltrable>(fiches: readonly T[], type: string, recherche: string): T[] {
  const cle = normaliser(recherche.trim())
  return fiches.filter(
    (fiche) =>
      (type === "tout" || fiche.type === type) && (!cle || normaliser(`${fiche.nom} ${fiche.description}`).includes(cle)),
  )
}

export function compterParType(fiches: readonly { type: string }[]): Record<string, number> {
  const comptes: Record<string, number> = {}
  for (const fiche of fiches) comptes[fiche.type] = (comptes[fiche.type] ?? 0) + 1
  return comptes
}
