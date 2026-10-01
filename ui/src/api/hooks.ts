import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "./client"
import { exiger, messageErreur } from "./requetes"
import { actionsTimeline } from "./timeline"

type Etat<T> = { cle: string; version: number; donnees: T | null; erreur: string | null }

/**
 * Charge une donnée identifiée par `cle` ; `recharger()` la redemande. Pendant un rechargement
 * de la même clé, les données précédentes restent affichées (pas de clignotement).
 */
export function useDonnees<T>(cle: string, charger: () => Promise<T>) {
  const [version, setVersion] = useState(0)
  const [etat, setEtat] = useState<Etat<T>>({ cle: "", version: -1, donnees: null, erreur: null })
  const chargerRef = useRef(charger)
  // Numéro de la dernière requête lancée / appliquée : une réponse plus récente que la dernière appliquée
  // est toujours prise, même si un rechargement a été lancé entre-temps (sinon, des rechargements plus
  // rapprochés que la latence de la requête jetteraient toutes les réponses).
  const derniere = useRef(0)
  const appliquee = useRef(0)
  const monteRef = useRef(true)

  useEffect(() => {
    chargerRef.current = charger
  })

  useEffect(() => {
    const numero = ++derniere.current
    const aJour = () => {
      if (!monteRef.current || numero < appliquee.current) return false
      appliquee.current = numero
      return true
    }
    chargerRef.current().then(
      (donnees) => {
        if (aJour()) setEtat({ cle, version, donnees, erreur: null })
      },
      (erreur: unknown) => {
        if (aJour()) {
          setEtat((precedent) => ({
            cle,
            version,
            donnees: precedent.cle === cle ? precedent.donnees : null,
            erreur: messageErreur(erreur),
          }))
        }
      },
    )
  }, [cle, version])

  useEffect(() => {
    monteRef.current = true
    return () => {
      monteRef.current = false
    }
  }, [])

  const recharger = useCallback(() => setVersion((v) => v + 1), [])
  const memeCle = etat.cle === cle
  return {
    donnees: memeCle ? etat.donnees : null,
    erreur: memeCle ? etat.erreur : null,
    chargement: !memeCle || etat.version !== version,
    recharger,
  }
}

export type Evenement = { type: string; id?: string; statut?: string; valeur?: number; [cle: string]: unknown }

const TYPES_EVENEMENTS = ["connecte", "job", "progression", "preparation", "file", "erreur_ordonnanceur", "phase", "installation"]

// Un seul EventSource par page, partagé par tous les abonnés : le navigateur plafonne les
// connexions HTTP/1.1 longues (6 par hôte, tous onglets confondus).
let source: EventSource | null = null
const abonnes = new Set<(evenement: Evenement) => void>()

function ouvrirFlux(): EventSource {
  const flux = new EventSource("/api/evenements")
  const repartir = (message: MessageEvent) => {
    try {
      const donnees = JSON.parse(String(message.data)) as Record<string, unknown>
      const evenement = { ...donnees, type: message.type } as Evenement
      for (const abonne of [...abonnes]) abonne(evenement)
    } catch {
      // message illisible : ignoré, l'état se rattrape au rechargement suivant
    }
  }
  for (const type of TYPES_EVENEMENTS) flux.addEventListener(type, repartir)
  return flux
}

/** Abonnement au flux SSE /api/evenements (reconnexion automatique du navigateur). */
export function useEvenements(rappel: (evenement: Evenement) => void): void {
  const rappelRef = useRef(rappel)

  useEffect(() => {
    rappelRef.current = rappel
  })

  useEffect(() => {
    const relais = (evenement: Evenement) => rappelRef.current(evenement)
    abonnes.add(relais)
    if (source === null) source = ouvrirFlux()
    return () => {
      abonnes.delete(relais)
      if (abonnes.size === 0 && source !== null) {
        source.close()
        source = null
      }
    }
  }, [])
}

/**
 * Rappelle `recharger` quand le flux SSE signale un changement (au plus une fois par `delaiMs`).
 * `types` : seuls ces types d'événement déclenchent le rechargement (par défaut, tous).
 */
export function useRechargementSurEvenements(
  recharger: () => void,
  delaiMs = 400,
  types?: readonly string[],
): void {
  const minuterie = useRef<number | undefined>(undefined)

  useEvenements((evenement) => {
    if (types && !types.includes(evenement.type)) return
    if (minuterie.current !== undefined) return
    minuterie.current = window.setTimeout(() => {
      minuterie.current = undefined
      recharger()
    }, delaiMs)
  })

  useEffect(() => {
    const reference = minuterie
    return () => window.clearTimeout(reference.current)
  }, [])
}

/** État de la file, rechargé sur les événements du flux SSE. */
export function useEtatFile() {
  const requete = useDonnees("file", () => exiger(api.GET("/api/file")))
  useRechargementSurEvenements(requete.recharger)
  return requete
}

/** Projet et état du Director, rechargés ensemble sur les événements de la file. */
export function useProjetDirector(projetId: string) {
  const projet = useDonnees(`projet:${projetId}`, () =>
    exiger(api.GET("/api/projets/{projet_id}", { params: { path: { projet_id: projetId } } })),
  )
  const director = useDonnees(`director:${projetId}`, () =>
    exiger(api.GET("/api/projets/{projet_id}/director", { params: { path: { projet_id: projetId } } })),
  )
  const rechargerProjet = projet.recharger
  const rechargerDirector = director.recharger
  const recharger = useCallback(() => {
    rechargerProjet()
    rechargerDirector()
  }, [rechargerProjet, rechargerDirector])
  useRechargementSurEvenements(recharger)
  return { projet: projet.donnees, director: director.donnees, erreur: projet.erreur ?? director.erreur, recharger }
}

/** Timeline, segments projetés et actions programmées d'un projet, rechargés sur les événements de la file. */
export function useTimelineDirector(projetId: string) {
  const timeline = useDonnees(`timeline:${projetId}`, () => actionsTimeline.timeline(projetId))
  const segments = useDonnees(`segments:${projetId}`, () => actionsTimeline.segments(projetId))
  const actions = useDonnees(`actions:${projetId}`, () => actionsTimeline.actions(projetId))
  const rechargerTimeline = timeline.recharger
  const rechargerSegments = segments.recharger
  const rechargerActions = actions.recharger
  const recharger = useCallback(() => {
    rechargerTimeline()
    rechargerSegments()
    rechargerActions()
  }, [rechargerTimeline, rechargerSegments, rechargerActions])
  useRechargementSurEvenements(recharger)
  return {
    timeline: timeline.donnees,
    segments: segments.donnees ?? [],
    actions: actions.donnees ?? [],
    chargement: timeline.donnees === null && timeline.chargement,
    erreur: timeline.erreur ?? segments.erreur ?? actions.erreur,
    recharger,
  }
}
