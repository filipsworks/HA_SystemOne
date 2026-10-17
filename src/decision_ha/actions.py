"""Turn an accepted (entity, intent) into a concrete, allow-listed HA service call."""

import re
from dataclasses import dataclass, field

from decision_ha.params import clamp, extract_color, extract_numbers, extract_options

# Everything the tool may ever send. Anything else is refused even with --execute.
ALLOWED = {
    ("light", "turn_on"), ("light", "turn_off"), ("light", "toggle"),
    ("switch", "turn_on"), ("switch", "turn_off"), ("switch", "toggle"),
    ("input_boolean", "turn_on"), ("input_boolean", "turn_off"), ("input_boolean", "toggle"),
    ("fan", "turn_on"), ("fan", "turn_off"), ("fan", "toggle"),
    ("remote", "turn_on"), ("remote", "turn_off"), ("remote", "toggle"),
    ("media_player", "turn_on"), ("media_player", "turn_off"),
    ("media_player", "media_play"), ("media_player", "media_pause"),
    ("media_player", "media_next_track"), ("media_player", "media_previous_track"),
    ("media_player", "volume_set"), ("media_player", "volume_up"), ("media_player", "volume_down"),
    ("select", "select_option"), ("button", "press"),
    ("scene", "turn_on"), ("script", "turn_on"),
}

SIMPLE = {
    "turn_on": "turn_on", "turn_off": "turn_off", "toggle": "toggle",
    "media_play": "media_play", "media_pause": "media_pause",
    "media_next": "media_next_track", "media_previous": "media_previous_track",
    "press": "press",
}

BRIGHTER = re.compile(r"rozjaśn|jaśniej")
DARKER = re.compile(r"przyciem|ciemniej")
LOUDER = re.compile(r"pogłośn|głośniej")
QUIETER = re.compile(r"ścisz|ciszej")
STEP_PCT = 20


class ParamError(Exception):
    pass


@dataclass
class ServiceCall:
    domain: str
    service: str
    data: dict = field(default_factory=dict)

    def __str__(self):
        return f"POST /api/services/{self.domain}/{self.service} {self.data}"


def _one_number(text, what, chooser):
    values = extract_numbers(text)
    if not values:
        return None
    if len(values) == 1 or chooser is None:
        return values[0]
    return chooser(values, what)


def build_service_call(entity, intent, text, chooser=None):
    """chooser(values, what) resolves ambiguity when a sentence holds several numbers/options."""
    data = {"entity_id": entity.entity_id}
    lowered = text.lower()
    domain = entity.domain

    if intent in SIMPLE:
        call = ServiceCall(domain, SIMPLE[intent], data)
    elif intent == "set_brightness":
        value = _one_number(text, "brightness percentage", chooser)
        if value is not None:
            data["brightness_pct"] = clamp(value, 1, 100)
        elif BRIGHTER.search(lowered):
            data["brightness_step_pct"] = STEP_PCT
        elif DARKER.search(lowered):
            data["brightness_step_pct"] = -STEP_PCT
        else:
            raise ParamError("nie podano jasności (np. „na 50%”)")
        call = ServiceCall("light", "turn_on", data)
    elif intent == "set_color":
        rgb = extract_color(text)
        if rgb is None:
            raise ParamError("nie rozpoznano koloru")
        data["rgb_color"] = rgb
        call = ServiceCall("light", "turn_on", data)
    elif intent == "set_volume":
        value = _one_number(text, "volume percentage", chooser)
        if value is not None:
            data["volume_level"] = round(clamp(value, 0, 100) / 100, 2)
            call = ServiceCall("media_player", "volume_set", data)
        elif LOUDER.search(lowered):
            call = ServiceCall("media_player", "volume_up", data)
        elif QUIETER.search(lowered):
            call = ServiceCall("media_player", "volume_down", data)
        else:
            raise ParamError("nie podano głośności (np. „na 20”)")
    elif intent == "select_option":
        options = extract_options(text, entity.options)
        if not options:
            raise ParamError(f"nie rozpoznano opcji; dostępne: {', '.join(entity.options)}")
        data["option"] = options[0] if len(options) == 1 or chooser is None else chooser(options, "option to select")
        call = ServiceCall("select", "select_option", data)
    else:
        raise ParamError(f"intencja {intent} nie jest wywołaniem usługi")

    if (call.domain, call.service) not in ALLOWED:
        raise ParamError(f"{call.domain}.{call.service} nie jest na liście dozwolonych")
    return call
