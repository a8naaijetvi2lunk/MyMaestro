/** Aides autour d'openapi-fetch et de fetch : une erreur de l'API devient une exception lisible. */

type Reponse<T> = { data?: T; error?: unknown; response: Response }

export function messageApi(erreur: unknown, statut: number): string {
  if (erreur && typeof erreur === "object" && "detail" in erreur) {
    const detail = (erreur as { detail: unknown }).detail
    if (typeof detail === "string") return detail
    if (Array.isArray(detail)) {
      return detail
        .map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : JSON.stringify(e)))
        .join(" ; ")
    }
  }
  return `Erreur ${statut}`
}

export function messageErreur(erreur: unknown): string {
  return erreur instanceof Error ? erreur.message : String(erreur)
}

/** Données d'une réponse réussie, ou exception portant le message de l'API. */
export async function exiger<T>(requete: Promise<Reponse<T>>): Promise<T> {
  const { data, error, response } = await requete
  if (!response.ok || data === undefined) throw new Error(messageApi(error, response.status))
  return data
}

/** Pour les réponses sans corps (204) : seule la réussite compte. */
export async function executer(requete: Promise<{ error?: unknown; response: Response }>): Promise<void> {
  const { error, response } = await requete
  if (!response.ok) throw new Error(messageApi(error, response.status))
}

/** Envoie un fichier en corps brut (PUT) : l'API lit le flux, sans multipart. */
export async function televerser(url: string, fichier: File): Promise<unknown> {
  const response = await fetch(url, {
    method: "PUT",
    body: fichier,
    headers: { "Content-Type": fichier.type || "application/octet-stream" },
  })
  const corps: unknown = response.headers.get("content-type")?.includes("json") ? await response.json() : undefined
  if (!response.ok) throw new Error(messageApi(corps, response.status))
  return corps
}

/** Adresse d'un média servi par l'API ; `version` force le rechargement après un remplacement. */
export function urlMedia(chemin: string, version = 0): string {
  const adresse = `/api/medias/${chemin.split("/").map(encodeURIComponent).join("/")}`
  return version ? `${adresse}?v=${version}` : adresse
}
