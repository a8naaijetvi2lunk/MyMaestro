import { useId, useRef, useState, type RefObject } from "react"

import type { Prise } from "@/api/client"
import { urlMediaProjet } from "@/api/director"
import { Liste } from "@/components/formulaire/controles"
import { Button } from "@/components/ui/button"
import { fichierDePrise } from "@/lib/timeline"

type Proprietes = {
  projetId: string
  prises: readonly Prise[]
  activeId: string | null
  fermer: () => void
  choisir: (priseId: string) => void
}

/** Comparaison A/B de deux prises d'un plan : lectures lancées ensemble, le son vient de la prise A. */
export function ComparaisonAB({ projetId, prises, activeId, fermer, choisir }: Proprietes) {
  const titreId = useId()
  const premiere = activeId ?? prises[0]?.id ?? ""
  const [gauche, setGauche] = useState(premiere)
  const [droite, setDroite] = useState(prises.find((p) => p.id !== premiere)?.id ?? premiere)
  const [lecture, setLecture] = useState(false)
  const videoA = useRef<HTMLVideoElement>(null)
  const videoB = useRef<HTMLVideoElement>(null)
  const options = prises.map((prise) => ({ valeur: prise.id, libelle: `Prise ${prise.numero}${prise.id === activeId ? " (active)" : ""}` }))

  function basculer() {
    const videos = [videoA.current, videoB.current].filter((video): video is HTMLVideoElement => video !== null)
    if (lecture) {
      videos.forEach((video) => video.pause())
      setLecture(false)
      return
    }
    videos.forEach((video) => {
      video.currentTime = 0
      void video.play().catch(() => undefined)
    })
    setLecture(true)
  }

  function colonne(lettre: string, priseId: string, changer: (id: string) => void, ref: RefObject<HTMLVideoElement | null>, muet: boolean) {
    const prise = prises.find((p) => p.id === priseId)
    const fichier = prise ? fichierDePrise(prise) : null
    return (
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center justify-between gap-2 text-[13px] font-semibold">
          {lettre}
          <Liste libelle={`Prise ${lettre}`} options={options} valeur={priseId} onChange={(valeur) => changer(String(valeur))} className="h-8" />
        </div>
        <div className="flex aspect-video items-center justify-center overflow-hidden rounded-[12px] bg-[var(--media-noir)] text-xs text-[color:var(--structure-text)]">
          {fichier ? (
            <video ref={ref} src={urlMediaProjet(projetId, fichier)} muted={muet} playsInline preload="auto" className="size-full object-contain" onEnded={() => setLecture(false)} />
          ) : (
            "Pas de rendu"
          )}
        </div>
        <Button size="sm" variant="outline" disabled={!prise || prise.id === activeId} onClick={() => prise && choisir(prise.id)}>
          Garder la prise {prise?.numero ?? "?"}
        </Button>
      </div>
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--v-scrim)] p-4"
      onKeyDown={(evenement) => {
        if (evenement.key === "Escape") fermer()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titreId}
        className="flex w-full max-w-4xl flex-col gap-4 rounded-[var(--r-panel)] bg-card p-6 text-card-foreground shadow-[var(--shadow-float)]"
      >
        <h2 id={titreId} className="m-0 font-cojeev-display text-[21px] font-bold">
          Comparer deux prises
        </h2>
        <div className="flex flex-col gap-4 md:flex-row">
          {colonne("A", gauche, setGauche, videoA, false)}
          {colonne("B", droite, setDroite, videoB, true)}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={basculer}>
            {lecture ? "Pause" : "Lire les deux"}
          </Button>
          <Button variant="ghost" autoFocus onClick={fermer}>
            Fermer
          </Button>
        </div>
      </div>
    </div>
  )
}
