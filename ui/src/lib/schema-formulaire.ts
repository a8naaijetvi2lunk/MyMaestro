/** Formulaire généré depuis un schéma JSON pydantic (spec §4.1 : l'écran Recette n'est pas codé à la main). */

export type SchemaJson = Record<string, unknown>
export type ValeurOption = string | number
export type Option = { valeur: ValeurOption; libelle: string }

export type Controle =
  | { type: "case" }
  | { type: "segments"; options: Option[] }
  | { type: "liste"; options: Option[] }
  | { type: "curseur"; min: number; max: number; pas: number }
  | { type: "nombre"; min?: number; max?: number }
  | { type: "texte" }
  | { type: "fige"; libelles: Record<string, string> }

export type Champ = { chemin: string[]; titre: string; description?: string; controle: Controle }
export type Groupe = { chemin: string[]; titre: string; description?: string; champs: Champ[]; groupes: Groupe[] }

function texte(valeur: unknown): string | undefined {
  return typeof valeur === "string" ? valeur : undefined
}

function nombre(valeur: unknown): number | undefined {
  return typeof valeur === "number" ? valeur : undefined
}

function estObjet(valeur: unknown): valeur is Record<string, unknown> {
  return valeur !== null && typeof valeur === "object" && !Array.isArray(valeur)
}

/** Remplace un « $ref » par sa définition ; les clés posées à côté (titre, libellés…) l'emportent. */
export function resoudre(schema: SchemaJson, racine: SchemaJson): SchemaJson {
  const ref = texte(schema["$ref"])
  if (!ref) return schema
  const definitions = (racine["$defs"] ?? {}) as Record<string, SchemaJson>
  const definition = definitions[ref.replace("#/$defs/", "")]
  if (!definition) return schema
  const freres = Object.fromEntries(Object.entries(schema).filter(([cle]) => cle !== "$ref"))
  return { ...resoudre(definition, racine), ...freres }
}

export function controleDe(prop: SchemaJson): Controle {
  const libelles = (prop["x-libelles"] ?? {}) as Record<string, string>
  const indication = prop["x-controle"]
  const valeurs = Array.isArray(prop["enum"]) ? (prop["enum"] as ValeurOption[]) : null
  if (indication === "fige" || "const" in prop || valeurs?.length === 1) return { type: "fige", libelles }
  if (valeurs) {
    const options = valeurs.map((valeur) => ({ valeur, libelle: libelles[String(valeur)] ?? String(valeur) }))
    return indication === "segments" ? { type: "segments", options } : { type: "liste", options }
  }
  const min = nombre(prop["minimum"])
  const max = nombre(prop["maximum"])
  switch (prop["type"]) {
    case "boolean":
      return { type: "case" }
    case "integer":
      return { type: "nombre", min, max }
    case "number":
      return min !== undefined && max !== undefined ? { type: "curseur", min, max, pas: 0.1 } : { type: "nombre", min, max }
    default:
      return { type: "texte" }
  }
}

export function construireGroupe(schema: SchemaJson, racine: SchemaJson = schema, chemin: string[] = []): Groupe {
  const groupe: Groupe = {
    chemin,
    titre: texte(schema["title"]) ?? "",
    description: texte(schema["description"]),
    champs: [],
    groupes: [],
  }
  const proprietes = (schema["properties"] ?? {}) as Record<string, SchemaJson>
  for (const [cle, brut] of Object.entries(proprietes)) {
    const prop = resoudre(brut, racine)
    const sousChemin = [...chemin, cle]
    if (prop["type"] === "object" && prop["properties"]) {
      groupe.groupes.push(construireGroupe(prop, racine, sousChemin))
    } else {
      groupe.champs.push({
        chemin: sousChemin,
        titre: texte(prop["title"]) ?? cle,
        description: texte(prop["description"]),
        controle: controleDe(prop),
      })
    }
  }
  return groupe
}

export function lireValeur(valeurs: unknown, chemin: readonly string[]): unknown {
  let courant: unknown = valeurs
  for (const cle of chemin) {
    if (!estObjet(courant)) return undefined
    courant = courant[cle]
  }
  return courant
}

/** Copie de `valeurs` où la valeur au bout de `chemin` est remplacée (aucune mutation). */
export function ecrireValeur(valeurs: unknown, chemin: readonly string[], valeur: unknown): Record<string, unknown> {
  const base = estObjet(valeurs) ? valeurs : {}
  if (chemin.length === 0) return base
  const [tete, ...reste] = chemin
  return { ...base, [tete]: reste.length === 0 ? valeur : ecrireValeur(base[tete], reste, valeur) }
}

/** Valeurs complétées récursivement par les défauts (une recette ancienne peut manquer de réglages récents). */
export function fusionner(defauts: unknown, valeurs: unknown): unknown {
  if (!estObjet(defauts) || !estObjet(valeurs)) return valeurs === undefined ? defauts : valeurs
  const resultat: Record<string, unknown> = { ...defauts }
  for (const [cle, valeur] of Object.entries(valeurs)) resultat[cle] = fusionner(defauts[cle], valeur)
  return resultat
}
