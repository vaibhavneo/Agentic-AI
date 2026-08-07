"""
Hardcoded Vedic Astrology Knowledge Base
==========================================
Encoded from the 60 books in the library — classical Parasara / Jaimini principles.
This is the "procedural memory" that grounds the AI in authentic Vedic tradition.

Sources: BPHS, Narasimha Rao, K.N. Rao, Deepanshu Giri, Arjun Pai, Visti Larsen
"""

# ══════════════════════════════════════════════════════════════════════════
# HOUSE MEANINGS (Bhavas)
# ══════════════════════════════════════════════════════════════════════════

HOUSE_MEANINGS = {
    1:  {
        "name": "Tanu Bhava (Lagna)",
        "primary": "Self, personality, physical body, vitality, appearance, overall life path",
        "career": "Leadership, entrepreneurship, independent work",
        "health": "Head, brain, constitution, immunity",
        "keywords": ["identity", "self", "health", "beginnings", "personality"],
    },
    2:  {
        "name": "Dhana Bhava",
        "primary": "Wealth, family, speech, food, face, accumulated resources, early education",
        "career": "Finance, banking, teaching, speaking",
        "wealth": "Accumulated wealth, savings, family wealth",
        "keywords": ["money", "family", "speech", "values", "resources"],
    },
    3:  {
        "name": "Sahaja Bhava",
        "primary": "Siblings, courage, communication, short travels, skills, efforts",
        "career": "Writing, media, sales, communication, arts",
        "keywords": ["courage", "siblings", "communication", "short trips"],
    },
    4:  {
        "name": "Sukha Bhava",
        "primary": "Mother, home, property, comfort, vehicles, inner happiness, education",
        "career": "Real estate, agriculture, teaching, interior design",
        "keywords": ["home", "mother", "property", "comfort", "roots"],
    },
    5:  {
        "name": "Putra Bhava",
        "primary": "Children, intelligence, creativity, romance, speculation, past life merit (purva punya)",
        "career": "Education, creative arts, speculation, entertainment, politics",
        "soul": "Purva punya — karmic gifts from past lives; creative expression",
        "keywords": ["children", "creativity", "intelligence", "romance", "speculation"],
    },
    6:  {
        "name": "Ripu/Roga Bhava",
        "primary": "Enemies, debts, diseases, obstacles, service, daily work",
        "career": "Medicine, law, military, service industries",
        "keywords": ["obstacles", "enemies", "service", "health challenges", "debts"],
    },
    7:  {
        "name": "Kalatra Bhava",
        "primary": "Marriage partner, partnerships, business partners, public dealings",
        "career": "Partnerships, consulting, diplomacy, business",
        "marriage": "Spouse characteristics, marriage timing, relationship quality",
        "keywords": ["marriage", "partner", "relationships", "public", "business partners"],
    },
    8:  {
        "name": "Ayus/Randhra Bhava",
        "primary": "Longevity, transformation, hidden knowledge, occult, inheritance, sudden changes",
        "career": "Research, occult, mining, insurance, psychology",
        "soul": "Transformation, hidden depths, past life karma surfacing",
        "keywords": ["transformation", "hidden", "longevity", "inheritance", "occult"],
    },
    9:  {
        "name": "Dharma Bhava",
        "primary": "Father, guru, higher education, philosophy, religion, fortune, long travels",
        "career": "Teaching, philosophy, law, religion, publishing, foreign work",
        "soul": "Dharma — life purpose, higher wisdom, spiritual orientation",
        "keywords": ["dharma", "father", "philosophy", "fortune", "spirituality", "wisdom"],
    },
    10: {
        "name": "Karma Bhava",
        "primary": "Career, profession, status, authority, government, public reputation",
        "career": "The primary career house — profession, achievements, public role",
        "keywords": ["career", "profession", "status", "authority", "public life"],
    },
    11: {
        "name": "Labha Bhava",
        "primary": "Income, gains, friends, elder siblings, desires fulfilled, social networks",
        "career": "Networking, social enterprise, gains from profession",
        "wealth": "Cash flow, income streams, financial gains",
        "keywords": ["gains", "income", "friends", "desires", "networks"],
    },
    12: {
        "name": "Vyaya Bhava",
        "primary": "Losses, foreign lands, spirituality, liberation (moksha), expenses, bed pleasures",
        "career": "Foreign work, hospitals, ashrams, behind-scenes roles, spiritual work",
        "soul": "Moksha — spiritual liberation, dissolution of ego, final journey",
        "keywords": ["loss", "foreign", "spirituality", "moksha", "isolation", "hospital"],
    },
}


