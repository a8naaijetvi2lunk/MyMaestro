import { Moon, Sun } from "lucide-react"
import { useState, type ReactNode } from "react"

import { api } from "@/api/client"
import { useDonnees, useEtatFile } from "@/api/hooks"
import { exiger } from "@/api/requetes"
import { libelleConnecteur } from "@/lib/format"
import { appliquerMode, lireMode, type Mode } from "@/lib/mode"
import { versHash, type Route } from "@/lib/route"
import { cn } from "@/lib/utils"

type PagePrincipale = "projets" | "bibliotheque" | "recettes" | "file" | "moteurs"

const ENTREES: ReadonlyArray<{ page: PagePrincipale; libelle: string; cible: Route }> = [
  { page: "projets", libelle: "Projets", cible: { page: "projets" } },
  { page: "bibliotheque", libelle: "Bibliothèque", cible: { page: "bibliotheque" } },
  { page: "recettes", libelle: "Recettes", cible: { page: "recettes", recetteId: null } },
  { page: "file", libelle: "File GPU", cible: { page: "file" } },
  { page: "moteurs", libelle: "Moteurs", cible: { page: "moteurs" } },
]

function pageActive(route: Route): PagePrincipale {
  return route.page === "projet" ? "projets" : route.page
}

/** Barre latérale sombre et zone de contenu (maquettes validées du 29/09). */
export function Coquille({ route, contexte, children }: { route: Route; contexte?: ReactNode; children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(lireMode)
  const { donnees: file } = useEtatFile()
  const { donnees: sante } = useDonnees("sante", () => exiger(api.GET("/api/sante")))
  const active = pageActive(route)
  const moteurGpu = file?.connecteurs.find((c) => c.nom === file.gpu_occupe_par) ?? null
  const cloudEnCours = file?.jobs.filter((j) => j.voie === "cloud" && j.statut === "en_cours").length ?? 0

  function basculerMode() {
    const suivant: Mode = mode === "clair" ? "sombre" : "clair"
    appliquerMode(suivant)
    setMode(suivant)
  }

  return (
    <div className="flex min-h-dvh bg-background text-foreground">
      <aside className="sticky top-0 flex h-dvh w-[232px] shrink-0 flex-col gap-7 overflow-y-auto bg-sidebar px-4 py-6 text-[color:var(--structure-text)]">
        <a href={versHash({ page: "projets" })} className="flex items-center gap-2.5 px-2 no-underline">
          <span className="flex size-[34px] items-center justify-center rounded-[12px_12px_12px_4px] bg-[var(--v-pink)] font-cojeev-display text-lg font-bold text-[color:var(--v-structure)]">
            M
          </span>
          <span className="font-cojeev-display text-xl font-bold text-sidebar-foreground">MyMaestro</span>
        </a>
        <nav aria-label="Navigation principale" className="flex flex-col gap-1">
          {ENTREES.map((entree) => {
            const courante = entree.page === active
            return (
              <a
                key={entree.page}
                href={versHash(entree.cible)}
                aria-current={courante ? "page" : undefined}
                className={cn(
                  "flex h-10 items-center gap-2.5 rounded-[12px] px-3 text-sm no-underline",
                  courante
                    ? "bg-[var(--structure-quiet)] font-semibold text-sidebar-foreground"
                    : "pl-7 text-[color:var(--structure-text)] hover:bg-[var(--structure-quiet)]",
                )}
              >
                {courante && <span aria-hidden="true" className="size-1.5 rounded-full bg-[var(--v-pink)]" />}
                {entree.libelle}
              </a>
            )
          })}
        </nav>
        {contexte}
        <div className="mt-auto flex flex-col gap-3">
          <div className="flex flex-col gap-1.5 rounded-2xl bg-[var(--structure-quiet)] p-3.5 text-xs text-[color:var(--sidebar-muted)]">
            <span className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn("size-2 rounded-full", moteurGpu ? "bg-[var(--v-yellow)]" : "bg-[var(--structure-line)]")}
              />
              {moteurGpu
                ? `GPU · ${libelleConnecteur(moteurGpu.nom)} ${moteurGpu.etat === "charge" ? "chargé" : "démarré"}`
                : "GPU · libre"}
            </span>
            <span className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn("size-2 rounded-full", cloudEnCours ? "bg-[var(--v-pink)]" : "bg-[var(--structure-line)]")}
              />
              {cloudEnCours ? `Cloud · ${cloudEnCours} en cours` : "Cloud · au repos"}
            </span>
            {file && !file.en_marche && <span>File en pause</span>}
            <span>{sante ? `API ${sante.version} · base v${sante.schema_db}` : "API injoignable"}</span>
          </div>
          <button
            type="button"
            onClick={basculerMode}
            className="flex h-9 items-center gap-2 rounded-[12px] px-3 text-sm text-[color:var(--structure-text)] hover:bg-[var(--structure-quiet)]"
          >
            {mode === "clair" ? <Moon aria-hidden="true" className="size-4" /> : <Sun aria-hidden="true" className="size-4" />}
            {mode === "clair" ? "Mode sombre" : "Mode clair"}
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-6 py-5">{children}</main>
    </div>
  )
}
