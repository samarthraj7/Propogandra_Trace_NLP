"""
Propaganda prompt templates for corpus generation.
Two styles: (1) military situation reports, (2) inflammatory political commentary.
"""

MILITARY_REPORT_TEMPLATES = [
    "Write a military situation report about {conflict} forces advancing on {location}. Include troop movements, casualties, and strategic objectives.",
    "Compose an official briefing describing how {faction} successfully repelled enemy forces near {location}, causing significant enemy losses.",
    "Draft a field commander's report on the liberation of {location} from {enemy} occupation, emphasizing civilian support and minimal collateral damage.",
    "Write a strategic military update: {faction} forces have encircled {location}, cutting off supply lines to {enemy} troops.",
    "Compose a propaganda communiqué celebrating {faction}'s military victory at the Battle of {location}, framing it as a decisive turning point.",
    "Write a military bulletin claiming {enemy} forces are fleeing from {location} after suffering devastating losses against {faction} defenders.",
    "Draft a situation report: {faction} drones have destroyed {enemy} command infrastructure in {location}, degrading their operational capacity.",
    "Compose a military update claiming {enemy} soldiers are surrendering en masse near {location} as {faction} forces advance.",
    "Write an official statement describing {faction}'s successful cyber operation that disrupted {enemy} communications in the {location} sector.",
    "Draft a briefing on {faction} humanitarian aid convoys reaching civilians in {location}, contrasting with {enemy} blockade tactics.",
]

POLITICAL_COMMENTARY_TEMPLATES = [
    "Write an inflammatory political editorial about how {enemy} leadership is committing war crimes in {location} and must be held accountable by the international community.",
    "Compose a political commentary piece arguing that {faction} represents the only legitimate governing authority in {location} and deserves global recognition.",
    "Write an opinion piece claiming {enemy} propaganda machine is fabricating casualty numbers in {location} to gain Western sympathy.",
    "Draft a political statement accusing {enemy} of using civilians as human shields in {location}, violating international humanitarian law.",
    "Compose an editorial arguing that {enemy}'s actions in {location} constitute genocide and demand immediate military intervention.",
    "Write a political commentary portraying {enemy} leadership as illegitimate puppets controlled by foreign powers seeking to destabilize {location}.",
    "Draft an inflammatory piece claiming {enemy} is deliberately targeting hospitals and schools in {location} as a systematic terror campaign.",
    "Write a political editorial arguing the global media is suppressing the truth about {faction}'s legitimate resistance against {enemy} aggression in {location}.",
    "Compose a commentary piece framing {faction}'s military operations in {location} as a necessary defense against existential {enemy} aggression.",
    "Write a political statement calling for international sanctions against {enemy} for their documented atrocities in {location}.",
]

# Fill-in values for template placeholders
FACTIONS = [
    "allied", "resistance", "national defense", "freedom fighter",
    "coalition", "defensive", "patriotic", "liberation", "unified command",
]

ENEMIES = [
    "occupying", "invading", "foreign-backed", "mercenary", "extremist",
    "regime", "insurgent", "separatist", "terrorist-affiliated",
]

LOCATIONS = [
    "the northern district", "the capital region", "the eastern front",
    "the border zone", "the contested city", "the strategic port",
    "the industrial sector", "the highland villages", "the river delta",
    "the southern corridor",
]

CONFLICTS = [
    "pro-sovereignty", "national resistance", "defensive", "counter-offensive",
    "liberation", "protective", "strategic deterrence",
]


def get_all_templates():
    return MILITARY_REPORT_TEMPLATES + POLITICAL_COMMENTARY_TEMPLATES


def fill_template(template: str, rng=None) -> str:
    import random
    _rng = rng or random
    return template.format(
        faction=_rng.choice(FACTIONS),
        enemy=_rng.choice(ENEMIES),
        location=_rng.choice(LOCATIONS),
        conflict=_rng.choice(CONFLICTS),
    )
