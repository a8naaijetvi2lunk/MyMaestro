import { useCallback, useState } from "react"

import { api } from "@/api/client"
import { urlMediaProjet } from "@/api/director"
import { useDonnees, useRechargementSurEvenements } from "@/api/hooks"
import { exiger } from "@/api/requetes"
import { actionsTimeline } from "@/api/timeline"
import { useAction } from "@/api/use-action"
import { Alerte, Carte } from "@/components/commun/mise-en-page"
import { CaseACocher } from "@/components/formulaire/controles"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatDuree } from "@/lib/format"
import { naviguer } from "@/lib/use-route"

import { BarreActions, type ProprietesEcran } from "./commun"

const STATUTS_EXPORT: Record<string, { libelle: string; variante: "olive-soft" | "danger" | "yellow-soft" | "default" }> = {
  termine: { libelle: "Terminé", variante: "olive-soft" },
  echec: { libelle: "Échec", variante: "danger" },
  en_cours: { libelle: "En cours", variante: "yellow-soft" },
  en_file: { libelle: "En file", variante: "default" },
}

function chargerRecettes() {
  return exiger(api.GET("/api/recettes", { params: { query: { module: "director_musique" } } }))
}

function telechargement(projetId: string, fichier: string): string {
  return `${urlMediaProjet(projetId, fichier)}?telecharger=true`
}

/** Étape « Export » : montage 1080p selon la projection de la timeline, option 60 fps (DLSSG), exports passés. */
export function EcranExport({ projet, director, recharger }: ProprietesEcran) {
  const exportsProjet = useDonnees(`exports:${projet.id}`, () => actionsTimeline.exports(projet.id))
  const segments = useDonnees(`segments:${projet.id}`, () => actionsTimeline.segments(projet.id))
  const recettes = useDonnees("recettes:director_musique", chargerRecettes)
  const rendu = useDonnees(`rendu:${projet.format}`, () => exiger(api.GET("/api/rendu", { params: { query: { format: projet.format } } })))
  const rechargerExports = exportsProjet.recharger
  const rechargerSegments = segments.recharger
  const rechargerLocal = useCallback(() => {
    rechargerExports()
    rechargerSegments()
  }, [rechargerExports, rechargerSegments])
  const toutRecharger = useCallback(() => {
    recharger()
    rechargerLocal()
  }, [recharger, rechargerLocal])
  useRechargementSurEvenements(rechargerLocal)
  const { erreur, enCours, executer } = useAction(toutRecharger)
  const [interpolation, setInterpolation] = useState<boolean | null>(null)

  if (segments.donnees === null && segments.erreur) {
    return (
      <Carte titre="Export">
        {segments.erreur === "Timeline introuvable" ? (
          <p className="m-0 text-sm">Pas encore de timeline à exporter : elle apparaît à la validation des images.</p>
        ) : (
          <Alerte>{segments.erreur}</Alerte>
        )}
        <Button variant="outline" className="w-fit" onClick={() => naviguer({ page: "projet", projetId: projet.id, etape: "video" })}>
          Aller à la timeline
        </Button>
      </Carte>
    )
  }

  const recette = recettes.donnees?.find((r) => r.id === projet.recette_id)
  const reglageExport = recette?.valeurs.export as { interpolation_60fps?: boolean } | undefined
  const avec60 = interpolation ?? Boolean(reglageExport?.interpolation_60fps)
  const liste = exportsProjet.donnees ?? []
  const exportEnCours = liste.some((unExport) => unExport.statut === "en_file" || unExport.statut === "en_cours")
  const noirs = (segments.donnees ?? []).filter((segment) => segment.clip_id !== null && segment.fichier === null).length
  const taille = rendu.donnees ? `${rendu.donnees.largeur_sortie}×${rendu.donnees.hauteur_sortie}` : "1080p"

  return (
    <div className="flex flex-col gap-4">
      <Carte titre="Export du clip">
        <p className="m-0 text-sm text-[color:var(--v-text-2)]">
          Le montage suit la projection de la timeline, comme l'aperçu : chaque segment est normalisé en {taille} à {rendu.donnees?.fps_maitre ?? 24} fps,
          puis la chanson et les sons sont mixés. Durée : {projet.duree_chanson_s ? formatDuree(projet.duree_chanson_s) : "—"}.
        </p>
        {noirs > 0 && <Alerte>{noirs} segment(s) sans rendu partiront en noir.</Alerte>}
        <CaseACocher
          libelle="Interpolation 60 fps (DLSSG)"
          description="Appliquée une seule fois, au montage final ; par défaut, la valeur de la recette"
          coche={avec60}
          onChange={setInterpolation}
        />
      </Carte>
      {director?.erreurs.export && <Alerte>{director.erreurs.export}</Alerte>}
      {erreur && <Alerte>{erreur}</Alerte>}
      {exportsProjet.erreur && <Alerte>{exportsProjet.erreur}</Alerte>}
      <BarreActions>
        <span className="flex-1 text-[color:var(--v-text-2)]">
          {liste.length} export{liste.length > 1 ? "s" : ""}
          {exportEnCours && " · Un export est en cours"}
        </span>
        <Button variant="accent" disabled={enCours || exportEnCours || segments.donnees === null} onClick={() => void executer(() => actionsTimeline.exporter(projet.id, interpolation))}>
          Exporter
        </Button>
      </BarreActions>
      {liste.length > 0 && (
        <Carte titre="Exports">
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {liste.map((unExport) => {
              const statut = STATUTS_EXPORT[unExport.statut] ?? { libelle: unExport.statut, variante: "default" as const }
              return (
                <li key={unExport.id} className="flex flex-wrap items-center gap-3 rounded-[14px] bg-[var(--v-beige-2)] px-4 py-3 text-[13px]">
                  <Badge variant={statut.variante}>{statut.libelle}</Badge>
                  <span>{new Date(unExport.cree_le).toLocaleString("fr-FR")}</span>
                  <span className="text-[color:var(--v-text-3)]">
                    {formatDuree(unExport.duree_s)}
                    {unExport.interpolation_60fps ? " · 60 fps demandé" : ""}
                  </span>
                  {unExport.fichier && (
                    <>
                      <a href={urlMediaProjet(projet.id, unExport.fichier)} target="_blank" rel="noreferrer">
                        Lire
                      </a>
                      <a href={telechargement(projet.id, unExport.fichier)}>Télécharger (24 fps)</a>
                    </>
                  )}
                  {unExport.fichier_60fps && <a href={telechargement(projet.id, unExport.fichier_60fps)}>Télécharger (60 fps)</a>}
                  {unExport.erreur && (
                    <span role="alert" className="text-[color:var(--status-danger-ink)]">
                      {unExport.erreur}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
        </Carte>
      )}
    </div>
  )
}
