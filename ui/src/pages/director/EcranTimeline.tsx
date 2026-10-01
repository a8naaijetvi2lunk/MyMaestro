import { useCallback, useState } from "react"

import { actionsDirector } from "@/api/director"
import { useDonnees, useTimelineDirector } from "@/api/hooks"
import { actionsTimeline } from "@/api/timeline"
import { useAction } from "@/api/use-action"
import { Alerte, Carte } from "@/components/commun/mise-en-page"
import { Button } from "@/components/ui/button"
import { formatDuree } from "@/lib/format"
import { finClip, formatTaille, zoomInitial, type Placement } from "@/lib/timeline"
import { naviguer } from "@/lib/use-route"

import { BarreActions, type ProprietesEcran } from "./commun"
import { Apercu } from "./timeline/Apercu"
import { BarreTimeline } from "./timeline/BarreTimeline"
import { PanneauPlan } from "./timeline/PanneauPlan"
import { Pistes } from "./timeline/Pistes"

type Executer = (action: () => Promise<unknown>) => Promise<boolean>

const CLES_ERREURS = ["video", "postprod", "actions", "bruitage"] as const

/** Étape « Vidéo et timeline » (maquette 4) : lancement de la phase vidéo, aperçu, plan sélectionné, barre, pistes. */
export function EcranTimeline({ projet, director, recharger }: ProprietesEcran) {
  const { timeline, segments, actions, chargement, erreur: erreurTimeline, recharger: rechargerTimeline } = useTimelineDirector(projet.id)
  const toutRecharger = useCallback(() => {
    recharger()
    rechargerTimeline()
  }, [recharger, rechargerTimeline])
  const { erreur, enCours, executer } = useAction(toutRecharger)
  const [selection, setSelection] = useState<string | null>(null)
  const [tete, setTete] = useState(0)
  const [lecture, setLecture] = useState(false)
  const [magnetisme, setMagnetisme] = useState(true)
  const [zoom, setZoom] = useState<number | null>(null)

  if (timeline === null && chargement) return <p className="text-[color:var(--v-text-3)]">Chargement…</p>

  if (timeline === null && projet.etat_phases.images === "termine" && projet.etat_phases.video === "a_faire") {
    return (
      <div className="flex flex-col gap-4">
        <LancementVideo projetId={projet.id} executer={executer} enCours={enCours} />
        {erreur && <Alerte>{erreur}</Alerte>}
      </div>
    )
  }

  if (timeline === null) {
    return (
      <Carte titre="Timeline">
        <p className="m-0 text-sm">
          {erreurTimeline && erreurTimeline !== "Timeline introuvable"
            ? erreurTimeline
            : "La timeline apparaît quand les images de départ sont validées : un emplacement par plan, à sa place dans la chanson."}
        </p>
        <Button variant="outline" className="w-fit" onClick={() => naviguer({ page: "projet", projetId: projet.id, etape: "images" })}>
          Aller aux images
        </Button>
      </Carte>
    )
  }

  const px = zoom ?? zoomInitial(timeline.duree_chanson_s)
  const clipChoisi = timeline.clips.find((clip) => clip.id === selection) ?? null
  const videos = timeline.clips.filter((clip) => clip.piste.startsWith("V"))
  const finMontage = Math.max(0, ...videos.map((clip) => finClip(clip)))
  const rendus = videos.filter((clip) => clip.etat === "brut" || clip.etat === "upscale" || clip.etat === "dlss5").length
  const erreurs = CLES_ERREURS.map((cle) => director?.erreurs[cle]).filter((message): message is string => Boolean(message))

  function placer(clipId: string, placement: Placement) {
    void executer(() => actionsTimeline.modifierClip(projet.id, clipId, placement))
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-[color:var(--v-text-2)]">
        <span>
          {projet.format} · {timeline.fps_maitre} fps · {projet.plans.length} plans · {rendus} rendus · {formatDuree(finMontage)} sur{" "}
          {formatDuree(timeline.duree_chanson_s)}
        </span>
        <Button variant="accent" onClick={() => naviguer({ page: "projet", projetId: projet.id, etape: "export" })}>
          Exporter
        </Button>
      </div>
      {projet.etat_phases.video === "a_faire" && <LancementVideo projetId={projet.id} executer={executer} enCours={enCours} />}
      {erreurs.map((message) => (
        <Alerte key={message}>{message}</Alerte>
      ))}
      {erreur && <Alerte>{erreur}</Alerte>}
      {erreurTimeline && <Alerte>{erreurTimeline}</Alerte>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,700px)_minmax(0,1fr)]">
        <Apercu projet={projet} timeline={timeline} segments={segments} tete_s={tete} lecture={lecture} onTete={setTete} onLecture={setLecture} />
        <PanneauPlan key={clipChoisi?.id ?? "aucun"} projet={projet} clip={clipChoisi} pistes={timeline.pistes} executer={executer} enCours={enCours} />
      </div>
      <BarreTimeline
        projet={projet}
        clip={clipChoisi}
        tete_s={tete}
        actions={actions}
        magnetisme={magnetisme}
        onMagnetisme={setMagnetisme}
        pxParSeconde={px}
        onZoom={setZoom}
        executer={executer}
        enCours={enCours}
      />
      <Pistes
        pistes={timeline.pistes}
        clips={timeline.clips}
        plans={projet.plans}
        sections={director?.analyse?.sections ?? []}
        tempsForts={director?.analyse?.temps_forts ?? []}
        duree_s={timeline.duree_chanson_s}
        fps={timeline.fps_maitre}
        pxParSeconde={px}
        magnetisme={magnetisme}
        selection={selection}
        tete_s={tete}
        onSelection={setSelection}
        onTete={setTete}
        onPlacer={placer}
      />
    </div>
  )
}

function LancementVideo({ projetId, executer, enCours }: { projetId: string; executer: Executer; enCours: boolean }) {
  const { donnees: estimation, erreur } = useDonnees(`estimation:${projetId}`, () => actionsTimeline.estimation(projetId))
  return (
    <BarreActions>
      <span className="flex-1">
        Vidéo et post-production en autonomie : la file tourne jusqu'au bout, un plan raté passe en rouge et le reste continue.
        {estimation &&
          ` ${estimation.plans} plans · ${formatTaille(estimation.octets_necessaires)} estimés · ${formatTaille(estimation.octets_libres)} libres.`}
      </span>
      {erreur && <span role="alert">{erreur}</span>}
      {estimation && !estimation.suffisant && (
        <span role="alert" className="text-[color:var(--status-danger-ink)]">
          Disque insuffisant
        </span>
      )}
      <Button variant="accent" disabled={enCours || !estimation?.suffisant} onClick={() => void executer(() => actionsDirector.lancer(projetId, "video"))}>
        Lancer la vidéo
      </Button>
    </BarreActions>
  )
}
