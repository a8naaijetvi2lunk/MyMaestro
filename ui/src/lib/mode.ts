/** Mode d'affichage : clair par défaut (maquettes validées), sombre au choix, mémorisé par navigateur. */
export type Mode = "clair" | "sombre"

const CLE_MODE = "mymaestro.mode"

export function lireMode(): Mode {
  try {
    return localStorage.getItem(CLE_MODE) === "sombre" ? "sombre" : "clair"
  } catch {
    return "clair"
  }
}

export function appliquerMode(mode: Mode): void {
  document.documentElement.dataset.mode = mode === "sombre" ? "dark" : "light"
  try {
    localStorage.setItem(CLE_MODE, mode)
  } catch {
    // stockage indisponible (navigation privée, données bloquées) : le mode vaut pour la session
  }
}
