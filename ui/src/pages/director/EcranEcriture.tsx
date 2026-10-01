import { Send } from "lucide-react"
import { useId, useState, type FormEvent } from "react"

import { api, type Brief, type Concept, type MessageChat, type Projet } from "@/api/client"
import { actionsDirector } from "@/api/director"
import { useDonnees } from "@/api/hooks"
import { exiger } from "@/api/requetes"
import { useAction } from "@/api/use-action"
import { Alerte, Carte } from "@/components/commun/mise-en-page"
import { ZoneTexte } from "@/components/formulaire/controles"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { formatDecimal, formatDuree, libelleMoteurVideo, libelleRole } from "@/lib/format"
import { naviguer } from "@/lib/use-route"
import { cn } from "@/lib/utils"

import { CarteCasting } from "./CarteCasting"
import type { ProprietesEcran } from "./commun"

const PASTILLES_CONCEPT = ["bg-[var(--v-pink)]", "bg-[var(--v-blue)]", "bg-[var(--v-olive)]", "bg-[var(--v-yellow)]", "bg-[var(--v-pink)]"]

export function EcranEcriture({ projet, director, recharger }: ProprietesEcran) {
  const { erreur, enCours, executer } = useAction(recharger)
  const [message, setMessage] = useState("")
  const { donnees: fiches } = useDonnees("bibliotheque", () => exiger(api.GET("/api/bibliotheque")))
  const etat = projet.etat_phases.ecriture
  const attente = director?.en_attente ?? []
  const concepts = director?.concepts ?? []
  const retenu = director?.concept_retenu ?? null

  if (etat === "a_faire") {
    return (
      <Carte titre="Écriture">
        <p className="m-0 text-sm">L'écriture s'ouvre quand l'analyse est terminée.</p>
      </Carte>
    )
  }

  async function envoyer(evenement?: FormEvent) {
    evenement?.preventDefault()
    const texte = message.trim()
    if (!texte) return
    if (await executer(() => actionsDirector.message(projet.id, texte))) setMessage("")
  }

  async function validerEcriture() {
    if (await executer(() => actionsDirector.valider(projet.id, "ecriture"))) {
      naviguer({ page: "projet", projetId: projet.id, etape: "prompts" })
    }
  }

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex flex-col gap-3.5">
        <CarteBrief
          key={JSON.stringify(director?.brief ?? {})}
          brief={director?.brief ?? { ambiance: "", genre: "", envies: "" }}
          enregistrer={(brief) => executer(() => actionsDirector.brief(projet.id, brief))}
        />
        <CarteCasting key={projet.casting.join("|")} projet={projet} fiches={fiches ?? []} executer={executer} />
        <h2 className="m-0 mt-1 text-xs font-semibold uppercase tracking-[.06em] text-[color:var(--v-text-3)]">
          {concepts.length > 1 ? `${concepts.length} concepts contrastés` : concepts.length === 1 ? "1 concept" : "Concepts"}
        </h2>
        {concepts.map((concept, indice) => (
          <CarteConcept
            key={`${indice}-${concept.titre}`}
            concept={concept}
            indice={indice}
            retenu={retenu === indice}
            retenir={() => void executer(() => actionsDirector.retenir(projet.id, indice))}
            melanger={() => {
              const base = retenu !== null && retenu !== indice ? concepts[retenu]?.titre : null
              setMessage(base ? `Mélange « ${base} » avec « ${concept.titre} » : ` : `Reprends « ${concept.titre} » en changeant : `)
            }}
          />
        ))}
        <div>
          <Button
            variant="outline"
            disabled={enCours || attente.includes("ecriture.concepts")}
            onClick={() => void executer(() => actionsDirector.concepts(projet.id))}
          >
            {attente.includes("ecriture.concepts") ? "Opus propose des concepts…" : concepts.length > 0 ? "Proposer d'autres concepts" : "Proposer des concepts"}
          </Button>
        </div>
        {director?.erreurs.ecriture && <Alerte>{director.erreurs.ecriture}</Alerte>}
        {erreur && <Alerte>{erreur}</Alerte>}
        {projet.plans.length > 0 && (
          <CarteDecoupage projet={projet} enAttente={etat === "a_valider"} valider={() => void validerEcriture()} occupe={enCours} />
        )}
      </div>
      <PanneauChat
        messages={director?.chat ?? []}
        opusEcrit={attente.includes("ecriture.chat")}
        message={message}
        setMessage={setMessage}
        envoyer={(evenement) => void envoyer(evenement)}
        peutDecouper={retenu !== null && !attente.includes("ecriture.decoupage")}
        decoupageEnCours={attente.includes("ecriture.decoupage")}
        ecrireDecoupage={() => void executer(() => actionsDirector.decoupage(projet.id))}
      />
    </div>
  )
}

