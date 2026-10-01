import { api, type Brief, type LigneParoles, type PlanModification } from "./client"
import { exiger } from "./requetes"

function projet(projetId: string) {
  return { params: { path: { projet_id: projetId } } }
}

function plan(projetId: string, planId: string) {
  return { params: { path: { projet_id: projetId, plan_id: planId } } }
}

/** Actions du Director (plan 4b) ; chaque appel lève une erreur lisible en cas de refus. */
export const actionsDirector = {
  lancer: (projetId: string, phase: string) =>
    exiger(api.POST("/api/projets/{projet_id}/phases/{phase}/lancer", { params: { path: { projet_id: projetId, phase } } })),
  valider: (projetId: string, phase: string) =>
    exiger(api.POST("/api/projets/{projet_id}/phases/{phase}/valider", { params: { path: { projet_id: projetId, phase } } })),
  brief: (projetId: string, brief: Brief) => exiger(api.PUT("/api/projets/{projet_id}/ecriture/brief", { ...projet(projetId), body: brief })),
  concepts: (projetId: string) => exiger(api.POST("/api/projets/{projet_id}/ecriture/concepts", projet(projetId))),
  retenir: (projetId: string, indice: number) =>
    exiger(api.POST("/api/projets/{projet_id}/ecriture/concepts/{indice}/retenir", { params: { path: { projet_id: projetId, indice } } })),
  message: (projetId: string, texte: string) =>
    exiger(api.POST("/api/projets/{projet_id}/ecriture/chat", { ...projet(projetId), body: { texte } })),
  decoupage: (projetId: string) => exiger(api.POST("/api/projets/{projet_id}/ecriture/decoupage", projet(projetId))),
  lignes: (projetId: string, lignes: LigneParoles[]) =>
    exiger(api.PUT("/api/projets/{projet_id}/analyse/lignes", { ...projet(projetId), body: lignes })),
  casting: (projetId: string, casting: string[], ajouterAuxPlans: boolean) =>
    exiger(api.PUT("/api/projets/{projet_id}/casting", { ...projet(projetId), body: { casting, ajouter_aux_plans: ajouterAuxPlans } })),
  modifierPlan: (projetId: string, planId: string, modification: PlanModification) =>
    exiger(api.PATCH("/api/projets/{projet_id}/plans/{plan_id}", { ...plan(projetId, planId), body: modification })),
  refaireImage: (projetId: string, planId: string) =>
    exiger(api.POST("/api/projets/{projet_id}/plans/{plan_id}/image/refaire", plan(projetId, planId))),
  compatibilites: (projetId: string) => exiger(api.GET("/api/projets/{projet_id}/compatibilites", projet(projetId))),
}

/** Adresse d'un fichier du projet (chanson, images de départ) ; `version` force le rechargement après un remplacement. */
export function urlMediaProjet(projetId: string, chemin: string, version = 0): string {
  const adresse = `/api/projets/${encodeURIComponent(projetId)}/medias/${chemin.split("/").map(encodeURIComponent).join("/")}`
  return version ? `${adresse}?v=${version}` : adresse
}
