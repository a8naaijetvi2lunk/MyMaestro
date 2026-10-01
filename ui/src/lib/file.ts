import type { EtatConnecteur, Job } from "@/api/client"

export type GroupeMoteur = { cle: string; connecteur: string; modele: string | null; jobs: Job[] }

export type DepartFile = { connecteur: string | null; modele: string | null }

/**
 * Graine de `ordonnerCommeArbitre` : le job en cours, sinon le moteur GPU CHARGÉ (comme `arbitre.moteur_charge`).
 * `gpu_occupe_par` n'est pas utilisable : il retombe sur un moteur seulement démarré, que l'arbitre ignore.
 */
export function departFile(jobs: readonly Job[], connecteurs: readonly EtatConnecteur[]): DepartFile {
  const enCours = jobs.find((j) => j.voie === "gpu" && j.statut === "en_cours")
  if (enCours) return { connecteur: enCours.connecteur, modele: enCours.modele ?? null }
  return { connecteur: connecteurs.find((c) => c.voie === "gpu" && c.etat === "charge")?.nom ?? null, modele: null }
}

/**
 * Ordre d'exécution prévu par l'arbitre (`arbitre.ordonner`) : bloc de tête (même régime, même phase que le plus petit
 * `ordre`), puis moteur chargé + même modèle, puis même moteur, sinon plus petit `ordre`.
 * Limites : `dernier_modele` n'est pas exposé (graine = job en cours, ou moteur occupé sans modèle connu) et `apres`
 * n'est pas dans Job (aucun producteur ne le pose aujourd'hui).
 */
export function ordonnerCommeArbitre(jobs: readonly Job[], depart: DepartFile): Job[] {
  const restants = [...jobs]
  const ordre: Job[] = []
  let { connecteur, modele } = depart
  while (restants.length > 0) {
    const tete = restants.reduce((a, b) => (b.ordre < a.ordre ? b : a))
    const bloc = restants.filter((j) => j.regime === tete.regime && j.phase === tete.phase).sort((a, b) => a.ordre - b.ordre)
    const choisi =
      bloc.find((j) => j.connecteur === connecteur && (j.modele ?? null) === modele) ??
      bloc.find((j) => j.connecteur === connecteur) ??
      bloc[0]
    ordre.push(choisi)
    restants.splice(restants.indexOf(choisi), 1)
    connecteur = choisi.connecteur
    modele = choisi.modele ?? null
  }
  return ordre
}

/** Jobs regroupés quand ils se suivent sur le même moteur et le même modèle (ordre reçu conservé). */
export function grouperParMoteur(jobs: readonly Job[]): GroupeMoteur[] {
  const groupes: GroupeMoteur[] = []
  for (const job of jobs) {
    const cle = `${job.connecteur}:${job.modele ?? ""}`
    const dernier = groupes[groupes.length - 1]
    if (dernier && dernier.cle === cle) dernier.jobs.push(job)
    else groupes.push({ cle, connecteur: job.connecteur, modele: job.modele ?? null, jobs: [job] })
  }
  return groupes
}

/** VRAM tenue par les moteurs GPU : pic du moteur chargé, résiduel des moteurs seulement démarrés. */
export function vramTenue(connecteurs: readonly EtatConnecteur[]): number {
  return connecteurs
    .filter((c) => c.voie === "gpu")
    .reduce((total, c) => total + (c.etat === "charge" ? c.empreinte_vram_mo : c.etat === "demarre" ? c.vram_residuelle_mo : 0), 0)
}

export function formatGo(mo: number): string {
  return (mo / 1024).toFixed(1).replace(".", ",")
}