# ══════════════════════════════════════════════════════════════════════════
# PLANET SIGNIFICATIONS (Karakas)
# ══════════════════════════════════════════════════════════════════════════

PLANET_KARAKAS = {
    "Sun": {
        "soul": "Atma (soul) — the core self, ego, individuality",
        "body": "Heart, eyes, bones, vitality",
        "career": "Government, authority, politics, administration, medicine (surgery), father's profession",
        "relationships": "Father, authority figures, bosses",
        "soul_purpose": "Leadership, authority, dharma — shining one's light authentically",
        "themes": ["ego", "father", "authority", "soul", "leadership", "vitality", "dharma"],
    },
    "Moon": {
        "soul": "Manas (mind) — emotions, subconscious, receptivity",
        "body": "Mind, lungs, fluids, breasts",
        "career": "Nursing, hospitality, food business, public work, maritime",
        "relationships": "Mother, public, women, masses",
        "soul_purpose": "Emotional intelligence, nurturing, connecting with collective",
        "themes": ["mother", "mind", "emotions", "public", "fluctuation", "nurturing"],
    },
    "Mars": {
        "soul": "Energy, willpower, aggression, courage",
        "body": "Blood, muscles, marrow, accidents",
        "career": "Military, police, engineering, surgery, sports, real estate",
        "relationships": "Siblings, husband (in female chart), competitors",
        "soul_purpose": "Courage, action, protecting what matters",
        "themes": ["courage", "action", "energy", "warrior", "land", "siblings", "ambition"],
    },
    "Mercury": {
        "soul": "Intelligence, analytical mind, communication, adaptability",
        "body": "Nervous system, skin, lungs",
        "career": "Writing, accounting, IT, trading, teaching, journalism, consulting",
        "relationships": "Uncles, friends, young people",
        "soul_purpose": "Communication, analysis, synthesis of knowledge",
        "themes": ["intelligence", "communication", "trade", "analysis", "youth", "writing"],
    },
    "Jupiter": {
        "soul": "Wisdom, expansion, grace, dharma, higher knowledge",
        "body": "Liver, hips, thighs, fat",
        "career": "Teaching, law, finance, religion, consulting, corporate leadership",
        "relationships": "Husband (in female chart), children, guru, elders",
        "soul_purpose": "Wisdom, expansion of consciousness, dharma teacher",
        "themes": ["wisdom", "expansion", "guru", "children", "dharma", "law", "optimism"],
    },
    "Venus": {
        "soul": "Beauty, love, harmony, pleasure, creativity, refinement",
        "body": "Reproductive system, kidneys, face",
        "career": "Arts, entertainment, luxury goods, fashion, beauty, hospitality, finance",
        "relationships": "Wife (in male chart), romantic partners, women",
        "soul_purpose": "Love, beauty, harmony — creating joy and connection",
        "themes": ["love", "beauty", "arts", "luxury", "creativity", "partnership", "pleasure"],
    },
    "Saturn": {
        "soul": "Discipline, karma, restriction, structure, hard work, time",
        "body": "Bones, teeth, knees, chronic conditions",
        "career": "Law, politics, mining, construction, engineering, administration",
        "relationships": "Servants, laborers, elderly, disciplinarians",
        "soul_purpose": "Master builder — learning through discipline, patience, responsibility",
        "themes": ["karma", "discipline", "restriction", "patience", "structure", "work", "delay"],
    },
    "Rahu": {
        "soul": "Obsession, foreign influences, materialism, ambition, illusion (Maya)",
        "body": "Neurological disorders, skin issues, unexplained illness",
        "career": "Technology, foreign work, research, unconventional fields, media",
        "relationships": "Foreign connections, unusual partnerships",
        "soul_purpose": "Breaking from past-life patterns, embracing new experiences (Rahu house/sign = current life mission)",
        "themes": ["obsession", "foreign", "illusion", "ambition", "technology", "unconventional"],
    },
    "Ketu": {
        "soul": "Spirituality, liberation, past-life knowledge, detachment, moksha",
        "body": "Mysterious illness, psychic sensitivity",
        "career": "Spirituality, research, occult, healing, service",
        "relationships": "Past-life connections, spiritual teachers",
        "soul_purpose": "Ketu sign/house = past-life mastery and area of natural skill (but also over-done — need balance)",
        "themes": ["liberation", "spirituality", "past lives", "detachment", "moksha", "hidden knowledge"],
    },
}


# ══════════════════════════════════════════════════════════════════════════
# SIGN CHARACTERISTICS
# ══════════════════════════════════════════════════════════════════════════

