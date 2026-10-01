import { useId, useState, type FormEvent } from "react"

import { api } from "@/api/client"
import { useDonnees } from "@/api/hooks"
import { exiger, messageErreur, televerser } from "@/api/requetes"
import { Alerte } from "@/components/commun/mise-en-page"
import { ChampTexte, Liste, Segments, ZoneTexte } from "@/components/formulaire/controles"
import { Button } from "@/components/ui/button"
import { naviguer } from "@/lib/use-route"
import { cn } from "@/lib/utils"

async function chargerChoix() {
  const [recettes, fiches] = await Promise.all([
    exiger(api.GET("/api/recettes", { params: { query: { module: "director_musique" } } })),
    exiger(api.GET("/api/bibliotheque")),
  ])
  return { recettes, fiches }
}

export function FenetreNouveauProjet({ fermer }: { fermer: () => void }) {
  const { donnees } = useDonnees("nouveau-projet", chargerChoix)
  const [titre, setTitre] = useState("")
  const [format, setFormat] = useState<"16:9" | "9:16">("16:9")
  const [recetteChoisie, setRecetteChoisie] = useState<string | null>(null)
  const [casting, setCasting] = useState<string[]>([])
  const [paroles, setParoles] = useState("")
  const [chanson, setChanson] = useState<File | null>(null)
  const [projetCree, setProjetCree] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const titreId = useId()
  const idChanson = useId()
  const recette = recetteChoisie ?? donnees?.recettes[0]?.id ?? null

  function basculer(ficheId: string) {
    setCasting((actuel) => (actuel.includes(ficheId) ? actuel.filter((id) => id !== ficheId) : [...actuel, ficheId]))
  }

  async function creer(evenement: FormEvent) {
    evenement.preventDefault()
    setEnCours(true)
    setErreur(null)
    try {
      // Un nouvel essai après un échec d'envoi de la chanson ne recrée pas le projet.
      const id =
        projetCree ?? (await exiger(api.POST("/api/projets", { body: { titre: titre.trim(), format, recette_id: recette, paroles, casting } }))).id
      setProjetCree(id)
      if (chanson) await televerser(`/api/projets/${encodeURIComponent(id)}/chanson`, chanson)
      naviguer({ page: "projet", projetId: id, etape: "creation" })
    } catch (e) {
      setErreur(messageErreur(e))
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
        onSubmit={(evenement) => void creer(evenement)}
        className="flex max-h-[90dvh] w-full max-w-2xl flex-col gap-4 overflow-y-auto rounded-[var(--r-panel)] bg-card p-6 text-card-foreground shadow-[var(--shadow-float)]"
      >
        <h2 id={titreId} className="m-0 font-cojeev-display text-[21px] font-bold">
          Nouveau clip musical
        </h2>
        <fieldset disabled={projetCree !== null} className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
        <ChampTexte libelle="Titre" valeur={titre} onChange={setTitre} autoFocus required />
        <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] font-semibold">
          Format
          <Segments
            libelle="Format"
            options={[
              { valeur: "16:9", libelle: "16:9 · paysage" },
              { valeur: "9:16", libelle: "9:16 · vertical" },
            ]}
            valeur={format}
            onChange={(v) => setFormat(v === "9:16" ? "9:16" : "16:9")}
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] font-semibold">
          Recette
          <Liste
            libelle="Recette"
            options={(donnees?.recettes ?? []).map((r) => ({ valeur: r.id, libelle: r.nom }))}
            valeur={recette ?? ""}
            onChange={(v) => setRecetteChoisie(String(v))}
            className="w-[300px]"
          />
        </div>
        <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
          <legend className="mb-2 text-[13px] font-semibold">Casting (bibliothèque)</legend>
          <div className="flex flex-wrap gap-1.5">
            {(donnees?.fiches ?? []).map((fiche) => {
              const choisie = casting.includes(fiche.id)
              return (
                <button
                  key={fiche.id}
                  type="button"
                  aria-pressed={choisie}
                  onClick={() => basculer(fiche.id)}
                  className={cn(
                    "h-8 rounded-full px-3 text-xs",
                    choisie ? "bg-[var(--v-ink)] font-semibold text-[color:var(--v-on-ink)]" : "bg-[var(--v-beige)] text-foreground",
                  )}
                >
                  {fiche.nom}
                </button>
              )
            })}
          </div>
        </fieldset>
        <ZoneTexte libelle="Paroles (facultatives : elles font foi et seront calées sur la voix)" valeur={paroles} onChange={setParoles} lignes={6} />
        </fieldset>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={idChanson} className="text-[13px] font-semibold">
            Chanson
          </label>
          <input
            id={idChanson}
            type="file"
            accept="audio/*"
            onChange={(evenement) => setChanson(evenement.target.files?.[0] ?? null)}
            className="text-sm"
          />
        </div>
        {erreur && <Alerte>{erreur}</Alerte>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={fermer}>
            Annuler
          </Button>
          <Button type="submit" variant="accent" disabled={!titre.trim() || enCours}>
            {enCours ? "Envoi…" : projetCree ? "Envoyer la chanson" : "Créer le projet"}
          </Button>
        </div>
      </form>
    </div>
  )
}
