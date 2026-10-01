import { useId, useState } from "react"

import { actionsDirector, urlMediaProjet } from "@/api/director"
import { televerser } from "@/api/requetes"
import { useAction } from "@/api/use-action"
import { Alerte, Carte } from "@/components/commun/mise-en-page"
import { Button } from "@/components/ui/button"
import { formatDuree } from "@/lib/format"
import { naviguer } from "@/lib/use-route"

import type { ProprietesEcran } from "./commun"

export function EcranChanson({ projet, recharger }: ProprietesEcran) {
  const { erreur, enCours, executer } = useAction(recharger)
  const idFichier = useId()
  const [version, setVersion] = useState(0)
  const analyse = projet.etat_phases.analyse

  async function lancerAnalyse() {
    if (await executer(() => actionsDirector.lancer(projet.id, "analyse"))) {
      naviguer({ page: "projet", projetId: projet.id, etape: "analyse" })
    }
  }

  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <Carte titre="Chanson">
        {projet.chanson ? (
          <>
            <audio controls src={urlMediaProjet(projet.id, projet.chanson, version)} className="w-full" />
            <p className="m-0 text-sm text-[color:var(--v-text-2)]">
              {projet.chanson} · {formatDuree(projet.duree_chanson_s ?? 0)}
            </p>
          </>
        ) : (
          <p className="m-0 text-sm">Aucune chanson pour l'instant : envoie le fichier audio (mp3, wav, flac, m4a ou ogg).</p>
        )}
        {analyse === "a_faire" || analyse === "echec" ? (
          <div>
            <label
              htmlFor={idFichier}
              className="inline-flex h-10 cursor-pointer items-center rounded-full px-5 text-sm [box-shadow:inset_0_0_0_1px_var(--v-edge)] hover:bg-[var(--v-beige-2)]"
            >
              {enCours ? "Envoi…" : projet.chanson ? "Remplacer la chanson" : "Envoyer la chanson"}
            </label>
            <input
              id={idFichier}
              type="file"
              accept="audio/*"
              className="sr-only"
              onChange={(evenement) => {
                const fichier = evenement.target.files?.[0]
                evenement.target.value = ""
                if (fichier) {
                  void executer(() => televerser(`/api/projets/${encodeURIComponent(projet.id)}/chanson`, fichier)).then((ok) => {
                    if (ok) setVersion((v) => v + 1)
                  })
                }
              }}
            />
          </div>
        ) : (
          <p className="m-0 text-xs text-[color:var(--v-text-3)]">
            Chanson verrouillée depuis le lancement de l'analyse (pour une autre chanson, crée un nouveau projet).
          </p>
        )}
        {erreur && <Alerte>{erreur}</Alerte>}
      </Carte>
      <Carte titre="Paroles">
        {projet.paroles ? (
          <p className="m-0 whitespace-pre-wrap text-sm leading-[1.5]">{projet.paroles}</p>
        ) : (
          <p className="m-0 text-sm text-[color:var(--v-text-2)]">
            Pas de paroles fournies : elles seront transcrites pendant l'analyse, puis à relire.
          </p>
        )}
      </Carte>
      <Carte titre="Analyse">
        <p className="m-0 text-sm text-[color:var(--v-text-2)]">
          BPM, temps forts, sections, voix isolée et calage des paroles sur la voix.
        </p>
        {analyse === "en_cours" ? (
          <p className="m-0 text-sm">Analyse en cours dans la file GPU…</p>
        ) : (
          <div>
            <Button
              variant="accent"
              disabled={!projet.chanson || enCours || projet.plans.length > 0}
              title={projet.plans.length > 0 ? "Le découpage existe déjà : l'analyse ne se relance plus" : undefined}
              onClick={() => void lancerAnalyse()}
            >
              {analyse === "a_faire" ? "Lancer l'analyse" : "Relancer l'analyse"}
            </Button>
          </div>
        )}
      </Carte>
    </div>
  )
}
