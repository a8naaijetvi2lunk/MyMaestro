import { Box, ImageIcon, Info, PersonStanding, Plus, ScanFace, Search } from "lucide-react"
import { useId, useState, type FormEvent, type ReactNode } from "react"

import { api, type FicheBibliotheque, type RoleImageFiche, type TypeFiche } from "@/api/client"
import { useDonnees } from "@/api/hooks"
import { executer, exiger, messageErreur, televerser, urlMedia } from "@/api/requetes"
import { Alerte, EnTetePage } from "@/components/commun/mise-en-page"
import { ChampTexte, Segments, ZoneTexte } from "@/components/formulaire/controles"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { compterParType, filtrerFiches } from "@/lib/bibliotheque"
import { cn } from "@/lib/utils"

type Teinte = "pink-soft" | "blue-soft" | "olive-soft"

const TYPES: ReadonlyArray<{ valeur: TypeFiche; libelle: string; pluriel: string; teinte: Teinte; roles: RoleImageFiche[] }> = [
  { valeur: "personnage", libelle: "Personnage", pluriel: "Personnages", teinte: "pink-soft", roles: ["portrait_pied", "gros_plan"] },
  { valeur: "decor", libelle: "Décor", pluriel: "Décors", teinte: "blue-soft", roles: ["reference"] },
  { valeur: "style", libelle: "Style", pluriel: "Styles", teinte: "olive-soft", roles: ["reference"] },
]

const LIBELLES_ROLE: Record<RoleImageFiche, string> = {
  portrait_pied: "Portrait en pied",
  gros_plan: "Gros plan du visage",
  reference: "Référence",
}

const ICONES_ROLE: Record<RoleImageFiche, ReactNode> = {
  portrait_pied: <PersonStanding aria-hidden="true" className="size-11" strokeWidth={1.4} />,
  gros_plan: <ScanFace aria-hidden="true" className="size-11" strokeWidth={1.4} />,
  reference: <ImageIcon aria-hidden="true" className="size-11" strokeWidth={1.4} />,
}

const FONDS: Record<Teinte, string> = {
  "pink-soft": "bg-[var(--v-pink-soft)] text-[color:var(--v-accent-ink)]",
  "blue-soft": "bg-[var(--v-blue-soft)] text-[color:var(--status-info-ink)]",
  "olive-soft": "bg-[var(--v-olive-soft)] text-[color:var(--v-olive-ink)]",
}

const GENERATION_A_VENIR = "La génération d'images depuis la bibliothèque arrive dans une prochaine version"

function typeDe(fiche: FicheBibliotheque) {
  return TYPES.find((t) => t.valeur === fiche.type) ?? TYPES[0]
}

