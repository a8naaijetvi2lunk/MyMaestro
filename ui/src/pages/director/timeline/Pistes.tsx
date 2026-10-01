import { Lock, TriangleAlert } from "lucide-react"
import { useState, type PointerEvent } from "react"

import type { Clip, Plan, Section } from "@/api/client"
import { LIBELLES_COURTS_VIDEO } from "@/lib/etapes"
import { libelleRole } from "@/lib/format"
import {
  SEUIL_AIMANT_PX,
  aimanterPlacement,
  appliquerGeste,
  chevauche,
  graduations,
  libelleEtatClip,
  libellePiste,
  type Geste,
  type Placement,
} from "@/lib/timeline"
import { cn } from "@/lib/utils"

const LARGEUR_ETIQUETTE = 64
const ECART = 8

type Glisse = { clipId: string; geste: Geste; departX: number; placement: Placement; valide: boolean }

type Proprietes = {
  pistes: readonly string[]
  clips: readonly Clip[]
  plans: readonly Plan[]
  sections: readonly Section[]
  tempsForts: readonly number[]
  duree_s: number
  fps: number
  pxParSeconde: number
  magnetisme: boolean
  selection: string | null
  tete_s: number
  onSelection: (clipId: string) => void
  onTete: (temps_s: number) => void
  onPlacer: (clipId: string, placement: Placement) => void
}

/** Pistes de la timeline (maquette 4) : règle, sections, pistes vidéo et audio, gestes de montage, tête de lecture. */
export function Pistes(props: Proprietes) {
  const { pistes, clips, plans, sections, tempsForts, duree_s, fps, pxParSeconde, magnetisme, selection, tete_s } = props
  const { onSelection, onTete, onPlacer } = props
  const [glisse, setGlisse] = useState<Glisse | null>(null)
  const parPlan = new Map(plans.map((plan) => [plan.id, plan]))
  const largeur = Math.ceil(duree_s * pxParSeconde)
  const reperes = [...tempsForts, tete_s]

  const dureeSource = (clip: Clip) => (clip.plan_id ? (parPlan.get(clip.plan_id)?.duree_s ?? null) : null)

  function commencer(evenement: PointerEvent<HTMLElement>, clip: Clip, geste: Geste) {
    if (evenement.button !== 0 || clip.piste === "A0") return
    evenement.stopPropagation()
    evenement.currentTarget.setPointerCapture(evenement.pointerId)
    onSelection(clip.id)
    setGlisse({
      clipId: clip.id,
      geste,
      departX: evenement.clientX,
      placement: { position_s: clip.position_s, entree_s: clip.entree_s, sortie_s: clip.sortie_s },
      valide: true,
    })
  }

  function bouger(evenement: PointerEvent<HTMLElement>, clip: Clip) {
    if (glisse === null || glisse.clipId !== clip.id) return
    const brut = appliquerGeste(clip, glisse.geste, (evenement.clientX - glisse.departX) / pxParSeconde, dureeSource(clip), fps, duree_s)
    if (brut === null) return
    const placement = magnetisme
      ? aimanterPlacement(brut, glisse.geste, reperes, SEUIL_AIMANT_PX / pxParSeconde, dureeSource(clip), fps)
      : brut
    setGlisse({ ...glisse, placement, valide: !chevauche(clips, { ...clip, ...placement }) })
  }

  function finir(clip: Clip) {
    if (glisse === null || glisse.clipId !== clip.id) return
    setGlisse(null)
    const { placement, valide } = glisse
    const change =
      placement.position_s !== clip.position_s || placement.entree_s !== clip.entree_s || placement.sortie_s !== clip.sortie_s
    if (change && valide) onPlacer(clip.id, placement)
  }

  function placerTete(evenement: PointerEvent<HTMLElement>) {
    const bord = evenement.currentTarget.getBoundingClientRect().left
    onTete(Math.min(duree_s, Math.max(0, (evenement.clientX - bord) / pxParSeconde)))
  }

  return (
    <section aria-label="Pistes" className="rounded-[var(--r-card)] bg-card p-4 text-card-foreground">
      <div className="overflow-x-auto">
        <div className="relative flex flex-col gap-2" style={{ width: LARGEUR_ETIQUETTE + ECART + largeur }}>
          <div className="flex gap-2">
            <span className="shrink-0" style={{ width: LARGEUR_ETIQUETTE }} />
            <div
              aria-hidden="true"
              onPointerDown={placerTete}
              className="relative h-[18px] cursor-pointer text-[11px] tabular-nums text-[color:var(--v-text-3)]"
              style={{ width: largeur }}
            >
              {graduations(duree_s, pxParSeconde).map((repere) => (
                <span key={repere.temps} className="absolute" style={{ left: repere.temps * pxParSeconde }}>
                  {repere.libelle}
                </span>
              ))}
            </div>
          </div>
          {sections.length > 0 && (
            <div className="flex gap-2">
              <span className="shrink-0 self-center text-[11px] text-[color:var(--v-text-3)]" style={{ width: LARGEUR_ETIQUETTE }}>
                Sections
              </span>
              <div className="relative h-[22px] text-[11px] font-semibold text-[color:var(--v-text-2)]" style={{ width: largeur }}>
                {sections.map((section) => (
                  <span
                    key={`${section.nom}-${section.debut_s}`}
                    className="absolute h-[22px] truncate rounded-[6px] bg-[var(--v-beige)] px-2 py-[3px]"
                    style={{ left: section.debut_s * pxParSeconde, width: Math.max(0, (section.fin_s - section.debut_s) * pxParSeconde - 2) }}
                  >
                    {section.nom}
                  </span>
                ))}
              </div>
            </div>
          )}
          {pistes.map((piste) => (
            <div key={piste} className="flex gap-2">
              <span className="flex shrink-0 flex-col justify-center text-xs font-semibold" style={{ width: LARGEUR_ETIQUETTE }}>
                {piste}
                <span className="text-[11px] font-normal text-[color:var(--v-text-3)]">{libellePiste(piste)}</span>
              </span>
              <div
                className={cn(
                  "relative rounded-[12px]",
                  piste.startsWith("V") ? "h-[72px]" : "h-[44px]",
                  piste === "A0" ? "bg-[var(--v-olive-soft)]" : "bg-[var(--v-beige-2)]",
                )}
                style={{ width: largeur }}
              >
                {clips
                  .filter((clip) => clip.piste === piste)
                  .map((clip) => {
                    const enCours = glisse !== null && glisse.clipId === clip.id ? glisse : null
                    const place = enCours?.placement ?? clip
                    return (
                      <ClipPiste
                        key={clip.id}
                        clip={clip}
                        plan={clip.plan_id ? parPlan.get(clip.plan_id) : undefined}
                        gauche={place.position_s * pxParSeconde}
                        largeur={Math.max(6, (place.sortie_s - place.entree_s) * pxParSeconde)}
                        choisi={clip.id === selection}
                        invalide={enCours !== null && !enCours.valide}
                        onSelection={() => onSelection(clip.id)}
                        onCommencer={(evenement, geste) => commencer(evenement, clip, geste)}
                        onBouger={(evenement) => bouger(evenement, clip)}
                        onFinir={() => finir(clip)}
                      />
                    )
                  })}
              </div>
            </div>
          ))}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute top-0 bottom-0 w-[2px] rounded-[2px] bg-[var(--v-ink)]"
            style={{ left: LARGEUR_ETIQUETTE + ECART + tete_s * pxParSeconde }}
          />
        </div>
      </div>
    </section>
  )
}