SIGN_CHARACTERISTICS = {
    "Aries":       {"element": "Fire",  "quality": "Cardinal", "ruler": "Mars",    "theme": "Pioneer, leader, initiator, independent, impulsive"},
    "Taurus":      {"element": "Earth", "quality": "Fixed",    "ruler": "Venus",   "theme": "Builder, sensual, stable, artistic, patient, stubborn"},
    "Gemini":      {"element": "Air",   "quality": "Mutable",  "ruler": "Mercury", "theme": "Communicator, curious, dual nature, versatile, witty"},
    "Cancer":      {"element": "Water", "quality": "Cardinal", "ruler": "Moon",    "theme": "Nurturer, emotional, protective, intuitive, home-lover"},
    "Leo":         {"element": "Fire",  "quality": "Fixed",    "ruler": "Sun",     "theme": "Royal, creative, generous, proud, leadership, performer"},
    "Virgo":       {"element": "Earth", "quality": "Mutable",  "ruler": "Mercury", "theme": "Analytical, service-oriented, perfectionist, healing, practical"},
    "Libra":       {"element": "Air",   "quality": "Cardinal", "ruler": "Venus",   "theme": "Diplomat, harmony-seeker, just, artistic, partnership-oriented"},
    "Scorpio":     {"element": "Water", "quality": "Fixed",    "ruler": "Mars",    "theme": "Intense, transformative, secretive, psychic, willful, investigator"},
    "Sagittarius": {"element": "Fire",  "quality": "Mutable",  "ruler": "Jupiter", "theme": "Philosopher, adventurer, truth-seeker, optimistic, wanderer"},
    "Capricorn":   {"element": "Earth", "quality": "Cardinal", "ruler": "Saturn",  "theme": "Achiever, disciplined, ambitious, pragmatic, authoritative"},
    "Aquarius":    {"element": "Air",   "quality": "Fixed",    "ruler": "Saturn",  "theme": "Humanitarian, reformer, unconventional, visionary, community"},
    "Pisces":      {"element": "Water", "quality": "Mutable",  "ruler": "Jupiter", "theme": "Mystic, compassionate, creative, spiritual, boundary-less, dreamer"},
}


# ══════════════════════════════════════════════════════════════════════════
# KEY YOGAS (Planetary Combinations)
# ══════════════════════════════════════════════════════════════════════════

IMPORTANT_YOGAS = {
    "Raj Yoga": "When lords of Kendra (1,4,7,10) and Trikona (1,5,9) houses conjoin or exchange — gives authority, status, success",
    "Dhana Yoga": "Lords of 2nd and 11th house connected to each other or to benefics — great wealth accumulation",
    "Viparita Raja Yoga": "Lords of 6th, 8th, or 12th in each other's houses — sudden rise after adversity",
    "Gajakesari Yoga": "Jupiter in Kendra from Moon — wisdom, fame, greatness",
    "Budha-Aditya Yoga": "Sun and Mercury conjunct — intelligence, government work, recognition",
    "Chandra-Mangal Yoga": "Moon and Mars conjunct — financial drive, emotional intensity",
    "Hamsa Yoga": "Jupiter in its own sign or exaltation in Kendra — great wisdom, spiritual grace",
    "Malavya Yoga": "Venus in own sign or exaltation in Kendra — beauty, wealth, artistic success",
    "Ruchaka Yoga": "Mars in own sign or exaltation in Kendra — courage, leadership, martial success",
    "Sasha Yoga": "Saturn in own sign or exaltation in Kendra — discipline, political power, longevity",
    "Kemadruma Yoga": "No planets on either side of Moon — periods of isolation, emotional difficulty",
    "Parivartana Yoga": "Two planets in each other's signs (exchange) — strong mutual enhancement",
    "Kaal Sarp Yoga": "All planets between Rahu and Ketu — karmic intensity, spiritual life, delays then sudden rise",
    "Daridra Yoga": "Lords of 2nd or 11th in 6th, 8th, 12th — financial struggle (check for cancellation)",
    "Neecha Bhanga Raja Yoga": "Debilitated planet gets cancellation via specific planetary configurations — turns weakness to strength",
}


# ══════════════════════════════════════════════════════════════════════════
# DIVISIONAL CHART MEANINGS
# ══════════════════════════════════════════════════════════════════════════

