/** Fonctions pures de l'écran « Moteurs » : libellés d'état et action proposée. */

export type ActionMoteur = "installer" | "reessayer" | "reinstaller" | "connecter"

/** Le strict nécessaire d'un moteur pour décider de l'action (compatible avec `EtatMoteurInstalle`). */
export type MoteurInstalle = { id: string; etat: string; connecte?: boolean | null }

const LIBELLES_ETAT: Record<string, string> = {
  absent: "Absent",
  installe: "Installé",
  externe: "Installé (externe)",
  version_differente: "Version différente",
  incomplet: "Incomplet",
  en_cours: "Installation…",
}

export function libelleEtat(etat: string): string {
  return LIBELLES_ETAT[etat] ?? etat
}

const LIBELLES_ETAPE: Record<string, string> = {
  preparation: "Préparation",
  telechargement: "Téléchargement",
  extraire: "Extraction",
  commande: "Installation des dépendances",
  copier_ressource: "Copie du modèle de conversation",
  precharger_maestro: "Préchargement des modèles",
  installeur_claude: "Installeur Claude",
  fin: "Fin",
}

/** Libellé français d'une étape d'installation (code inconnu : renvoyé tel quel). */
export function libelleEtape(etape: string): string {
  return LIBELLES_ETAPE[etape] ?? etape
}

/** Événements du flux SSE après lesquels l'écran « Moteurs » se recharge : l'installation, et la (re)connexion du flux. */
export const EVENEMENTS_MOTEURS = ["installation", "connecte"] as const

const VERBES_ACTION: Record<"installer" | "reessayer" | "reinstaller", string> = {
  installer: "Installer",
  reessayer: "Réessayer",
  reinstaller: "Réinstaller",
}

/** Nom accessible d'un bouton : unique par moteur (plusieurs « Installer » identiques sur la même page n'en disent rien). */
export function nomAccessibleAction(action: ActionMoteur | "annuler", libelleMoteur: string): string {
  if (action === "annuler") return `Annuler l'installation de ${libelleMoteur}`
  if (action === "connecter") return "Se connecter à Claude"
  return `${VERBES_ACTION[action]} ${libelleMoteur}`
}

/**
 * Action du bouton d'une carte : « Installer » (absent), « Réessayer » (incomplet), « Réinstaller » (version différente),
 * « Se connecter » (Claude utilisable mais déconnecté) ; aucune pour un moteur installé, externe ou en cours d'installation.
 */
export function actionPossible(moteur: MoteurInstalle): ActionMoteur | null {
  switch (moteur.etat) {
    case "absent":
      return "installer"
    case "incomplet":
      return "reessayer"
    case "version_differente":
      return "reinstaller"
    case "installe":
    case "externe":
      return moteur.id === "claude" && moteur.connecte === false ? "connecter" : null
    default:
      return null
  }
}