function CarteBrief({ brief, enregistrer }: { brief: Brief; enregistrer: (brief: Brief) => Promise<boolean> }) {
  const [edition, setEdition] = useState(false)
  const [brouillon, setBrouillon] = useState<Brief>(brief)
  const champs: { cle: keyof Brief; libelle: string }[] = [
    { cle: "ambiance", libelle: "Ambiance" },
    { cle: "genre", libelle: "Genre" },
    { cle: "envies", libelle: "Envies" },
  ]

  async function sauver() {
    if (await enregistrer(brouillon)) setEdition(false)
  }

  return (
    <Carte
      titre="Brief"
      actions={
        edition ? (
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => setEdition(false)}>
              Annuler
            </Button>
            <Button size="sm" variant="accent" onClick={() => void sauver()}>
              Enregistrer
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setEdition(true)}>
            Modifier
          </Button>
        )
      }
    >
      {edition ? (
        <div className="grid gap-3 md:grid-cols-3">
          {champs.map(({ cle, libelle }) => (
            <ZoneTexte key={cle} libelle={libelle} valeur={brouillon[cle] ?? ""} onChange={(valeur) => setBrouillon({ ...brouillon, [cle]: valeur })} lignes={3} />
          ))}
        </div>
      ) : (
        <dl className="m-0 grid grid-cols-1 gap-x-5 gap-y-2.5 text-[13px] md:grid-cols-2">
          {champs.map(({ cle, libelle }) => (
            <div key={cle}>
              <dt className="text-[color:var(--v-text-3)]">{libelle}</dt>
              <dd className="m-0 mt-0.5">{brief[cle] || "—"}</dd>
            </div>
          ))}
        </dl>
      )}
    </Carte>
  )
}