DIVISIONAL_MEANINGS = {
    "D1": "Rasi (Natal Chart) — Overall life blueprint, physical world, personality, general trends",
    "D2": "Hora — Financial potential, wealth orientation (Sun hora = paternal wealth path; Moon hora = maternal/emotional wealth)",
    "D3": "Drekkana — Siblings, courage, initiative, short-distance travel, skills",
    "D4": "Chaturthamsa — Fortune, property, physical luxuries and pleasures, general destiny",
    "D7": "Saptamsa — Children, creativity, procreation, parenting capacity",
    "D9": """Navamsa — THE most important divisional chart after D-1.
    Reveals: soul's dharmic path, spouse characteristics, relationship karma,
    inner spiritual nature, and the maturation of D-1 promises.
    A planet strong in both D-1 and D-9 is called 'Vargottama' — extremely powerful.
    A planet debilitated in D-1 but exalted in D-9 loses weakness.
    Navamsa Lagna reveals the soul's true nature and spiritual path.""",
    "D10": """Dasamsa — Career, profession, livelihood, public status, social contribution.
    The 10th house lord in D-10, the Amatyakaraka in D-10, and the D-10 Lagna lord
    together reveal the most suitable profession and career trajectory.""",
    "D12": "Dwadasamsa — Parents, ancestry, karmic inheritance from the parental line",
    "D16": "Shodasamsa (Kalamsa) — Vehicles, comforts, pleasures or troubles from material possessions",
    "D20": "Vimsamsa — Spirituality, worship, religious inclination, initiation on a spiritual path",
    "D24": "Chaturvimsamsa (Siddhamsa) — Education, learning, knowledge acquisition, academic achievement",
    "D27": "Saptavimsamsa (Bhamsa/Nakshatramsa) — General strengths and weaknesses, resilience",
    "D30": "Trimsamsa — Evil effects, misfortunes, character weaknesses; the varga of difficulties",
    "D40": "Khavedamsa — Auspicious and inauspicious general effects, maternal-line influences",
    "D45": "Akshavedamsa — General character and conduct, paternal-line influences",
    "D60": """Shashtiamsa — Overall past-life karma and general life results.
    Classically considered to carry MORE weight than the birth chart (D-1) itself
    for fine-grained prediction — the final, most granular divisional chart.""",
}


# ══════════════════════════════════════════════════════════════════════════
# PREDICTION FRAMEWORKS
# ══════════════════════════════════════════════════════════════════════════

CAREER_ANALYSIS_FRAMEWORK = """
CAREER ANALYSIS (Multi-Chart Approach — K.N. Rao methodology):
1. D-1 10th house + its lord + planets in 10th → primary career themes
2. D-1 Amatyakaraka (planet with 2nd highest degrees) → career significator
3. D-10 Lagna + 10th house → career in divisional confirmation
4. D-9 10th house → dharmic alignment of career choice
5. Vimshottari Dasha lord at key career timing periods
6. D-1 2nd + 11th lords → financial dimension of career
7. Natural karakas: Saturn (career/discipline), Sun (authority), Mercury (skills), Jupiter (wisdom professions)
8. Use the "Computed Chart Strength" section if provided — a planet strong across multiple
   career-authoritative vargas (D-1, D-10, D-9) should be emphasized over one strong only in D-1
"""

WEALTH_ANALYSIS_FRAMEWORK = """
WEALTH ANALYSIS:
1. D-1 2nd house lord + planets in 2nd → accumulated wealth
2. D-1 11th house lord + planets in 11th → income and gains
3. D-2 (Hora) Lagna → wealth orientation (Sun vs Moon hora)
4. D-1 Jupiter placement → abundance and expansion
5. Dhana Yogas (2nd-11th lord connections)
6. Venus (liquid wealth), Jupiter (overall prosperity)
7. Dasha periods triggering 2nd and 11th house lords
8. Use the "Computed Chart Strength" section if provided — weigh Vimshopaka Bala across
   D-1 and D-2 (Hora) over a single-chart placement alone
"""

MARRIAGE_ANALYSIS_FRAMEWORK = """
MARRIAGE AND RELATIONSHIP ANALYSIS:
1. D-1 7th house + lord → marriage timing and partner qualities
2. Venus (in male chart) + Jupiter (in female chart) → romantic indicators
3. D-9 (Navamsa) — THE marriage chart:
   - D-9 7th house lord → spouse characteristics
   - D-9 Lagna → marriage's inner quality and soul purpose
   - Navamsa Lagna Lord → life partner's core nature
4. Upapada Lagna (UL) in D-1 → marriage manifestation and spouse karma
5. Mars-Venus connection → passion and attraction
6. Saturn-7th lord aspect → delays, karmic marriage lessons
7. Timing: Dasha of 7th lord, Venus dasha, or trigger of 7th house
8. Use the "Computed Chart Strength" section if provided — a Vargottama or high-Vimshopaka
   Venus/Jupiter (D-1 + D-9 + D-7) carries more weight than a single-chart placement
"""

