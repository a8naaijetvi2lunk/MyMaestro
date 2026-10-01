import { Pause, Play } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import type { Projet, Segment, Timeline } from "@/api/client"
import { urlMediaProjet } from "@/api/director"
import { formatDuree } from "@/lib/format"
import { segmentAuTemps } from "@/lib/timeline"
import { cn } from "@/lib/utils"

type Proprietes = {
  projet: Projet
  timeline: Timeline
  segments: readonly Segment[]
  tete_s: number
  lecture: boolean
  onTete: (temps_s: number) => void
  onLecture: (lecture: boolean) => void
}

/**
 * Aperçu : la chanson est l'horloge ; la vidéo montre le fichier du segment projeté à la tête de lecture
 * (ce que tu vois est ce qui sera exporté). Changer de source recharge le média : le décalage voulu est
 * reposé dans `onLoadedMetadata`, depuis une ref tenue à jour par un effet.
 */
export function Apercu({ projet, timeline, segments, tete_s, lecture, onTete, onLecture }: Proprietes) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const attenduRef = useRef(0)
  const [erreurAudio, setErreurAudio] = useState(false)
  const chanson = timeline.clips.find((clip) => clip.piste === "A0")?.fichier_audio ?? projet.chanson
  const segment = segmentAuTemps(segments, tete_s)
  const source = segment?.fichier ? urlMediaProjet(projet.id, segment.fichier) : null
  const decalage = segment ? segment.source_debut_s + (tete_s - segment.debut_s) : 0
  const plan = segment?.plan_id ? projet.plans.find((p) => p.id === segment.plan_id) : undefined

  // La vidéo suit la tête : recalée à l'arrêt, ou si elle dérive de plus de 0,25 s en lecture.
  useEffect(() => {
    attenduRef.current = decalage
    const video = videoRef.current
    if (video === null || source === null || video.readyState < 1) return
    if (!lecture || Math.abs(video.currentTime - decalage) > 0.25) video.currentTime = decalage
  }, [decalage, source, lecture])

  // La chanson suit la tête : à l'arrêt, et en lecture pour un saut voulu (règle, curseur) au-delà du retard de la rAF.
  useEffect(() => {
    const audio = audioRef.current
    if (audio === null) return
    if (!lecture) {
      audio.pause()
      videoRef.current?.pause()
      if (Math.abs(audio.currentTime - tete_s) > 0.05) audio.currentTime = tete_s
      return
    }
    if (Math.abs(audio.currentTime - tete_s) > 0.25) audio.currentTime = tete_s
  }, [tete_s, lecture])

  // En lecture, la tête suit le temps de la chanson (au plus une fois toutes les 80 ms).
  useEffect(() => {
    if (!lecture) return
    let cadre = 0
    let dernier = 0
    const suivre = (instant: number) => {
      const audio = audioRef.current
      if (audio !== null && instant - dernier > 80) {
        dernier = instant
        onTete(audio.currentTime)
        if (audio.ended) onLecture(false)
      }
      cadre = requestAnimationFrame(suivre)
    }
    cadre = requestAnimationFrame(suivre)
    return () => cancelAnimationFrame(cadre)
  }, [lecture, onTete, onLecture])

  async function basculer() {
    const audio = audioRef.current
    if (audio === null) return
    if (lecture) {
      onLecture(false)
      return
    }
    try {
      audio.currentTime = tete_s
      await audio.play()
      setErreurAudio(false)
      onLecture(true)
      void videoRef.current?.play().catch(() => undefined)
    } catch {
      setErreurAudio(true)
    }
  }

  return (
    <section aria-label="Aperçu" className="flex rounded-[var(--r-card)] bg-card p-3 text-card-foreground">
      <div className="flex min-h-[340px] w-full flex-col justify-between gap-3 rounded-[14px] bg-[var(--v-structure)] p-4 text-[color:var(--structure-text)]">
        <div className="flex justify-between gap-3 text-xs text-[color:var(--sidebar-muted)]">
          <span>{plan ? `Plan ${plan.indice + 1}${segment?.fichier ? "" : " · pas encore rendu"}` : "Noir"}</span>
          <span>Ce que tu vois = ce qui sera exporté</span>
        </div>
        <div
          className={cn(
            "relative mx-auto flex items-center justify-center overflow-hidden rounded-[10px] bg-[var(--media-noir)]",
            projet.format === "9:16" ? "aspect-[9/16] h-[260px]" : "aspect-video w-full max-w-[560px]",
          )}
        >
          {source !== null ? (
            <video
              ref={videoRef}
              src={source}
              muted
              playsInline
              preload="auto"
              className="size-full object-contain"
              onLoadedMetadata={(evenement) => {
                evenement.currentTarget.currentTime = attenduRef.current
                if (lecture) void evenement.currentTarget.play().catch(() => undefined)
              }}
            />
          ) : plan?.image_depart ? (
            <img
              src={urlMediaProjet(projet.id, plan.image_depart)}
              alt={`Image de départ du plan ${plan.indice + 1}`}
              className="size-full object-contain opacity-60"
            />
          ) : null}
        </div>
        {chanson && <audio ref={audioRef} src={urlMediaProjet(projet.id, chanson)} preload="auto" onError={() => setErreurAudio(true)} />}
        {erreurAudio && (
          <p role="alert" className="m-0 text-xs text-[color:var(--v-pink)]">
            Chanson illisible : l'aperçu ne peut pas jouer.
          </p>
        )}
        <div className="flex items-center gap-3">
          <button
            type="button"
            aria-label={lecture ? "Pause" : "Lecture"}
            disabled={!chanson}
            onClick={() => void basculer()}
            className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[var(--on-structure)] text-[color:var(--v-structure)]"
          >
            {lecture ? <Pause aria-hidden="true" className="size-4" /> : <Play aria-hidden="true" className="size-4" />}
          </button>
          <span className="text-[13px] tabular-nums">
            {formatDuree(tete_s)} / {formatDuree(timeline.duree_chanson_s)}
          </span>
          <input
            type="range"
            aria-label="Tête de lecture"
            min={0}
            max={timeline.duree_chanson_s}
            step={0.04}
            value={tete_s}
            onChange={(evenement) => onTete(Number(evenement.target.value))}
            className="flex-1 accent-[var(--v-pink)]"
          />
        </div>
      </div>
    </section>
  )
}
