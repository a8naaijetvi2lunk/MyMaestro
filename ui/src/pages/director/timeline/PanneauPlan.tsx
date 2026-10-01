import { Lock, TriangleAlert } from "lucide-react"
import { useState } from "react"

import type { Clip, Plan, Prise, Projet, SortiePostProd, TypeAction } from "@/api/client"
import { actionsDirector } from "@/api/director"
import { useDonnees } from "@/api/hooks"
import { actionsTimeline } from "@/api/timeline"
import { Carte } from "@/components/commun/mise-en-page"
import { ChampNombre, Curseur, Liste, Segments, ZoneTexte } from "@/components/formulaire/controles"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { LIBELLES_COURTS_VIDEO } from "@/lib/etapes"
import { formatDecimal, formatDuree, libelleMoteurVideo, libelleRole } from "@/lib/format"
import { MOTS_MAX_BRUITAGE, compterMots, libellePiste } from "@/lib/timeline"
import { cn } from "@/lib/utils"

import { ComparaisonAB } from "./ComparaisonAB"

type Executer = (action: () => Promise<unknown>) => Promise<boolean>
type Formulaire = "refaire" | "dlss5" | "bruitage" | "moteur"

const BOUTONS: readonly (readonly [Formulaire, string])[] = [
  ["refaire", "À refaire"],
  ["dlss5", "Passe DLSS5"],
  ["bruitage", "Bruitage (MMAudio)"],
  ["moteur", "Changer de moteur"],
]

const STATUTS_SORTIE: Record<string, string> = { en_file: "en file", en_cours: "en cours", termine: "terminé", echec: "échec" }

type Proprietes = { projet: Projet; clip: Clip | null; pistes: readonly string[]; executer: Executer; enCours: boolean }

/** Plan sélectionné (maquette 4) : verrou, paroles, prises, sorties de post-production, actions à programmer. */
export function PanneauPlan({ projet, clip, pistes, executer, enCours }: Proprietes) {
  if (clip === null) {
    return (
      <Carte titre="Plan sélectionné">
        <p className="m-0 text-sm text-[color:var(--v-text-2)]">
          Choisis un clip dans les pistes : ses prises, ses sorties et les actions à programmer s'affichent ici.
        </p>
      </Carte>
    )
  }
  const plan = clip.plan_id ? projet.plans.find((p) => p.id === clip.plan_id) : undefined
  if (plan === undefined) return <PanneauSon projet={projet} clip={clip} pistes={pistes} executer={executer} enCours={enCours} />
  return <PanneauVideo projet={projet} clip={clip} plan={plan} pistes={pistes} executer={executer} enCours={enCours} />
}

function libelleSortie(sortie: SortiePostProd): string {
  if (sortie.etape === "flashvsr") return `${sortie.ordre} · FlashVSR ×2`
  const style = typeof sortie.reglages.style === "string" ? ` · ${sortie.reglages.style}` : ""
  const intensite = typeof sortie.reglages.intensite === "number" ? ` ${formatDecimal(sortie.reglages.intensite)}` : ""
  return `${sortie.ordre} · DLSS5${style}${intensite}`
}

function etiquettePrise(prise: Prise, active: boolean): string {
  if (active) return "active"
  if (prise.statut === "termine") {
    const sortie = prise.sorties.find((s) => s.id === prise.sortie_active_id)
    return sortie ? (sortie.etape === "flashvsr" ? "FlashVSR" : "DLSS5") : "brut"
  }
  return STATUTS_SORTIE[prise.statut] ?? prise.statut
}

function LigneSortie({ libelle, etat, active, erreur, desactive, onChoisir }: {
  libelle: string
  etat: string
  active: boolean
  erreur: string | null
  desactive: boolean
  onChoisir: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={desactive}
      title={erreur ?? undefined}
      onClick={onChoisir}
      className={cn(
        "flex w-full justify-between gap-3 rounded-[8px] px-1 py-0.5 text-left",
        active ? "font-semibold" : "text-[color:var(--v-text-2)]",
        !desactive && "hover:bg-[var(--v-beige-2)]",
      )}
    >
      <span>{libelle}</span>
      <span className={cn(active && "text-[color:var(--v-olive-ink)]", etat === "échec" && "text-[color:var(--status-danger-ink)]")}>
        {active ? "sortie active" : etat}
      </span>
    </button>
  )
}

