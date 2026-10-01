import { describe, expect, it } from "vitest"

import {
  actionPossible,
  EVENEMENTS_MOTEURS,
  libelleEtape,
  libelleEtat,
  nomAccessibleAction,
  type MoteurInstalle,
} from "./moteurs"

function moteur(surcharge: Partial<MoteurInstalle>): MoteurInstalle {
  return { id: "maestro", etat: "absent", ...surcharge }
}

describe("libelleEtat", () => {
  it("donne l'état en clair pour chaque état", () => {
    expect(libelleEtat("absent")).toBe("Absent")
    expect(libelleEtat("installe")).toBe("Installé")
    expect(libelleEtat("externe")).toBe("Installé (externe)")
    expect(libelleEtat("version_differente")).toBe("Version différente")
    expect(libelleEtat("incomplet")).toBe("Incomplet")
    expect(libelleEtat("en_cours")).toBe("Installation…")
  })

  it("renvoie l'état tel quel s'il est inconnu", () => {
    expect(libelleEtat("autre")).toBe("autre")
  })
})

describe("actionPossible", () => {
  it("propose l'action de chaque état", () => {
    expect(actionPossible(moteur({ etat: "absent" }))).toBe("installer")
    expect(actionPossible(moteur({ etat: "incomplet" }))).toBe("reessayer")
    expect(actionPossible(moteur({ etat: "version_differente" }))).toBe("reinstaller")
  })

  it("ne propose rien pour un moteur installé, externe ou en cours d'installation", () => {
    expect(actionPossible(moteur({ etat: "installe" }))).toBeNull()
    expect(actionPossible(moteur({ etat: "externe" }))).toBeNull()
    expect(actionPossible(moteur({ etat: "en_cours" }))).toBeNull()
  })

  it("propose de se connecter pour Claude installé mais déconnecté", () => {
    expect(actionPossible(moteur({ id: "claude", etat: "installe", connecte: false }))).toBe("connecter")
    expect(actionPossible(moteur({ id: "claude", etat: "externe", connecte: false }))).toBe("connecter")
  })

  it("ne propose rien pour Claude connecté", () => {
    expect(actionPossible(moteur({ id: "claude", etat: "installe", connecte: true }))).toBeNull()
  })

  it("propose d'installer Claude absent, sans se connecter", () => {
    expect(actionPossible(moteur({ id: "claude", etat: "absent", connecte: false }))).toBe("installer")
  })
})

describe("libelleEtape", () => {
  it("traduit les codes d'étape", () => {
    expect(libelleEtape("preparation")).toBe("Préparation")
    expect(libelleEtape("telechargement")).toBe("Téléchargement")
    expect(libelleEtape("precharger_maestro")).toBe("Préchargement des modèles")
    expect(libelleEtape("copier_ressource")).toBe("Copie du modèle de conversation")
  })

  it("renvoie un code inconnu tel quel", () => {
    expect(libelleEtape("autre")).toBe("autre")
  })
})

describe("nomAccessibleAction", () => {
  it("donne un nom unique par moteur à chaque bouton d'action", () => {
    expect(nomAccessibleAction("installer", "Maestro")).toBe("Installer Maestro")
    expect(nomAccessibleAction("reessayer", "Bonsai 2")).toBe("Réessayer Bonsai 2")
    expect(nomAccessibleAction("reinstaller", "ffmpeg")).toBe("Réinstaller ffmpeg")
    expect(nomAccessibleAction("annuler", "Maestro")).toBe("Annuler l'installation de Maestro")
    expect(nomAccessibleAction("connecter", "Claude Code")).toBe("Se connecter à Claude")
  })
})

describe("EVENEMENTS_MOTEURS", () => {
  it("se limite à l'installation et à la (re)connexion du flux", () => {
    expect([...EVENEMENTS_MOTEURS].sort()).toEqual(["connecte", "installation"])
  })
})
