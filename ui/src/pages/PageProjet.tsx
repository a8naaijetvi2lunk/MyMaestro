import { useProjetDirector } from "@/api/hooks"
import { Alerte, EnTetePage } from "@/components/commun/mise-en-page"
import { ETAPES, etapeCourante } from "@/lib/etapes"
import { formatDuree } from "@/lib/format"

import { BadgeEtatPhase } from "./director/commun"
import { EcranAnalyse } from "./director/EcranAnalyse"
import { EcranChanson } from "./director/EcranChanson"
import { EcranEcriture } from "./director/EcranEcriture"
import { EcranExport } from "./director/EcranExport"
import { EcranImages } from "./director/EcranImages"
import { EcranPrompts } from "./director/EcranPrompts"
import { EcranTimeline } from "./director/EcranTimeline"

export function PageProjet({ projetId, etape }: { projetId: string; etape: string | null }) {
  const { projet, director, erreur, recharger } = useProjetDirector(projetId)

  if (erreur && !projet) return <Alerte>{erreur}</Alerte>
  if (!projet) return <p className="text-[color:var(--v-text-3)]">Chargement…</p>

  const courante = etape && ETAPES.some((e) => e.id === etape) ? etape : etapeCourante(projet.etat_phases)
  const libelle = ETAPES.find((e) => e.id === courante)?.libelle ?? courante
  const proprietes = { projet, director, recharger }
  const duree = projet.duree_chanson_s ? ` · ${formatDuree(projet.duree_chanson_s)}` : ""

  return (
    <div className="flex flex-col gap-4">
      <EnTetePage
        titre={libelle}
        sousTitre={`${projet.titre}${duree} · ${projet.format} · ${projet.plans.length} plan${projet.plans.length > 1 ? "s" : ""}`}
        actions={<BadgeEtatPhase etat={projet.etat_phases[courante]} />}
      />
      {erreur && <Alerte>{erreur}</Alerte>}
      {courante === "creation" && <EcranChanson {...proprietes} />}
      {courante === "analyse" && <EcranAnalyse {...proprietes} />}
      {courante === "ecriture" && <EcranEcriture {...proprietes} />}
      {courante === "prompts" && <EcranPrompts {...proprietes} />}
      {courante === "images" && <EcranImages {...proprietes} />}
      {courante === "video" && <EcranTimeline {...proprietes} />}
      {courante === "export" && <EcranExport {...proprietes} />}
    </div>
  )
}