/** Changement de piste : uniquement vers une piste du même type (V* pour une vidéo, A1… pour un son, jamais A0). */
function SelecteurPiste({ projet, clip, pistes, executer, enCours }: { projet: Projet; clip: Clip; pistes: readonly string[]; executer: Executer; enCours: boolean }) {
  const prefixe = clip.piste.startsWith("V") ? "V" : "A"
  const possibles = pistes.filter((piste) => piste.startsWith(prefixe) && piste !== "A0")
  return (
    <div className={cn("flex flex-wrap items-center gap-2 text-[13px]", enCours && "opacity-60")}>
      <span>Piste</span>
      <Liste
        libelle="Piste"
        options={possibles.map((piste) => ({ valeur: piste, libelle: `${piste} · ${libellePiste(piste)}` }))}
        valeur={clip.piste}
        onChange={(valeur) => {
          if (!enCours && valeur !== clip.piste) void executer(() => actionsTimeline.modifierClip(projet.id, clip.id, { piste: String(valeur) }))
        }}
      />
    </div>
  )
}

function PanneauVideo({ projet, clip, plan, pistes, executer, enCours }: { projet: Projet; clip: Clip; plan: Plan; pistes: readonly string[]; executer: Executer; enCours: boolean }) {
  const [formulaire, setFormulaire] = useState<Formulaire | null>(null)
  const [comparer, setComparer] = useState(false)
  const [graine, setGraine] = useState<number | null>(null)
  const [style, setStyle] = useState<"Cinematic" | "Default">("Cinematic")
  const [intensite, setIntensite] = useState(1)
  const [invite, setInvite] = useState(plan.prompt_son)
  const [moteur, setMoteur] = useState("")
  const compat = useDonnees(`compatibilites:${projet.id}`, () => actionsDirector.compatibilites(projet.id))
  const prises = projet.prises.filter((p) => p.plan_id === plan.id)
  const active = prises.find((p) => p.id === plan.prise_active_id) ?? null
  const rendues = prises.filter((p) => p.statut === "termine")
  const rendu = active?.statut === "termine"
  const ancre = Math.abs(clip.position_s - clip.entree_s - plan.debut_s) <= 1e-3
  const moteursPossibles = (compat.donnees?.[plan.id] ?? []).filter((c) => c.compatible && c.moteur !== plan.moteur_video)
  const moteurChoisi = moteursPossibles.find((c) => c.moteur === moteur) ?? moteursPossibles[0]
  const mots = compterMots(invite)

  function programmer(type: TypeAction, reglages: Record<string, unknown>) {
    void executer(() => actionsTimeline.programmer(projet.id, { type, plan_id: plan.id, clip_id: clip.id, reglages })).then((ok) => {
      if (ok) setFormulaire(null)
    })
  }

  return (
    <section aria-label="Plan sélectionné" className="flex flex-col gap-3.5 rounded-[var(--r-card)] bg-card p-[18px] text-card-foreground">
      <div className="flex items-center justify-between gap-3">
        <h2 className="m-0 font-cojeev-display text-[21px] font-bold">
          Plan {plan.indice + 1} · {libelleRole(plan.role)}
        </h2>
        <Badge variant={plan.role === "chante" ? "pink-soft" : "blue-soft"}>{libelleMoteurVideo(plan.moteur_video)}</Badge>
      </div>
      {clip.verrou_chanson ? (
        <div className="flex items-start gap-2 rounded-[12px] bg-[var(--v-beige)] px-3 py-2.5 text-[13px] text-[color:var(--v-text-2)]">
          <Lock aria-hidden="true" className="mt-px size-4 shrink-0" />
          <span className="flex-1">
            Ancré à la chanson à {formatDuree(plan.debut_s)}. Le déplacer casserait le lip-sync ; on peut rogner, la synchro suit.
          </span>
          <Button size="sm" variant="ghost" disabled={enCours} onClick={() => void executer(() => actionsTimeline.modifierClip(projet.id, clip.id, { verrou_chanson: false }))}>
            Déverrouiller
          </Button>
        </div>
      ) : plan.role === "chante" ? (
        <div className="flex flex-col gap-2 rounded-[12px] bg-[var(--status-danger-bg)] px-3 py-2.5 text-[13px] text-[color:var(--status-danger-ink)]">
          <span className="flex items-start gap-2">
            <TriangleAlert aria-hidden="true" className="mt-px size-4 shrink-0" />
            {ancre ? "Déverrouillé, mais toujours à sa place : le lip-sync tient." : "Lip-sync cassé : ce plan n'est plus calé sur son chant."}
          </span>
          {ancre ? (
            <Button size="sm" variant="outline" className="w-fit" disabled={enCours} onClick={() => void executer(() => actionsTimeline.modifierClip(projet.id, clip.id, { verrou_chanson: true }))}>
              Reverrouiller
            </Button>
          ) : (
            <Button size="sm" variant="outline" className="w-fit" disabled={enCours || !plan.image_depart} onClick={() => programmer("refaire", { a_la_position: true })}>
              À refaire à cette position
            </Button>
          )}
        </div>
      ) : null}
      {plan.paroles && <p className="m-0 text-sm italic">« {plan.paroles} »</p>}
      <SelecteurPiste projet={projet} clip={clip} pistes={pistes} executer={executer} enCours={enCours} />
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-[.06em] text-[color:var(--v-text-3)]">Prises</span>
          <Button size="sm" variant="outline" disabled={rendues.length < 2} onClick={() => setComparer(true)}>
            Comparer A/B
          </Button>
        </div>
        {prises.length === 0 ? (
          <p className="m-0 text-[13px] text-[color:var(--v-text-3)]">Pas encore rendu.</p>
        ) : (
          <div role="group" aria-label="Prise active" className="flex flex-wrap gap-1.5 rounded-[18px] bg-[var(--v-beige)] p-1">
            {prises.map((prise) => {
              const estActive = prise.id === plan.prise_active_id
              return (
                <button
                  key={prise.id}
                  type="button"
                  aria-pressed={estActive}
                  disabled={prise.statut !== "termine" || enCours || estActive}
                  onClick={() => void executer(() => actionsTimeline.choisirPrise(projet.id, plan.id, prise.id))}
                  className={cn(
                    "h-8 flex-1 rounded-full px-3 text-[13px] whitespace-nowrap",
                    estActive ? "bg-card font-semibold" : "bg-transparent text-[color:var(--v-text-2)]",
                  )}
                >
                  Prise {prise.numero} · {etiquettePrise(prise, estActive)}
                </button>
              )
            })}
          </div>
        )}
        {active?.statut === "echec" && active.erreur && (
          <p role="alert" className="m-0 text-[13px] text-[color:var(--status-danger-ink)]">
            {active.erreur}
          </p>
        )}
      </div>
      {active !== null && rendu && (
        <ol aria-label="Sorties de la prise active" className="m-0 flex list-none flex-col gap-1 p-0 text-[13px]">
          <li>
            <LigneSortie
              libelle="Rendu brut"
              etat="terminé"
              active={active.sortie_active_id === null}
              erreur={null}
              desactive={enCours || active.sortie_active_id === null}
              onChoisir={() => void executer(() => actionsTimeline.choisirSortie(projet.id, active.id, null))}
            />
          </li>
          {active.sorties.map((sortie) => (
            <li key={sortie.id}>
              <LigneSortie
                libelle={libelleSortie(sortie)}
                etat={STATUTS_SORTIE[sortie.statut] ?? sortie.statut}
                active={sortie.id === active.sortie_active_id}
                erreur={sortie.erreur}
                desactive={enCours || sortie.statut !== "termine" || sortie.id === active.sortie_active_id}
                onChoisir={() => void executer(() => actionsTimeline.choisirSortie(projet.id, active.id, sortie.id))}
              />
            </li>
          ))}
        </ol>
      )}
      <div className="mt-auto grid grid-cols-2 gap-2">
        {BOUTONS.map(([cle, libelle]) => (
          <Button
            key={cle}
            size="sm"
            variant={formulaire === cle ? "default" : "outline"}
            aria-expanded={formulaire === cle}
            disabled={enCours || ((cle === "dlss5" || cle === "bruitage") && !rendu)}
            onClick={() => setFormulaire((actuel) => (actuel === cle ? null : cle))}
          >
            {libelle}
          </Button>
        ))}
      </div>
      {formulaire === "refaire" && (
        <div className="flex flex-wrap items-center gap-2 rounded-[12px] bg-[var(--v-beige-2)] p-3 text-[13px]">
          <span>Graine (vide : au hasard)</span>
          <ChampNombre
            libelle="Graine"
            min={0}
            valeur={graine ?? undefined}
            onChange={(valeur) => {
              if (valeur >= 0) setGraine(Math.floor(valeur))
            }}
          />
          <Button size="sm" variant="ghost" disabled={graine === null} onClick={() => setGraine(null)}>
            Au hasard
          </Button>
          <Button size="sm" variant="accent" disabled={enCours} onClick={() => programmer("refaire", graine === null ? {} : { graine })}>
            Programmer
          </Button>
        </div>
      )}
      {formulaire === "dlss5" && (
        <div className="flex flex-col gap-2.5 rounded-[12px] bg-[var(--v-beige-2)] p-3 text-[13px]">
          <Segments
            libelle="Style DLSS5"
            options={[
              { valeur: "Cinematic", libelle: "Cinematic" },
              { valeur: "Default", libelle: "Default" },
            ]}
            valeur={style}
            onChange={(valeur) => setStyle(valeur === "Default" ? "Default" : "Cinematic")}
          />
          <Curseur libelle="Intensité" min={0} max={2} pas={0.1} valeur={intensite} onChange={setIntensite} />
          <Button size="sm" variant="accent" className="w-fit" disabled={enCours} onClick={() => programmer("passe_dlss5", { style, intensite })}>
            Programmer
          </Button>
        </div>
      )}
      {formulaire === "bruitage" && (
        <div className="flex flex-col gap-2.5 rounded-[12px] bg-[var(--v-beige-2)] p-3 text-[13px]">
          <ZoneTexte libelle={`Invite (${mots} / ${MOTS_MAX_BRUITAGE} mots, l'essentiel en tête, sans négation)`} valeur={invite} onChange={setInvite} lignes={3} />
          <Button size="sm" variant="accent" className="w-fit" disabled={enCours || mots > MOTS_MAX_BRUITAGE} onClick={() => programmer("bruitage", { prompt: invite })}>
            Programmer
          </Button>
        </div>
      )}
      {formulaire === "moteur" && (
        <div className="flex flex-wrap items-center gap-2 rounded-[12px] bg-[var(--v-beige-2)] p-3 text-[13px]">
          {moteurChoisi === undefined ? (
            compat.donnees === null && compat.chargement ? (
              <span>Chargement des moteurs compatibles…</span>
            ) : compat.erreur ? (
              <span role="alert" className="text-[color:var(--status-danger-ink)]">
                {compat.erreur}
              </span>
            ) : (
              <span>Aucun autre moteur compatible avec la durée de ce plan.</span>
            )
          ) : (
            <>
              <Liste
                libelle="Nouveau moteur"
                options={moteursPossibles.map((c) => ({
                  valeur: c.moteur,
                  libelle: `${LIBELLES_COURTS_VIDEO[c.moteur] ?? c.moteur}${c.note ? ` (${c.note})` : ""}`,
                }))}
                valeur={moteurChoisi.moteur}
                onChange={(valeur) => setMoteur(String(valeur))}
              />
              <Button size="sm" variant="accent" disabled={enCours} onClick={() => programmer("changer_moteur", { moteur: moteurChoisi.moteur })}>
                Programmer
              </Button>
              {moteurChoisi.avertissement && <span className="w-full text-[color:var(--status-danger-ink)]">{moteurChoisi.avertissement}</span>}
            </>
          )}
        </div>
      )}
      {comparer && (
        <ComparaisonAB
          projetId={projet.id}
          prises={rendues}
          activeId={plan.prise_active_id}
          fermer={() => setComparer(false)}
          choisir={(priseId) => void executer(() => actionsTimeline.choisirPrise(projet.id, plan.id, priseId))}
        />
      )}
    </section>
  )
}

