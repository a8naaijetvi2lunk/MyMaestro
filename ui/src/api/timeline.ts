import { api, type ActionEntree, type ClipModification, type TypePiste } from "./client"
import { executer, exiger, televerser } from "./requetes"

function projet(projetId: string) {
  return { params: { path: { projet_id: projetId } } }
}

function clip(projetId: string, clipId: string) {
  return { params: { path: { projet_id: projetId, clip_id: clipId } } }
}

/** Timeline, prises, actions à la carte et export (plan 5a) ; chaque appel lève une erreur lisible en cas de refus. */
export const actionsTimeline = {
  timeline: (projetId: string) => exiger(api.GET("/api/projets/{projet_id}/timeline", projet(projetId))),
  segments: (projetId: string) => exiger(api.GET("/api/projets/{projet_id}/timeline/segments", projet(projetId))),
  modifierClip: (projetId: string, clipId: string, modification: ClipModification) =>
    exiger(api.PATCH("/api/projets/{projet_id}/timeline/clips/{clip_id}", { ...clip(projetId, clipId), body: modification })),
  couper: (projetId: string, clipId: string, temps_s: number) =>
    exiger(api.POST("/api/projets/{projet_id}/timeline/clips/{clip_id}/couper", { ...clip(projetId, clipId), body: { temps_s } })),
  supprimerClip: (projetId: string, clipId: string) =>
    exiger(api.DELETE("/api/projets/{projet_id}/timeline/clips/{clip_id}", clip(projetId, clipId))),
  ajouterPiste: (projetId: string, type: TypePiste) =>
    exiger(api.POST("/api/projets/{projet_id}/timeline/pistes", { ...projet(projetId), body: { type } })),
  choisirPrise: (projetId: string, planId: string, priseId: string) =>
    exiger(
      api.PUT("/api/projets/{projet_id}/plans/{plan_id}/prise-active", {
        params: { path: { projet_id: projetId, plan_id: planId } },
        body: { prise_id: priseId },
      }),
    ),
  choisirSortie: (projetId: string, priseId: string, sortieId: string | null) =>
    exiger(
      api.PUT("/api/projets/{projet_id}/prises/{prise_id}/sortie-active", {
        params: { path: { projet_id: projetId, prise_id: priseId } },
        body: { sortie_id: sortieId },
      }),
    ),
  nettoyer: (projetId: string) => exiger(api.POST("/api/projets/{projet_id}/prises/nettoyer", projet(projetId))),
  estimation: (projetId: string) => exiger(api.GET("/api/projets/{projet_id}/video/estimation", projet(projetId))),
  actions: (projetId: string) => exiger(api.GET("/api/projets/{projet_id}/actions", projet(projetId))),
  programmer: (projetId: string, action: ActionEntree) =>
    exiger(api.POST("/api/projets/{projet_id}/actions", { ...projet(projetId), body: action })),
  retirer: (projetId: string, actionId: string) =>
    executer(api.DELETE("/api/projets/{projet_id}/actions/{action_id}", { params: { path: { projet_id: projetId, action_id: actionId } } })),
  lancerFile: (projetId: string) => exiger(api.POST("/api/projets/{projet_id}/actions/lancer", projet(projetId))),
  exports: (projetId: string) => exiger(api.GET("/api/projets/{projet_id}/exports", projet(projetId))),
  exporter: (projetId: string, interpolation: boolean | null) =>
    exiger(api.POST("/api/projets/{projet_id}/exports", { ...projet(projetId), body: { interpolation_60fps: interpolation } })),
}

/** Importe un son (corps brut) et le pose sur la première piste audio libre à `position_s`. */
export function importerSon(projetId: string, fichier: File, position_s: number): Promise<unknown> {
  return televerser(`/api/projets/${encodeURIComponent(projetId)}/sons?position_s=${position_s.toFixed(3)}`, fichier)
}
