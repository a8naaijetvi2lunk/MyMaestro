import { useState } from "react"

import { api, type ManifesteModule, type Recette, type ResumeProjet } from "@/api/client"
import { useDonnees } from "@/api/hooks"
import { exiger, messageErreur } from "@/api/requetes"
import { Alerte, EnTetePage } from "@/components/commun/mise-en-page"
import { ChampTexte } from "@/components/formulaire/controles"
import { FormulaireGenere } from "@/components/formulaire/FormulaireGenere"
import { Button } from "@/components/ui/button"
import { LIBELLES_COURTS_VIDEO } from "@/lib/etapes"
import { definitionsDuFormulaire, h3Interroge, TOUTES_DEFINITIONS_H3, type Definitions } from "@/lib/rendu"
import { formatDecimal } from "@/lib/format"
import { versHash } from "@/lib/route"
import { construireGroupe, fusionner, type SchemaJson } from "@/lib/schema-formulaire"
import { naviguer } from "@/lib/use-route"
import { cn } from "@/lib/utils"

const MODULE = "director_musique"

type Donnees = {
  manifeste: ManifesteModule
  defauts: Record<string, unknown>
  recettes: Recette[]
  projets: ResumeProjet[]
}

async function charger(): Promise<Donnees> {
  const [manifestes, defauts, recettes, projets] = await Promise.all([
    exiger(api.GET("/api/modules")),
    exiger(api.GET("/api/modules/{module_id}/defauts", { params: { path: { module_id: MODULE } } })),
    exiger(api.GET("/api/recettes", { params: { query: { module: MODULE } } })),
    exiger(api.GET("/api/projets")),
  ])
  const manifeste = manifestes.find((m) => m.id === MODULE)
  if (!manifeste) throw new Error("Module Director musique introuvable")
  return { manifeste, defauts, recettes, projets }
}

export function PageRecettes({ recetteId }: { recetteId: string | null }) {
  const { donnees, erreur, recharger } = useDonnees("recettes", charger)
  const [erreurCreation, setErreurCreation] = useState<string | null>(null)
  const [creation, setCreation] = useState(false)

  if (erreur && !donnees) return <Alerte>{erreur}</Alerte>
  if (!donnees) return <p className="text-[color:var(--v-text-3)]">Chargement…</p>

  const recette = donnees.recettes.find((r) => r.id === recetteId) ?? donnees.recettes[0] ?? null

  async function nouvelle(defauts: Record<string, unknown>) {
    if (creation) return
    setCreation(true)
    try {
      const creee = await exiger(api.POST("/api/recettes", { body: { module: MODULE, nom: "Nouvelle recette", valeurs: defauts } }))
      recharger()
      naviguer({ page: "recettes", recetteId: creee.id })
    } catch (e) {
      setErreurCreation(messageErreur(e))
    } finally {
      setCreation(false)
    }
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
      <nav aria-label="Mes recettes" className="flex flex-col gap-2">
        <span className="px-3 text-[11px] uppercase tracking-[.08em] text-[color:var(--v-text-3)]">Mes recettes</span>
        <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
          {donnees.recettes.map((r) => {
            const utilisee = donnees.projets.filter((p) => p.recette_id === r.id).map((p) => p.titre)
            return (
              <li key={r.id}>
                <a
                  href={versHash({ page: "recettes", recetteId: r.id })}
                  aria-current={r.id === recette?.id ? "page" : undefined}
                  className={cn(
                    "flex flex-col rounded-[10px] px-3 py-2 text-[13px] no-underline",
                    r.id === recette?.id ? "bg-card font-semibold text-foreground" : "text-[color:var(--v-text-2)] hover:bg-[var(--v-beige)]",
                  )}
                >
                  {r.nom}
                  {utilisee.length > 0 && (
                    <span className="text-[11px] font-normal text-[color:var(--v-text-3)]">Utilisée par : {utilisee.join(" · ")}</span>
                  )}
                </a>
              </li>
            )
          })}
        </ul>
        <Button variant="outline" size="sm" disabled={creation} onClick={() => void nouvelle(donnees.defauts)}>
          Nouvelle recette
        </Button>
        {erreurCreation && <Alerte>{erreurCreation}</Alerte>}
      </nav>
      {recette ? (
        <EditeurRecette
          key={recette.id}
          recette={recette}
          manifeste={donnees.manifeste}
          defauts={donnees.defauts}
          apresEnregistrement={recharger}
        />
      ) : (
        <p className="m-0">Aucune recette pour ce module : crée la première.</p>
      )}
    </div>
  )
}