function PanneauSon({ projet, clip, pistes, executer, enCours }: { projet: Projet; clip: Clip; pistes: readonly string[]; executer: Executer; enCours: boolean }) {
  const [volume, setVolume] = useState(clip.volume)
  const [fonduEntree, setFonduEntree] = useState(clip.fondu_entree_s)
  const [fonduSortie, setFonduSortie] = useState(clip.fondu_sortie_s)
  const chanson = clip.piste === "A0"
  const modifie = volume !== clip.volume || fonduEntree !== clip.fondu_entree_s || fonduSortie !== clip.fondu_sortie_s
  return (
    <Carte titre={chanson ? "Chanson · piste maîtresse" : `Son · ${clip.piste}`}>
      <p className="m-0 truncate text-[13px] text-[color:var(--v-text-2)]">{clip.fichier_audio}</p>
      {chanson && <p className="m-0 text-[13px]">La chanson ne bouge pas : c'est elle qui cale les plans chantés.</p>}
      {!chanson && <SelecteurPiste projet={projet} clip={clip} pistes={pistes} executer={executer} enCours={enCours} />}
      <Curseur libelle="Volume" min={0} max={2} pas={0.05} valeur={volume} onChange={setVolume} />
      {!chanson && (
        <div className="flex flex-wrap items-center gap-3 text-[13px]">
          <span>Fondu d'entrée (s)</span>
          <ChampNombre libelle="Fondu d'entrée" min={0} valeur={fonduEntree} onChange={setFonduEntree} />
          <span>Fondu de sortie (s)</span>
          <ChampNombre libelle="Fondu de sortie" min={0} valeur={fonduSortie} onChange={setFonduSortie} />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="accent"
          disabled={!modifie || enCours}
          onClick={() =>
            void executer(() =>
              actionsTimeline.modifierClip(
                projet.id,
                clip.id,
                chanson ? { volume } : { volume, fondu_entree_s: fonduEntree, fondu_sortie_s: fonduSortie },
              ),
            )
          }
        >
          Appliquer
        </Button>
        {!chanson && (
          <Button size="sm" variant="ghost" disabled={enCours} onClick={() => void executer(() => actionsTimeline.supprimerClip(projet.id, clip.id))}>
            Retirer ce son
          </Button>
        )}
      </div>
    </Carte>
  )
}