function nomFichier(chemin: string | null): string {
  return chemin ? (chemin.split("/").pop() ?? chemin) : "son"
}

function styleClip(clip: Clip, plan: Plan | undefined): string {
  if (clip.piste === "A0") return "bg-[var(--v-olive-soft)] text-[color:var(--v-olive-ink)] [box-shadow:inset_0_0_0_1px_var(--v-olive)]"
  if (!clip.piste.startsWith("V")) return "bg-[var(--v-yellow)] text-[color:var(--v-on-accent)]"
  const chante = plan?.role === "chante"
  switch (clip.etat) {
    case "echec":
      return "bg-[var(--status-danger-bg)] text-[color:var(--status-danger-ink)] [box-shadow:inset_0_0_0_2px_var(--v-danger)]"
    case "prevu":
      return "border-2 border-dashed border-[var(--v-border)] bg-transparent text-[color:var(--v-text-3)]"
    case "en_file":
      return cn("border-2 border-dashed bg-transparent text-foreground", chante ? "border-[var(--v-pink-deep)]" : "border-[var(--v-blue-deep)]")
    case "en_rendu":
    case "brut":
      return chante ? "bg-[var(--v-pink-soft)] text-[color:var(--v-ink)]" : "bg-[var(--v-blue-soft)] text-[color:var(--v-ink)]"
    default:
      return chante ? "bg-[var(--v-pink)] text-[color:var(--v-on-accent)]" : "bg-[var(--v-blue)] text-[color:var(--v-on-accent)]"
  }
}

