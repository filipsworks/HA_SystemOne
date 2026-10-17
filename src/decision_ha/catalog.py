"""Catalog of controllable entities: which ones, where they are, what can be done with them."""

import json
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch

import yaml

CONTROLLABLE_DOMAINS = {
    "light", "switch", "media_player", "remote", "select", "button",
    "fan", "input_boolean", "scene", "script",
}

# media_player supported_features bits (homeassistant.components.media_player.MediaPlayerEntityFeature)
MP_PAUSE = 1
MP_VOLUME_SET = 4
MP_PREVIOUS_TRACK = 16
MP_NEXT_TRACK = 32
MP_TURN_ON = 128
MP_TURN_OFF = 256
MP_PLAY = 16384

ON_OFF = ["turn_on", "turn_off", "toggle"]


@dataclass
class Entity:
    entity_id: str
    domain: str
    name: str
    area: str | None = None          # Polish area name, e.g. "sypialnia"
    where: str | None = None         # Polish locative phrase, e.g. "w sypialni"
    aliases: list[str] = field(default_factory=list)
    description: str | None = None
    intents: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)  # select options


def derive_intents(domain, attributes):
    if domain in ("switch", "input_boolean", "fan", "remote"):
        intents = list(ON_OFF)
    elif domain == "light":
        intents = list(ON_OFF)
        modes = set(attributes.get("supported_color_modes") or [])
        if modes - {"onoff"}:
            intents.append("set_brightness")
        if modes & {"hs", "rgb", "rgbw", "rgbww", "xy"}:
            intents.append("set_color")
    elif domain == "media_player":
        features = attributes.get("supported_features") or 0
        intents = []
        if features & MP_TURN_ON:
            intents.append("turn_on")
        if features & MP_TURN_OFF:
            intents.append("turn_off")
        if features & MP_PLAY:
            intents.append("media_play")
        if features & MP_PAUSE:
            intents.append("media_pause")
        if features & MP_NEXT_TRACK:
            intents.append("media_next")
        if features & MP_PREVIOUS_TRACK:
            intents.append("media_previous")
        if features & MP_VOLUME_SET:
            intents.append("set_volume")
    elif domain == "select":
        intents = ["select_option"]
    elif domain == "button":
        intents = ["press"]
    elif domain in ("scene", "script"):
        intents = ["turn_on"]
    else:
        intents = []
    if domain not in ("button", "scene", "script"):
        intents.append("query_state")
    return intents


def load_aliases(path):
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def is_excluded(entity_id, aliases):
    entry = (aliases.get("entities") or {}).get(entity_id) or {}
    if entry.get("exclude"):
        return True
    return any(fnmatch(entity_id, pattern) for pattern in aliases.get("exclude") or [])


def build_catalog(states, areas, aliases):
    """Pure: HA states + entity→HA-area map + aliases.yaml content → list[Entity]."""
    area_names = aliases.get("areas") or {}
    overrides = aliases.get("entities") or {}
    catalog = []
    for st in states:
        entity_id = st["entity_id"]
        domain = entity_id.split(".", 1)[0]
        if domain not in CONTROLLABLE_DOMAINS or is_excluded(entity_id, aliases):
            continue
        attrs = st.get("attributes") or {}
        entry = overrides.get(entity_id) or {}
        ha_area = entry.get("area") or areas.get(entity_id)
        area_info = area_names.get(ha_area) or {}
        intents = derive_intents(domain, attrs)
        if not intents:
            continue
        catalog.append(Entity(
            entity_id=entity_id,
            domain=domain,
            name=entry.get("name") or attrs.get("friendly_name") or entity_id,
            area=area_info.get("name") or ha_area,
            where=area_info.get("where"),
            aliases=list(entry.get("aliases") or []),
            description=entry.get("description"),
            intents=intents,
            options=list(attrs.get("options") or []),
        ))
    return sorted(catalog, key=lambda e: e.entity_id)


def save_catalog(catalog, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(e) for e in catalog], ensure_ascii=False, indent=2))


def load_catalog(path):
    if not path.exists():
        raise SystemExit(f"No catalog at {path}. Run `decide sync` first.")
    return {d["entity_id"]: Entity(**d) for d in json.loads(path.read_text())}


# Admin/diagnostic entities common to most installs; `decide init` starts every aliases.yaml with them.
DEFAULT_EXCLUDE = [
    "*zigbee2mqtt_bridge*",
    "button.*_identify",
    "select.*_power_on_behavior",
]


def aliases_skeleton(states, ha_areas, entity_areas):
    """Pure: a starting aliases.yaml for a new home — every HA area and controllable entity,
    with the Polish parts left for the user to fill in."""
    q = lambda s: json.dumps(s, ensure_ascii=False)  # a JSON string is a valid YAML scalar
    lines = [
        "# Wygenerowane przez `decide init`. Uzupełnij, potem: `decide sync && decide index`.",
        "",
        "# Obszary HA → polska nazwa i forma \"gdzie\", np. Bedroom: {name: sypialnia, where: w sypialni}",
        "areas:",
    ]
    lines += [f"  {q(area)}: {{name: {q(area)}, where: null}}" for area in sorted(ha_areas)]
    lines += ["", "# Encje pomijane (wzorce fnmatch).", "exclude:"]
    lines += [f"  - {q(pattern)}" for pattern in DEFAULT_EXCLUDE]
    lines += [
        "",
        "# Per-encja: name, aliases, area (nazwa obszaru HA), description, exclude: true.",
        "# Odkomentuj encje, którym chcesz nadać polskie nazwy lub opisy.",
        "entities:",
    ]
    for e in build_catalog(states, entity_areas, {"exclude": DEFAULT_EXCLUDE}):
        lines.append(f"#  {e.entity_id}:  # {e.name}" + (f" ({e.area})" if e.area else ""))
        lines.append("#    aliases: []")
    return "\n".join(lines) + "\n"
