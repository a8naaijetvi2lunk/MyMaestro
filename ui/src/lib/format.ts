/** Formate une durée en secondes au format « m:ss,d » (ex. 70,125 s → « 1:10,1 »). */
export function formatDuree(secondes: number): string {
  if (!Number.isFinite(secondes) || secondes < 0) return "—"
  const dixiemes = Math.round(secondes * 10)
  const minutes = Math.floor(dixiemes / 600)
  const reste = dixiemes - minutes * 600
  const s = Math.floor(reste / 10)
  const d = reste % 10
  return `${minutes}:${String(s).padStart(2, "0")},${d}`
}

/** Espace disque en Mo → « 9,5 Go » : 1 Go = 1 000 Mo, comme le README et le manifeste d'installation. */
export function formatEspace(mo: number): string {
  return mo >= 1000 ? `${(mo / 1000).toFixed(mo >= 10000 ? 0 : 1).replace(".", ",")} Go` : `${mo} Mo`
}

const LIBELLES_ROLE: Record<string, string> = {
  chante: "Chanté",
  coupe: "Coupe",
}

export function libelleRole(role: string): string {
  return LIBELLES_ROLE[role] ?? role
}

const LIBELLES_MOTEUR_VIDEO: Record<string, string> = {
  minimax_h3: "MiniMax H3",
  ltx2_22B_distilled_1_1_omninft: "LTX-2.3 + OmniNFT",
  ltx2_25_omninft: "LTX-2.5 + OmniNFT",
}

export function libelleMoteurVideo(moteur: string | null | undefined): string {
  if (!moteur) return "—"
  return LIBELLES_MOTEUR_VIDEO[moteur] ?? moteur
}

const LIBELLES_CONNECTEUR: Record<string, string> = {
  maestro: "Maestro",
  dlss5: "DLSS 5",
  bonsai: "Bonsai 2",
  claude: "Claude",
  codex: "Codex",
  export: "Export (ffmpeg)",
}

export function libelleConnecteur(nom: string): string {
  return LIBELLES_CONNECTEUR[nom] ?? nom
}

const LIBELLES_MODELE: Record<string, string> = {
  ...LIBELLES_MOTEUR_VIDEO,
  qwen_image_edit_2511_20B_fp8_lightning_8step: "Qwen Image Edit",
  codex_imagegen: "Codex imagegen",
  flashvsr2: "FlashVSR ×2",
  ffmpeg: "ffmpeg",
  mmaudio: "MMAudio",
  dlss5: "DLSS5",
  sonnet: "Claude sonnet",
  opus: "Claude opus",
  "claude-opus-5-5": "Opus 5.5",
  "bonsai2-27b-pq2": "Bonsai 2",
}

export function libelleModele(modele: string | null | undefined): string {
  if (!modele) return "—"
  return LIBELLES_MODELE[modele] ?? modele
}

const LIBELLES_PHASE: Record<string, string> = {
  creation: "Création",
  analyse: "Analyse",
  ecriture: "Écriture",
  prompts: "Prompts",
  images: "Images",
  video: "Vidéo",
  postprod: "Post-production",
  export: "Export",
}

export function libellePhase(phase: string): string {
  return LIBELLES_PHASE[phase] ?? phase
}

const LIBELLES_ETAT_PHASE: Record<string, string> = {
  a_faire: "À faire",
  en_cours: "En cours",
  a_valider: "À valider",
  termine: "Terminé",
  echec: "Échec",
}

export function libelleEtatPhase(etat: string): string {
  return LIBELLES_ETAT_PHASE[etat] ?? etat
}

/** Nombre décimal à la française (virgule), avec `decimales` chiffres après la virgule. */
export function formatDecimal(valeur: number, decimales = 1): string {
  return valeur.toFixed(decimales).replace(".", ",")
}
