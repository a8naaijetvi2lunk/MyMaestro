/** Logique pure de la timeline (spec §6.2) : échelle, graduations, magnétisme, gestes de montage, projection, libellés. */

import { LIBELLES_COURTS_VIDEO } from "./etapes"
import { formatDecimal } from "./format"

export type Placement = { position_s: number; entree_s: number; sortie_s: number }

export type ClipTimeline = Placement & { id: string; piste: string; verrou_chanson: boolean }

export type Geste = "deplacer" | "rogner-debut" | "rogner-fin"

export const PX_PAR_SECONDE_MIN = 4
export const PX_PAR_SECONDE_MAX = 200
export const SEUIL_AIMANT_PX = 8
export const MOTS_MAX_BRUITAGE = 55

export function finClip(clip: Placement): number {
  return clip.position_s + clip.sortie_s - clip.entree_s
}

/** Zoom de départ (pixels par seconde) : la chanson entière tient dans `largeur_px`. */
export function zoomInitial(duree_s: number, largeur_px = 1056): number {
  if (!(duree_s > 0)) return 20
  return Math.min(PX_PAR_SECONDE_MAX, Math.max(PX_PAR_SECONDE_MIN, largeur_px / duree_s))
}

/** « m:ss » (ex. 65 s → « 1:05 »). */
export function formatHorloge(secondes: number): string {
  const total = Math.max(0, Math.round(secondes))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`
}

/** Repères de la règle, avec un pas lisible (au moins 60 px entre deux repères). */
export function graduations(duree_s: number, pxParSeconde: number): { temps: number; libelle: string }[] {
  const pas = [1, 2, 5, 10, 15, 30, 60, 120].find((p) => p * pxParSeconde >= 60) ?? 300
  const reperes: { temps: number; libelle: string }[] = []
  for (let n = 0; n * pas <= duree_s + 1e-9; n += 1) reperes.push({ temps: n * pas, libelle: formatHorloge(n * pas) })
  return reperes
}

/** Repère le plus proche à `seuil_s` près, sinon le temps lui-même. */
export function aimanter(temps: number, reperes: readonly number[], seuil_s: number): number {
  let meilleur = temps
  let ecart = seuil_s
  for (const repere of reperes) {
    const distance = Math.abs(repere - temps)
    if (distance <= ecart) {
      meilleur = repere
      ecart = distance
    }
  }
  return meilleur
}

/**
 * Placement proposé par un geste de `delta_s` secondes (positif : vers la droite), ou null s'il est interdit.
 * Un plan ancré à la chanson ne se déplace pas ; rogné par le début, sa position et son entrée bougent ensemble
 * (la synchro suit). Le clip garde au moins une image et ne dépasse pas sa source.
 */
export function appliquerGeste(
  clip: ClipTimeline,
  geste: Geste,
  delta_s: number,
  dureeSource: number | null,
  fps: number,
  dureeChanson: number | null = null,
): Placement | null {
  const image = 1 / fps
  const { position_s, entree_s, sortie_s } = clip
  if (geste === "deplacer") {
    if (clip.verrou_chanson) return null
    const maximum = dureeChanson === null ? Number.POSITIVE_INFINITY : dureeChanson - image
    return { position_s: Math.min(maximum, Math.max(0, position_s + delta_s)), entree_s, sortie_s }
  }
  if (geste === "rogner-debut") {
    const d = Math.min(Math.max(delta_s, -entree_s, -position_s), sortie_s - entree_s - image)
    return { position_s: position_s + d, entree_s: entree_s + d, sortie_s }
  }
  const maximum = dureeSource ?? Number.POSITIVE_INFINITY
  return { position_s, entree_s, sortie_s: Math.min(maximum, Math.max(entree_s + image, sortie_s + delta_s)) }
}

/** Magnétisme : le bord que le geste déplace se colle au repère le plus proche, sans sortir de la source. */
export function aimanterPlacement(
  placement: Placement,
  geste: Geste,
  reperes: readonly number[],
  seuil_s: number,
  dureeSource: number | null,
  fps = 24,
): Placement {
  const image = 1 / fps
  if (geste === "rogner-fin") {
    const fin = aimanter(finClip(placement), reperes, seuil_s)
    const sortie = placement.entree_s + (fin - placement.position_s)
    const valide = sortie >= placement.entree_s + image - 1e-9 && (dureeSource === null || sortie <= dureeSource + 1e-6)
    return valide ? { ...placement, sortie_s: sortie } : placement
  }
  const position = aimanter(placement.position_s, reperes, seuil_s)
  if (geste === "deplacer") return { ...placement, position_s: Math.max(0, position) }
  const entree = placement.entree_s + (position - placement.position_s)
  return entree >= 0 && entree <= placement.sortie_s - image + 1e-9 ? { position_s: position, entree_s: entree, sortie_s: placement.sortie_s } : placement
}

/** Le clip, placé ainsi, chevauche-t-il un autre clip de sa piste ? (le serveur tranche ; ceci évite un aller-retour) */
export function chevauche(clips: readonly ClipTimeline[], candidat: ClipTimeline): boolean {
  const fin = finClip(candidat)
  return clips.some(
    (autre) => autre.id !== candidat.id && autre.piste === candidat.piste && autre.position_s < fin - 1e-6 && candidat.position_s < finClip(autre) - 1e-6,
  )
}

export function segmentAuTemps<T extends { debut_s: number; fin_s: number }>(segments: readonly T[], temps: number): T | null {
  return segments.find((segment) => segment.debut_s <= temps && temps < segment.fin_s) ?? null
}

const LIBELLES_ETAT_CLIP: Record<string, string> = {
  prevu: "Prévu",
  en_file: "En file",
  en_rendu: "En rendu",
  brut: "Brut",
  upscale: "FlashVSR",
  dlss5: "DLSS5",
  echec: "Échec",
}

export function libelleEtatClip(etat: string | null, progression: number | null): string {
  if (etat === "en_rendu" && progression !== null) return `${Math.round(progression * 100)} %`
  return etat ? (LIBELLES_ETAT_CLIP[etat] ?? etat) : "—"
}

export function libellePiste(piste: string): string {
  if (piste === "A0") return "Chanson"
  return piste.startsWith("V") ? "Vidéo" : "Sons"
}

type ActionAffichee = { type: string; plan_id: string | null; reglages: Record<string, unknown> }

export function libelleAction(action: ActionAffichee, indices: Readonly<Record<string, number>>): string {
  const indice = action.plan_id !== null ? indices[action.plan_id] : undefined
  const cible = indice !== undefined ? `Plan ${indice + 1}` : "Projet"
  const moteur = typeof action.reglages.moteur === "string" ? (LIBELLES_COURTS_VIDEO[action.reglages.moteur] ?? action.reglages.moteur) : null
  switch (action.type) {
    case "refaire":
      return `${cible} · refaire${moteur ? ` en ${moteur}` : ""}${action.reglages.a_la_position ? " à cette position" : ""}`
    case "changer_moteur":
      return `${cible} · passer en ${moteur ?? "?"}`
    case "passe_dlss5": {
      const intensite = action.reglages.intensite
      return `${cible} · passe DLSS5${typeof intensite === "number" ? ` ${formatDecimal(intensite)}` : ""}`
    }
    case "bruitage":
      return `${cible} · bruitage`
    default:
      return `${cible} · ${action.type}`
  }
}

export function compterMots(texte: string): number {
  const net = texte.trim()
  return net ? net.split(/\s+/).length : 0
}

type PriseAffichee = {
  statut: string
  fichier_brut: string | null
  sortie_active_id: string | null
  sorties: readonly { id: string; statut: string; fichier: string | null }[]
}

/** Fichier que la prise envoie au montage : sa sortie active terminée, sinon son rendu brut ; null sans rendu. */
export function fichierDePrise(prise: PriseAffichee): string | null {
  if (prise.statut !== "termine") return null
  const sortie = prise.sorties.find((s) => s.id === prise.sortie_active_id && s.statut === "termine" && s.fichier)
  return sortie?.fichier ?? prise.fichier_brut
}

/** Taille lisible (« 1,2 Go », « 350 Mo »). */
export function formatTaille(octets: number): string {
  if (octets >= 1e9) return `${formatDecimal(octets / 1e9)} Go`
  return `${Math.round(octets / 1e6)} Mo`
}
