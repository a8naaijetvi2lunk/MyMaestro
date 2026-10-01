from mymaestro.modules.director_musique.analyse_maestro import analyse_depuis_maestro, caler_paroles

BRUT = {
    "duration": 40.0,
    "bpm": 118.4,
    "beats": [{"time": 1.0, "strength": 0.9}, {"time": 0.5, "strength": 0.4}],
    "sections": [
        {"start": 0.0, "end": 10.0, "label": "intro", "energy": 0.2},
        {"start": 10.0, "end": 30.0, "label": "chorus", "energy": 0.9},
        {"start": 30.0, "end": 30.0, "label": "vide", "energy": 0.0},
        {"start": 30.0, "end": 40.0, "label": "coda", "energy": 0.3},
    ],
    "lyrics": [
        {"start": 11.0, "end": 14.0, "text": "Je marche seule quand la ville s'endort"},
        {"start": 14.5, "end": 20.0, "text": "Les néons comptent mes pas nuit blanche cœur battant"},
        {"start": 25.0, "end": 27.0, "text": "Et je garde la lumière"},
    ],
}


def test_sections_temps_forts_et_voix():
    analyse = analyse_depuis_maestro(BRUT, "")
    assert analyse.bpm == 118.4 and analyse.temps_forts == [0.5, 1.0] and not analyse.simule
    assert [(s.nom, s.debut_s, s.fin_s) for s in analyse.sections] == [("Intro", 0.0, 10.0), ("Refrain", 10.0, 30.0), ("Coda", 30.0, 40.0)]
    assert [(v.debut_s, v.fin_s) for v in analyse.voix] == [(11.0, 20.0), (25.0, 27.0)]
    assert [l.texte for l in analyse.lignes] == [s["text"] for s in BRUT["lyrics"]]  # sans paroles : la transcription


def test_paroles_fournies_calees_dans_l_ordre():
    paroles = "Je marche seule quand la ville s'endort\nLes néons comptent mes pas\n\nNuit blanche, cœur battant\nEt je garde la lumière"
    lignes = analyse_depuis_maestro(BRUT, paroles).lignes
    assert [l.texte for l in lignes] == ["Je marche seule quand la ville s'endort", "Les néons comptent mes pas", "Nuit blanche, cœur battant", "Et je garde la lumière"]
    assert (lignes[0].debut_s, lignes[0].fin_s) == (11.0, 14.0)
    # deux lignes chantées dans un même segment transcrit se le partagent
    assert (lignes[1].debut_s, lignes[1].fin_s, lignes[2].debut_s, lignes[2].fin_s) == (14.5, 17.25, 17.25, 20.0)
    assert (lignes[3].debut_s, lignes[3].fin_s) == (25.0, 27.0)


def test_sans_transcription_les_paroles_sont_reparties_sur_la_chanson():
    brut = {**BRUT, "lyrics": None}
    lignes = analyse_depuis_maestro(brut, "Un\nDeux").lignes
    assert [(l.texte, l.debut_s, l.fin_s) for l in lignes] == [("Un", 0.0, 20.0), ("Deux", 20.0, 40.0)]
    assert caler_paroles(["Un"], []) == []


def test_resultat_minimal_reste_valide():
    analyse = analyse_depuis_maestro({}, "")
    assert analyse.bpm == 120.0 and analyse.sections == [] and analyse.lignes == []


def test_couplet_absent_de_la_transcription_repartit_le_trou():
    segments = [(10.0, 14.0, "Le vent me parle à l'oreille"), (15.0, 18.0, "Les néons comptent mes pas"),
                (60.0, 63.0, "Et je garde la lumière"), (64.0, 67.0, "Jusqu'au bout de la nuit")]
    textes = ["Le vent me parle à l'oreille", "Les néons comptent mes pas", "Ligne trois", "Ligne quatre", "Ligne cinq", "Ligne six",
              "Et je garde la lumière", "Jusqu'au bout de la nuit"]
    lignes = caler_paroles(textes, segments)
    assert [(l.debut_s, l.fin_s) for l in lignes[:2]] == [(10.0, 14.0), (15.0, 18.0)]
    assert (lignes[2].debut_s, lignes[5].fin_s) == (18.0, 60.0)
    assert (lignes[6].debut_s, lignes[6].fin_s) == (60.0, 63.0)
    assert (lignes[7].debut_s, lignes[7].fin_s) == (64.0, 67.0)


def test_lignes_identiques_prennent_chacune_leur_segment():
    segments = [(10.0, 13.0, "Je garde la lumière"), (13.5, 16.5, "Je garde la lumière")]
    lignes = caler_paroles(["Je garde la lumière"] * 2, segments)
    assert [(l.debut_s, l.fin_s) for l in lignes] == [(10.0, 13.0), (13.5, 16.5)]


def test_derniere_ligne_absente_prend_la_fin_de_la_chanson():
    analyse = analyse_depuis_maestro(
        {"duration": 30.0, "lyrics": [{"start": 10.0, "end": 13.0, "text": "Je garde la lumière"}]},
        "Je garde la lumière\nJusqu'au bout de la nuit",
    )
    assert (analyse.lignes[1].debut_s, analyse.lignes[1].fin_s) == (13.0, 30.0)