export function PageBibliotheque() {
  const { donnees: fiches, erreur, recharger } = useDonnees("bibliotheque", () => exiger(api.GET("/api/bibliotheque")))
  const [filtre, setFiltre] = useState<string>("tout")
  const [recherche, setRecherche] = useState("")
  const [edition, setEdition] = useState<FicheBibliotheque | "nouvelle" | null>(null)

  const toutes = fiches ?? []
  const comptes = compterParType(toutes)
  const visibles = filtrerFiches(toutes, filtre, recherche)
  const options = [
    { valeur: "tout", libelle: `Tout · ${toutes.length}` },
    ...TYPES.map((t) => ({ valeur: t.valeur, libelle: `${t.pluriel} · ${comptes[t.valeur] ?? 0}` })),
  ]

  return (
    <div className="flex flex-col gap-4">
      <EnTetePage
        titre="Bibliothèque"
        sousTitre="Personnages, décors et styles, partagés entre tous les projets."
        actions={
          <>
            <label className="flex h-10 items-center gap-2 rounded-full bg-card px-3.5 text-sm [box-shadow:inset_0_0_0_1px_var(--v-edge)]">
              <Search aria-hidden="true" className="size-4 text-[color:var(--v-text-3)]" />
              <span className="sr-only">Rechercher une fiche</span>
              <input
                type="search"
                value={recherche}
                onChange={(evenement) => setRecherche(evenement.target.value)}
                placeholder="Rechercher…"
                className="w-[180px] border-0 bg-transparent text-sm outline-none"
              />
            </label>
            <Button variant="accent" onClick={() => setEdition("nouvelle")}>
              Nouvelle fiche
            </Button>
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <Segments libelle="Filtrer par type" options={options} valeur={filtre} onChange={(v) => setFiltre(String(v))} />
        <span className="ml-auto flex items-center gap-2 rounded-full bg-[var(--v-olive-soft)] px-3.5 py-2 text-[13px] text-[color:var(--v-olive-ink)]">
          <Info aria-hidden="true" className="size-4" />
          Références propres et isolées : un portrait en pied + un gros plan du visage, jamais de planche.
        </span>
      </div>
      {erreur && <Alerte>{erreur}</Alerte>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {visibles.map((fiche) => (
          <CarteFiche key={fiche.id} fiche={fiche} onModifier={() => setEdition(fiche)} apresChangement={recharger} />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <button
          type="button"
          onClick={() => setEdition("nouvelle")}
          className="flex h-[104px] items-center justify-center gap-2.5 rounded-[var(--r-card)] border-2 border-dashed border-[var(--v-border)] bg-transparent text-sm font-semibold text-[color:var(--v-text-2)] hover:bg-[var(--v-beige-2)]"
        >
          <Plus aria-hidden="true" className="size-[18px]" />
          Nouvelle fiche
        </button>
        <div className="flex flex-col justify-center gap-1 rounded-[var(--r-card)] bg-[var(--v-beige)] px-5 py-4 md:col-span-2">
          <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[.06em] text-[color:var(--v-text-3)]">
            <Box aria-hidden="true" className="size-4" />
            Module 3D · cahier suivant
          </span>
          <span className="text-sm">
            Une fiche pourra recevoir son modèle 3D (TRELLIS, Hunyuan3D) et son rig, sans toucher au socle : un connecteur et un module de plus.
          </span>
        </div>
      </div>
      {edition && (
        <FenetreFiche
          key={edition === "nouvelle" ? "nouvelle" : edition.id}
          fiche={edition === "nouvelle" ? null : edition}
          fermer={() => setEdition(null)}
          apresEnregistrement={() => {
            setEdition(null)
            recharger()
          }}
        />
      )}
    </div>
  )
}

function CarteFiche({
  fiche,
  onModifier,
  apresChangement,
}: {
  fiche: FicheBibliotheque
  onModifier: () => void
  apresChangement: () => void
}) {
  const type = typeDe(fiche)
  const [confirmation, setConfirmation] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [suppressionEnCours, setSuppressionEnCours] = useState(false)

  async function supprimer() {
    if (suppressionEnCours) return
    setErreur(null)
    setSuppressionEnCours(true)
    try {
      await executer(api.DELETE("/api/bibliotheque/{fiche_id}", { params: { path: { fiche_id: fiche.id } } }))
      apresChangement()
    } catch (e) {
      setErreur(messageErreur(e))
      setConfirmation(false)
    } finally {
      setSuppressionEnCours(false)
    }
  }

  return (
    <article className="flex flex-col gap-3 rounded-[var(--r-card)] bg-card p-4 text-card-foreground">
      <div className={cn("grid gap-2", type.roles.length > 1 && "grid-cols-2")}>
        {type.roles.map((role) => (
          <FigureReference key={role} fiche={fiche} role={role} teinte={type.teinte} apresChangement={apresChangement} surErreur={setErreur} />
        ))}
      </div>
      <div className="flex items-center justify-between gap-2">
        <h2 className="m-0 font-cojeev-display text-[21px] font-bold">{fiche.nom}</h2>
        <Badge variant={type.teinte}>{type.libelle}</Badge>
      </div>
      {fiche.description && <p className="m-0 text-[13px] leading-[1.45] text-[color:var(--v-text-2)]">{fiche.description}</p>}
      <span className="text-xs text-[color:var(--v-text-3)]">
        {fiche.projets.length > 0 ? `Utilisée dans : ${fiche.projets.join(" · ")}` : "Pas encore utilisée"}
      </span>
      {erreur && <Alerte>{erreur}</Alerte>}
      <div className="mt-auto flex flex-wrap gap-1.5">
        <Button size="sm" variant="ghost" disabled title={GENERATION_A_VENIR}>
          Générer · Qwen
        </Button>
        <Button size="sm" variant="ghost" disabled title={GENERATION_A_VENIR}>
          Générer · Codex
        </Button>
        <Button size="sm" variant="outline" onClick={onModifier}>
          Modifier
        </Button>
        {confirmation ? (
          <>
            <Button size="sm" variant="danger" onClick={() => void supprimer()} disabled={suppressionEnCours}>
              Confirmer la suppression
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmation(false)}>
              Annuler
            </Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirmation(true)}>
            Supprimer
          </Button>
        )}
      </div>
    </article>
  )
}

function FigureReference({
  fiche,
  role,
  teinte,
  apresChangement,
  surErreur,
}: {
  fiche: FicheBibliotheque
  role: RoleImageFiche
  teinte: Teinte
  apresChangement: () => void
  surErreur: (message: string | null) => void
}) {
  const image = fiche.images.find((i) => i.role === role) ?? null
  const [cheminEnEchec, setCheminEnEchec] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  const [envoi, setEnvoi] = useState(false)
  const idFichier = useId()
  const visible = image !== null && cheminEnEchec !== image.chemin

  async function importer(fichier: File) {
    setEnvoi(true)
    surErreur(null)
    try {
      await televerser(`/api/bibliotheque/${encodeURIComponent(fiche.id)}/images/${role}`, fichier)
      setCheminEnEchec(null)
      setVersion((v) => v + 1)
      apresChangement()
    } catch (e) {
      surErreur(messageErreur(e))
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <figure className={cn("relative m-0 flex h-[236px] flex-col items-center justify-center gap-2 overflow-hidden rounded-[14px]", FONDS[teinte])}>
      {visible ? (
        <img
          src={urlMedia(image.chemin, version)}
          alt={`${LIBELLES_ROLE[role]} — ${fiche.nom}`}
          onError={() => setCheminEnEchec(image.chemin)}
          className="size-full object-cover"
        />
      ) : (
        <>
          {ICONES_ROLE[role]}
          <figcaption className="text-xs">{LIBELLES_ROLE[role]}</figcaption>
        </>
      )}
      <label
        htmlFor={idFichier}
        className="absolute right-2 bottom-2 cursor-pointer rounded-full bg-card px-3 py-1 text-xs text-foreground shadow-[var(--shadow-float)]"
      >
        {envoi ? "Envoi…" : image ? "Remplacer" : "Importer"}
      </label>
      <input
        id={idFichier}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="sr-only"
        onChange={(evenement) => {
          const fichier = evenement.target.files?.[0]
          evenement.target.value = ""
          if (fichier) void importer(fichier)
        }}
      />
    </figure>
  )
}

function FenetreFiche({
  fiche,
  fermer,
  apresEnregistrement,
}: {
  fiche: FicheBibliotheque | null
  fermer: () => void
  apresEnregistrement: () => void
}) {
  const [type, setType] = useState<TypeFiche>(fiche?.type ?? "personnage")
  const [nom, setNom] = useState(fiche?.nom ?? "")
  const [description, setDescription] = useState(fiche?.description ?? "")
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)
  const titreId = useId()

  async function enregistrer(evenement: FormEvent) {
    evenement.preventDefault()
    if (enCours) return
    setEnCours(true)
    const corps = { type, nom: nom.trim(), description: description.trim() }
    try {
      if (fiche) {
        await exiger(api.PUT("/api/bibliotheque/{fiche_id}", { params: { path: { fiche_id: fiche.id } }, body: corps }))
      } else {
        await exiger(api.POST("/api/bibliotheque", { body: corps }))
      }
      apresEnregistrement()
    } catch (e) {
      setErreur(messageErreur(e))
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--v-scrim)] p-4"
      onKeyDown={(evenement) => {
        if (evenement.key === "Escape") fermer()
      }}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby={titreId}
        onSubmit={(evenement) => void enregistrer(evenement)}
        className="flex w-full max-w-lg flex-col gap-4 rounded-[var(--r-panel)] bg-card p-6 text-card-foreground shadow-[var(--shadow-float)]"
      >
        <h2 id={titreId} className="m-0 font-cojeev-display text-[21px] font-bold">
          {fiche ? "Modifier la fiche" : "Nouvelle fiche"}
        </h2>
        <Segments
          libelle="Type de fiche"
          options={TYPES.map((t) => ({ valeur: t.valeur, libelle: t.libelle }))}
          valeur={type}
          onChange={(v) => setType(v as TypeFiche)}
        />
        <ChampTexte libelle="Nom" valeur={nom} onChange={setNom} autoFocus required />
        <ZoneTexte libelle="Description" valeur={description} onChange={setDescription} lignes={3} />
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={fermer}>
            Annuler
          </Button>
          <Button type="submit" variant="accent" disabled={!nom.trim() || enCours}>
            Enregistrer
          </Button>
        </div>
      </form>
    </div>
  )
}