function CarteConcept({ concept, indice, retenu, retenir, melanger }: { concept: Concept; indice: number; retenu: boolean; retenir: () => void; melanger: () => void }) {
  return (
    <article
      className={cn(
        "flex gap-4 rounded-[var(--r-card)] bg-card p-4 text-card-foreground",
        retenu && "[box-shadow:0_0_0_2px_var(--v-canvas),0_0_0_4px_var(--v-ink)]",
      )}
    >
      <div
        className={cn(
          "flex size-16 shrink-0 items-center justify-center rounded-[20px_20px_20px_6px] font-cojeev-display text-[26px] font-bold text-[color:var(--v-structure)]",
          PASTILLES_CONCEPT[indice % PASTILLES_CONCEPT.length],
        )}
      >
        {indice + 1}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="m-0 font-cojeev-display text-[19px] font-bold">{concept.titre}</h3>
          {retenu && <Badge variant="ink" size="sm">Retenu</Badge>}
        </div>
        <p className="m-0 text-sm leading-[1.45]">{concept.pitch}</p>
        {(concept.arc || concept.traitement) && (
          <p className="m-0 text-xs text-[color:var(--v-text-3)]">
            {[concept.arc && `Arc : ${concept.arc}`, concept.traitement && `Traitement : ${concept.traitement}`].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>
      <div className="flex flex-col justify-center gap-1.5">
        {!retenu && (
          <Button size="sm" onClick={retenir}>
            Retenir
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={melanger}>
          Mélanger avec…
        </Button>
      </div>
    </article>
  )
}

function CarteDecoupage({ projet, enAttente, valider, occupe }: { projet: Projet; enAttente: boolean; valider: () => void; occupe: boolean }) {
  return (
    <Carte
      titre="Découpage"
      actions={
        enAttente && (
          <Button variant="accent" size="sm" disabled={occupe} onClick={valider}>
            Valider l'écriture et lancer les prompts
          </Button>
        )
      }
    >
      <table className="w-full text-left text-[13px]">
        <thead className="text-xs text-[color:var(--v-text-3)]">
          <tr>
            <th scope="col" className="py-1.5">#</th>
            <th scope="col">Rôle</th>
            <th scope="col">Début · durée</th>
            <th scope="col">Moteur</th>
            <th scope="col">Paroles / description</th>
          </tr>
        </thead>
        <tbody>
          {projet.plans.map((plan) => (
            <tr key={plan.id} className="border-t border-[var(--v-beige)]">
              <td className="py-2 font-bold">{plan.indice + 1}</td>
              <td>
                <Badge variant={plan.role === "chante" ? "pink-soft" : "blue-soft"}>{libelleRole(plan.role)}</Badge>
              </td>
              <td className="tabular-nums">
                {formatDuree(plan.debut_s)} · {formatDecimal(plan.duree_s)} s
              </td>
              <td>{libelleMoteurVideo(plan.moteur_video)}</td>
              <td className={plan.paroles ? "italic" : "text-[color:var(--v-text-2)]"}>{plan.paroles ? `« ${plan.paroles} »` : plan.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Carte>
  )
}

function PanneauChat({
  messages,
  opusEcrit,
  message,
  setMessage,
  envoyer,
  peutDecouper,
  decoupageEnCours,
  ecrireDecoupage,
}: {
  messages: MessageChat[]
  opusEcrit: boolean
  message: string
  setMessage: (message: string) => void
  envoyer: (evenement?: FormEvent) => void
  peutDecouper: boolean
  decoupageEnCours: boolean
  ecrireDecoupage: () => void
}) {
  const idMessage = useId()
  return (
    <section aria-label="Affiner avec Opus" className="flex flex-col gap-3.5 rounded-[var(--r-panel)] bg-card p-[18px] text-card-foreground">
      <div className="flex items-center justify-between">
        <h2 className="m-0 font-cojeev-display text-[21px] font-bold">Affiner avec Opus</h2>
        <span className="flex items-center gap-1.5 text-xs text-[color:var(--v-olive-ink)]">
          <span aria-hidden="true" className={cn("size-2 rounded-full", opusEcrit ? "bg-[var(--v-yellow)]" : "bg-[var(--v-olive)]")} />
          {opusEcrit ? "Opus écrit…" : "Prêt"}
        </span>
      </div>
      <ol className="m-0 flex max-h-[480px] list-none flex-col gap-3 overflow-y-auto p-0">
        {messages.length === 0 && <li className="text-sm text-[color:var(--v-text-3)]">Retiens un concept, puis affine-le ici.</li>}
        {messages.map((m, indice) => (
          <li
            key={indice}
            className={cn(
              "max-w-[320px] px-3.5 py-3 text-sm leading-[1.45]",
              m.auteur === "utilisateur"
                ? "self-end rounded-[18px_18px_6px_18px] bg-[var(--v-ink)] text-[color:var(--v-on-ink)]"
                : "self-start rounded-[18px_18px_18px_6px] bg-[var(--v-beige)]",
            )}
          >
            {m.texte}
          </li>
        ))}
      </ol>
      <form onSubmit={envoyer} className="flex flex-col gap-2">
        <label htmlFor={idMessage} className="text-xs text-[color:var(--v-text-3)]">
          Ton message (Ctrl+Entrée pour envoyer)
        </label>
        <div className="flex items-end gap-2">
          <textarea
            id={idMessage}
            rows={2}
            value={message}
            placeholder="Affiner le concept…"
            onChange={(evenement) => setMessage(evenement.target.value)}
            onKeyDown={(evenement) => {
              if (evenement.key === "Enter" && (evenement.ctrlKey || evenement.metaKey) && !opusEcrit) envoyer()
            }}
            className="flex-1 resize-none rounded-[14px] border-0 bg-card px-3 py-2.5 text-sm [box-shadow:inset_0_0_0_1px_var(--v-edge)]"
          />
          <button
            type="submit"
            aria-label="Envoyer"
            disabled={!message.trim() || opusEcrit}
            className="flex size-11 items-center justify-center rounded-full bg-[var(--v-ink)] text-[color:var(--v-on-ink)] disabled:opacity-50"
          >
            <Send aria-hidden="true" className="size-[18px]" />
          </button>
        </div>
      </form>
      <Button variant="accent" size="lg" fullWidth disabled={!peutDecouper} onClick={ecrireDecoupage}>
        {decoupageEnCours ? "Découpage en cours…" : "Écrire le découpage"}
      </Button>
      <span className="text-center text-xs text-[color:var(--v-text-3)]">Plan par plan, durées calées sur les grilles des moteurs</span>
    </section>
  )
}