function EditeurRecette({
  recette,
  manifeste,
  defauts,
  apresEnregistrement,
}: {
  recette: Recette
  manifeste: ManifesteModule
  defauts: Record<string, unknown>
  apresEnregistrement: () => void
}) {
  const [nom, setNom] = useState(recette.nom)
  const [valeurs, setValeurs] = useState<Record<string, unknown>>(
    () => fusionner(defauts, recette.valeurs) as Record<string, unknown>,
  )
  const [statut, setStatut] = useState<{ ok: boolean; message: string } | null>(null)
  const [enCours, setEnCours] = useState(false)
  const schema: SchemaJson = manifeste.schema_reglages
  const groupe = construireGroupe(schema)
  const format = valeurs.format === "9:16" ? "9:16" : "16:9"

  async function enregistrer() {
    setEnCours(true)
    try {
      await exiger(
        api.PUT("/api/recettes/{recette_id}", {
          params: { path: { recette_id: recette.id } },
          body: { module: recette.module, nom: nom.trim() || recette.nom, valeurs },
        }),
      )
      setStatut({ ok: true, message: "Recette enregistrée." })
      apresEnregistrement()
    } catch (e) {
      setStatut({ ok: false, message: messageErreur(e) })
    } finally {
      setEnCours(false)
    }
  }

  async function dupliquer() {
    setEnCours(true)
    try {
      const copie = await exiger(
        api.POST("/api/recettes", { body: { module: recette.module, nom: `${nom.trim() || recette.nom} (copie)`, valeurs } }),
      )
      apresEnregistrement()
      naviguer({ page: "recettes", recetteId: copie.id })
    } catch (e) {
      setStatut({ ok: false, message: messageErreur(e) })
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <EnTetePage
        titre={`Recette · ${nom || recette.nom}`}
        sousTitre="Programmée avant le lancement, réutilisable d'un projet à l'autre. Écran généré depuis les schémas de réglages du module."
        actions={
          <>
            <Button variant="outline" onClick={() => void dupliquer()} disabled={enCours}>
              Dupliquer
            </Button>
            <Button variant="accent" onClick={() => void enregistrer()} disabled={enCours}>
              Enregistrer la recette
            </Button>
          </>
        }
      />
      <ChampTexte libelle="Nom de la recette" valeur={nom} onChange={setNom} className="max-w-md" />
      {statut &&
        (statut.ok ? (
          <p role="status" className="m-0 text-sm text-[color:var(--v-olive-ink)]">
            {statut.message}
          </p>
        ) : (
          <Alerte>{statut.message}</Alerte>
        ))}
      <FormulaireGenere
        groupe={groupe}
        valeurs={valeurs}
        onChange={setValeurs}
        titreGeneral={typeof schema["x-titre-general"] === "string" ? schema["x-titre-general"] : "Général"}
        complementGeneral={<InfosDeRendu format={format} definitions={definitionsDuFormulaire(valeurs)} />}
      />
    </div>
  )
}

function InfosDeRendu({ format, definitions }: { format: "16:9" | "9:16"; definitions: Definitions }) {
  const { h3, ltx23, ltx25 } = definitions
  // Définitions H3 de la carte : lues avec le défaut du serveur, car un choix non permis est refusé (422) par /api/rendu.
  const { donnees: parDefaut } = useDonnees(`rendu-permises:${format}`, () =>
    exiger(api.GET("/api/rendu", { params: { query: { format } } })),
  )
  const permisesH3 = parDefaut?.moteurs.find((m) => m.moteur === "minimax_h3")?.definitions_permises
  const h3Demande = h3Interroge(h3, permisesH3)
  const h3NonPermis = permisesH3 !== undefined && h3Demande === undefined
  // Permises encore inconnues et définition à risque (720p, 1080p) : on attend, aucune requête refusée n'est envoyée.
  const attente = permisesH3 === undefined && h3Demande === undefined
  const { donnees: infos } = useDonnees(`rendu:${format}:${attente ? "attente" : (h3Demande ?? "defaut")}:${ltx23}:${ltx25}`, () =>
    attente
      ? new Promise<never>(() => {})
      : exiger(api.GET("/api/rendu", { params: { query: { format, h3: h3Demande, ltx23, ltx25 } } })),
  )
  // La clé change à chaque choix de définition : on garde la dernière réponse affichée pendant le rechargement.
  const [derniere, setDerniere] = useState(infos)
  if (infos && infos !== derniere) setDerniere(infos)
  const affichees = infos ?? derniere
  if (!affichees) return null
  const lignes = [
    ...affichees.moteurs.map((m) => {
      const nom = LIBELLES_COURTS_VIDEO[m.moteur] ?? m.moteur
      if (m.moteur === "minimax_h3" && h3NonPermis) return [nom, `${h3} · non disponible sur cette carte`]
      const taille = `${m.largeur}×${m.hauteur} (${m.definition})`
      const valeur =
        m.moteur === "minimax_h3"
          ? `${taille} · plans ≤ ${formatDecimal(m.duree_max_s)} s (${m.images_max} images)`
          : taille
      return [nom, m.saute_flashvsr ? `${valeur} · FlashVSR sauté (déjà en 1080p)` : valeur]
    }),
    ...(permisesH3
      ? [
          [
            "Définitions H3",
            TOUTES_DEFINITIONS_H3.map((d) => (permisesH3.includes(d) ? d : `${d} (non disponible sur cette carte)`)).join(" · "),
          ],
        ]
      : []),
    ["Fps maître",`${affichees.fps_maitre} · LTX-2.3 ramené de 25`],
    ["Sortie", `${affichees.largeur_sortie}×${affichees.hauteur_sortie}`],
  ]
  return (
    <dl className="m-0 grid grid-cols-2 gap-2.5 text-[13px]">
      {lignes.map(([terme, valeur]) => (
        <div key={terme} className="rounded-[12px] bg-[var(--v-beige-2)] p-3">
          <dt className="text-[color:var(--v-text-3)]">{terme}</dt>
          <dd className="m-0 mt-1 font-semibold">{valeur}</dd>
        </div>
      ))}
    </dl>
  )
}