function styleBadge(etat: string | null): string {
  if (etat === "dlss5") return "bg-[var(--v-ink)] text-[color:var(--v-on-ink)]"
  if (etat === "upscale") return "bg-card text-foreground"
  if (etat === "echec") return "bg-[var(--v-danger-fill)] text-[color:var(--on-structure)]"
  if (etat === "en_rendu") return "bg-[var(--v-yellow)] text-[color:var(--v-on-accent)]"
  return "bg-[var(--v-beige)] text-foreground"
}

function ClipPiste({
  clip,
  plan,
  gauche,
  largeur,
  choisi,
  invalide,
  onSelection,
  onCommencer,
  onBouger,
  onFinir,
}: {
  clip: Clip
  plan: Plan | undefined
  gauche: number
  largeur: number
  choisi: boolean
  invalide: boolean
  onSelection: () => void
  onCommencer: (evenement: PointerEvent<HTMLElement>, geste: Geste) => void
  onBouger: (evenement: PointerEvent<HTMLElement>) => void
  onFinir: () => void
}) {
  const video = clip.piste.startsWith("V")
  const moteur = plan?.moteur_video ? ` · ${LIBELLES_COURTS_VIDEO[plan.moteur_video] ?? ""}` : ""
  const titre = video && plan ? `${plan.indice + 1} · ${libelleRole(plan.role)}${moteur}` : nomFichier(clip.fichier_audio)
  const etat = libelleEtatClip(clip.etat, clip.progression)
  // Les poignées arrêtent la propagation : le corps du clip ne reçoit pas leurs gestes (sinon double envoi).
  const poignee = (geste: Geste) => ({
    onPointerDown: (evenement: PointerEvent<HTMLElement>) => onCommencer(evenement, geste),
    onPointerMove: (evenement: PointerEvent<HTMLElement>) => {
      evenement.stopPropagation()
      onBouger(evenement)
    },
    onPointerUp: (evenement: PointerEvent<HTMLElement>) => {
      evenement.stopPropagation()
      onFinir()
    },
    onPointerCancel: (evenement: PointerEvent<HTMLElement>) => {
      evenement.stopPropagation()
      onFinir()
    },
  })
  return (
    <button
      type="button"
      aria-pressed={choisi}
      aria-label={
        video && plan
          ? `Plan ${plan.indice + 1}, ${libelleRole(plan.role)}, ${etat}${clip.verrou_chanson ? ", ancré à la chanson" : ""}`
          : `Son ${titre}`
      }
      onClick={onSelection}
      onPointerDown={(evenement) => onCommencer(evenement, "deplacer")}
      onPointerMove={onBouger}
      onPointerUp={onFinir}
      onPointerCancel={onFinir}
      className={cn(
        "absolute top-1.5 flex touch-none flex-col justify-between overflow-hidden rounded-[12px] px-2 py-1.5 text-left text-xs font-semibold",
        video ? "h-[60px]" : "h-[32px]",
        styleClip(clip, plan),
        choisi && "[box-shadow:0_0_0_2px_var(--card),0_0_0_4px_var(--v-ink)]",
        invalide && "outline-2 outline-dashed outline-[var(--v-danger)]",
        clip.verrou_chanson || clip.piste === "A0" ? "cursor-default" : "cursor-grab",
      )}
      style={{ left: gauche, width: largeur }}
    >
      <span className="flex items-center gap-1 truncate">
        {clip.verrou_chanson && <Lock aria-hidden="true" className="size-3 shrink-0" strokeWidth={2.5} />}
        {clip.etat === "echec" && <TriangleAlert aria-hidden="true" className="size-3 shrink-0" strokeWidth={2.5} />}
        {titre}
      </span>
      {video && <span className={cn("self-start rounded-full px-1.5 py-px text-[10px]", styleBadge(clip.etat))}>{etat}</span>}
      {clip.etat === "en_rendu" && clip.progression !== null && (
        <span className="absolute bottom-0 left-0 h-1 bg-[var(--v-yellow-deep)]" style={{ width: `${Math.round(clip.progression * 100)}%` }} />
      )}
      {clip.piste !== "A0" && (
        <>
          <span aria-hidden="true" className="absolute top-0 bottom-0 left-0 w-2 cursor-ew-resize" {...poignee("rogner-debut")} />
          <span aria-hidden="true" className="absolute top-0 right-0 bottom-0 w-2 cursor-ew-resize" {...poignee("rogner-fin")} />
        </>
      )}
    </button>
  )
}
