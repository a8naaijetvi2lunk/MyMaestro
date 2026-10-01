import { Scissors, Upload } from "lucide-react"
import { useId, useState } from "react"

import type { ActionProgrammee, Clip, Projet } from "@/api/client"
import { actionsTimeline, importerSon } from "@/api/timeline"
import { Button } from "@/components/ui/button"
import { PX_PAR_SECONDE_MAX, PX_PAR_SECONDE_MIN, formatTaille, libelleAction } from "@/lib/timeline"
import { cn } from "@/lib/utils"

type Executer = (action: () => Promise<unknown>) => Promise<boolean>

const TONS_ACTION: Record<string, string> = {
  refaire: "bg-[var(--status-danger-bg)] text-[color:var(--status-danger-ink)]",
  changer_moteur: "bg-[var(--v-pink-soft)] text-[color:var(--v-ink)]",
  passe_dlss5: "bg-[var(--v-yellow-soft)] text-[color:var(--v-ink)]",
  bruitage: "bg-[var(--v-blue-soft)] text-[color:var(--v-ink)]",
}

type Proprietes = {
  projet: Projet
  clip: Clip | null
  tete_s: number
  actions: readonly ActionProgrammee[]
  magnetisme: boolean
  onMagnetisme: (actif: boolean) => void
  pxParSeconde: number
  onZoom: (pxParSeconde: number) => void
  executer: Executer
  enCours: boolean
}

/** Barre de la timeline (maquette 4) : couper, magnétisme, zoom, pistes, sons, actions programmées, « Lancer la file ». */
export function BarreTimeline({ projet, clip, tete_s, actions, magnetisme, onMagnetisme, pxParSeconde, onZoom, executer, enCours }: Proprietes) {
  const idSon = useId()
  const [bilan, setBilan] = useState<string | null>(null)
  const indices = Object.fromEntries(projet.plans.map((plan) => [plan.id, plan.indice]))
  const image = 1 / 24
  const coupable = clip !== null && clip.piste !== "A0" && tete_s > clip.position_s + image && tete_s < clip.fin_s - image

  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-[26px] bg-card px-3 py-2 text-card-foreground">
      <Button size="sm" variant="outline" disabled={!coupable || enCours} onClick={() => clip && void executer(() => actionsTimeline.couper(projet.id, clip.id, tete_s))}>
        <Scissors aria-hidden="true" className="size-4" />
        Couper
      </Button>
      <Button
        size="sm"
        variant="outline"
        aria-pressed={magnetisme}
        className={cn(magnetisme && "bg-[var(--v-olive-soft)] font-semibold text-[color:var(--v-olive-ink)]")}
        onClick={() => onMagnetisme(!magnetisme)}
      >
        Magnétisme : temps forts
      </Button>
      <Button size="sm" variant="ghost" aria-label="Dézoomer" disabled={pxParSeconde <= PX_PAR_SECONDE_MIN} onClick={() => onZoom(Math.max(PX_PAR_SECONDE_MIN, pxParSeconde / 1.25))}>
        −
      </Button>
      <Button size="sm" variant="ghost" aria-label="Zoomer" disabled={pxParSeconde >= PX_PAR_SECONDE_MAX} onClick={() => onZoom(Math.min(PX_PAR_SECONDE_MAX, pxParSeconde * 1.25))}>
        +
      </Button>
      <Button size="sm" variant="ghost" disabled={enCours} onClick={() => void executer(() => actionsTimeline.ajouterPiste(projet.id, "video"))}>
        + Piste vidéo
      </Button>
      <Button size="sm" variant="ghost" disabled={enCours} onClick={() => void executer(() => actionsTimeline.ajouterPiste(projet.id, "audio"))}>
        + Piste son
      </Button>
      <label
        htmlFor={idSon}
        className="inline-flex h-[var(--ctl-sm)] cursor-pointer items-center gap-1.5 rounded-full px-3 text-[length:var(--fs-small)] hover:bg-[var(--v-beige)]"
      >
        <Upload aria-hidden="true" className="size-4" />
        Importer un son
      </label>
      <input
        id={idSon}
        type="file"
        accept="audio/*"
        className="sr-only"
        onChange={(evenement) => {
          const fichier = evenement.target.files?.[0]
          evenement.target.value = ""
          if (fichier) void executer(() => importerSon(projet.id, fichier, tete_s))
        }}
      />
      <Button
        size="sm"
        variant="ghost"
        disabled={enCours}
        onClick={() =>
          void executer(async () => {
            const nettoyage = await actionsTimeline.nettoyer(projet.id)
            setBilan(`${nettoyage.prises_supprimees} prise(s) supprimée(s), ${formatTaille(nettoyage.octets_liberes)} libérés`)
          })
        }
      >
        Nettoyer les prises non retenues
      </Button>
      {bilan && (
        <span role="status" className="text-xs text-[color:var(--v-text-2)]">
          {bilan}
        </span>
      )}
      <span aria-hidden="true" className="h-6 w-px bg-[var(--v-border)]" />
      <span className="text-xs font-semibold uppercase tracking-[.06em] text-[color:var(--v-text-3)]">Programmé</span>
      {actions.length === 0 && <span className="text-xs text-[color:var(--v-text-3)]">rien pour l'instant</span>}
      {actions.map((action) => {
        const libelle = libelleAction(action, indices)
        return (
          <span key={action.id} className={cn("inline-flex items-center gap-1 rounded-full py-1 pr-1 pl-2.5 text-xs", TONS_ACTION[action.type])}>
            {libelle}
            <button
              type="button"
              aria-label={`Retirer : ${libelle}`}
              disabled={enCours}
              className="rounded-full px-1.5 hover:bg-card"
              onClick={() => void executer(() => actionsTimeline.retirer(projet.id, action.id))}
            >
              ×
            </button>
          </span>
        )
      })}
      <Button className="ml-auto" disabled={actions.length === 0 || enCours} onClick={() => void executer(() => actionsTimeline.lancerFile(projet.id))}>
        Lancer la file ({actions.length})
      </Button>
    </div>
  )
}