SOUL_PURPOSE_FRAMEWORK = """
SOUL PURPOSE AND LIFE LESSONS:
1. RAHU (North Node) sign/house → soul's current life mission — what must be embraced and developed
2. KETU (South Node) sign/house → past-life mastery — natural talents but also area of over-reliance
3. D-9 Lagna → soul's dharmic orientation in this life
4. D-1 5th house + lord → purva punya (past life merit and creative gifts)
5. D-1 9th house + lord → dharma — higher purpose and philosophical orientation
6. D-1 12th house → moksha path — spiritual dissolution, what must be surrendered
7. Atmakaraka (planet with highest degrees in D-1) → the soul's primary lesson and king of the chart
8. D-9 Atmakaraka sign → karakamsa — reveals soul's deepest purpose
9. Planets in 12th from Atmakaraka in D-9 (Ishtadevata) → personal deity and spiritual support
10. Use the "Computed Chart Strength" section if provided — Rahu/Ketu strength across
    D-1, D-20 (spirituality), and D-24 (learning) grounds this analysis beyond D-1 alone
"""

LIFE_LESSONS_FRAMEWORK = """
LIFE LESSONS ANALYSIS:
1. Saturn house/sign → where discipline and patience are learned; karmic debts
2. 6th house → obstacles and service — challenges that teach resilience
3. 8th house → transformation — what must be surrendered for growth
4. Retrograde planets → inner mastery — souls that have over-relied on these energies
5. Debilitated planets → areas needing conscious development (check for Neecha Bhanga)
6. D-1 12th house → where ego must dissolve for spiritual growth
7. Rahu-Ketu axis → the central karmic polarity of this lifetime
8. Use the "Computed Chart Strength" section if provided — Saturn's Vimshopaka Bala across
   D-1 and D-30 (Trimsamsa, the misfortune/character varga) sharpens this analysis
"""

# Nakshatra themes for soul analysis (from Deepanshu Giri's book)
NAKSHATRA_THEMES = {
    "Ashwini":         "Healing, speed, new beginnings — Ketu energy — healer archetype",
    "Bharani":         "Discipline through extremes, creativity, holding life/death — Venus intensity",
    "Krittika":        "Sharp discrimination, purification, passion — Sun's knife cuts away impurity",
    "Rohini":          "Growth, fertility, beauty, sensuality — Moon's most beloved star",
    "Mrigashira":      "Seeking, searching, never satisfied — curious wanderer, creative mind",
    "Ardra":           "Storm, destruction before creation — Rahu's raw power, scientist/researcher",
    "Punarvasu":       "Return of light, renewal, wisdom — Jupiter's star of restoration",
    "Pushya":          "Nourishment, divine food, purest blessing — Saturn's most sattvic nakshatra",
    "Ashlesha":        "Wisdom serpent, mystical power, healing — Mercury's hidden depths",
    "Magha":           "Ancestral power, royalty, throne — Ketu's connection to lineage and authority",
    "Purva Phalguni":  "Pleasure, creative union, rest — Venus's gift of joy and beauty",
    "Uttara Phalguni": "Service through partnership, contracts, social benefactor — Sun-Venus blend",
    "Hasta":           "Skilled hands, dexterity, healing — Moon's practical artistry",
    "Chitra":          "Brilliant creation, architectural mastery — Mars's craftsmanship spark",
    "Swati":           "Independence, flexibility, trade — Rahu's entrepreneurial wind",
    "Vishakha":        "Fierce determination, divided purpose, triumph through focus — Jupiter-Mars",
    "Anuradha":        "Devotion, friendship, spiritual organization — Saturn's loving discipline",
    "Jyeshtha":        "Elder's wisdom, protection, intense power — Mercury-Mars elder chief",
    "Mula":            "Root extraction, radical transformation — Ketu's destruction of false foundations",
    "Purva Ashadha":   "Invincible determination, purification — Venus's unconquerable spirit",
    "Uttara Ashadha":  "Final victory, universal dharma — Sun's ultimate achievement",
    "Shravana":        "Listening, learning, cosmic connection — Moon's ear to divine wisdom",
    "Dhanishtha":      "Wealth through excellence, music, abundance — Mars-Saturn wealth builders",
    "Shatabhisha":     "Healing, hidden truth, 100 healers — Rahu's mystical medicine",
    "Purva Bhadrapada":"Intensity, visionary sacrifice, spiritual warrior — Jupiter-Saturn fire",
    "Uttara Bhadrapada":"Deep wisdom, completion, cosmic serpent — Saturn's ocean of time",
    "Revati":          "Completion, nourishment, safe harbor — Mercury's compassionate end",
}