def test_sans_duree_aucune_ligne_n_a_une_duree_nulle():
    lignes = caler_paroles(["Je garde la lumière", "Jusqu'au bout de la nuit"], [(10.0, 13.0, "Je garde la lumière")])
    assert all(ligne.fin_s > ligne.debut_s for ligne in lignes)
    assert (lignes[0].debut_s, lignes[1].fin_s) == (10.0, 13.0)


def test_balise_en_tete_avec_premier_segment_a_zero_reste_valide():
    analyse = analyse_depuis_maestro(
        {"duration": 20.0, "lyrics": [{"start": 0.0, "end": 4.0, "text": "Je marche seule quand la ville s'endort"},
                                      {"start": 4.0, "end": 8.0, "text": "Les néons comptent mes pas"}]},
        "[Couplet 1]\nJe marche seule quand la ville s'endort\nLes néons comptent mes pas",
    )
    assert len(analyse.lignes) == 3
    assert all(ligne.fin_s > ligne.debut_s >= 0 for ligne in analyse.lignes)


def test_residu_flottant_ne_donne_aucune_ligne_de_duree_nulle():
    lignes = caler_paroles(
        ["Les néons comptent mes pas", "Nuit blanche, cœur battant", "Et je garde la lumière", "[Refrain]", "Jusqu'au bout de la nuit"],
        [(7.56, 15.6, "Les néons comptent mes pas nuit blanche cœur battant et je garde la lumière"), (15.6, 19.71, "Jusqu'au bout de la nuit")],
        50.0,
    )
    assert all(ligne.fin_s > ligne.debut_s for ligne in lignes)
    assert (lignes[0].debut_s, lignes[4].debut_s, lignes[4].fin_s) == (7.56, 15.6, 19.71)


def test_refrain_chante_trois_fois_mais_ecrit_une_fois():
    textes = ["Je marche seule quand la ville s'endort", "Le vent me parle à l'oreille", "Jusqu'au bout de la nuit",
              "Je garde la lumière", "Les néons comptent mes pas", "Nuit blanche cœur battant"]
    refrain = [(textes[2], textes[3])] * 3
    segments = [(10.0, 14.0, textes[0]), (14.5, 18.0, textes[1])]
    for rang, (a, b) in enumerate(refrain):
        segments += [(20.0 + 10 * rang, 24.0 + 10 * rang, a), (24.5 + 10 * rang, 28.0 + 10 * rang, b)]
    segments += [(52.0, 58.0, textes[4]), (58.5, 65.5, textes[5])]
    lignes = caler_paroles(textes, segments, 70.0)
    # le refrain écrit prend sa première occurrence, d'un seul tenant ; le couplet 2 garde ses vrais horaires
    assert [(l.debut_s, l.fin_s) for l in lignes] == [(10.0, 14.0), (14.5, 18.0), (20.0, 24.0), (24.5, 28.0), (52.0, 58.0), (58.5, 65.5)]


def test_ad_libs_transcrits_entre_deux_lignes_sont_ignores():
    textes = ["Je marche seule quand la ville s'endort", "Le vent me parle à l'oreille", "Les néons comptent mes pas"]
    segments = [(10.0, 14.0, textes[0]), (14.5, 18.0, textes[1]), (18.5, 19.5, "Oh oh oh"), (20.0, 21.0, "Yeah"),
                (21.5, 22.5, "Hey hey"), (23.0, 27.0, textes[2])]
    ligne = caler_paroles(textes, segments)[2]
    assert (ligne.debut_s, ligne.fin_s) == (23.0, 27.0)


def test_refrain_final_non_transcrit_ne_reprend_pas_un_segment_deja_pris():
    textes = ["Je garde la lumière", "Jusqu'au bout de la nuit", "Je garde la lumière", "Jusqu'au bout de la nuit"]
    lignes = caler_paroles(textes, [(30.0, 33.5, textes[0]), (34.0, 37.5, textes[1])], 50.0)
    assert [(l.debut_s, l.fin_s) for l in lignes] == [(30.0, 33.5), (34.0, 37.5), (37.5, 43.75), (43.75, 50.0)]


def test_mots_outils_communs_ne_suffisent_pas_a_caler_une_ligne():
    textes = ["Le vent me parle à l'oreille", "Et je garde la lumière", "Jusqu'au bout de la nuit"]
    segments = [(10.0, 14.0, textes[0]), (15.0, 16.0, "je garde tout"), (30.0, 33.0, textes[2])]
    lignes = caler_paroles(textes, segments)
    assert (lignes[1].debut_s, lignes[1].fin_s) == (14.0, 30.0)  # non calée : le trou entre ses voisines


def test_ligne_coupee_en_deux_segments_les_couvre_tous_les_deux():
    textes = ["Je marche seule quand la ville s'endort", "Le vent me parle à l'oreille"]
    segments = [(10.0, 12.0, "Je marche seule"), (12.2, 14.0, "quand la ville s'endort"), (14.5, 18.0, textes[1])]
    assert [(l.debut_s, l.fin_s) for l in caler_paroles(textes, segments)] == [(10.0, 14.0), (14.5, 18.0)]


def test_balise_entre_deux_lignes_d_un_meme_segment_reste_valide():
    lignes = caler_paroles(["Les néons comptent mes pas", "[Pont]", "Nuit blanche, cœur battant"],
                           [(10.0, 16.0, "Les néons comptent mes pas nuit blanche cœur battant")], 20.0)
    assert len(lignes) == 3 and all(l.fin_s > l.debut_s for l in lignes)
    assert [l.debut_s for l in lignes] == sorted(l.debut_s for l in lignes)
