"""Polish answers for state questions."""

STATES = {
    "on": "jest włączone",
    "off": "jest wyłączone",
    "playing": "odtwarza",
    "paused": "jest wstrzymane (pauza)",
    "idle": "jest bezczynne",
    "standby": "jest w trybie czuwania",
    "unavailable": "jest niedostępne",
    "unknown": "ma nieznany stan",
}


def describe_state(entity, state):
    value = state.get("state", "unknown")
    attrs = state.get("attributes") or {}
    text = f"{entity.name} {STATES.get(value, f'ma stan „{value}”')}"
    extras = []
    if attrs.get("brightness") is not None and value == "on":
        extras.append(f"jasność {round(attrs['brightness'] / 255 * 100)}%")
    if attrs.get("volume_level") is not None:
        extras.append(f"głośność {round(attrs['volume_level'] * 100)}%")
    if attrs.get("media_title"):
        extras.append(f"„{attrs['media_title']}”")
    if entity.domain == "select":
        text = f"{entity.name}: {value}"
    return text + (f" ({', '.join(extras)})" if extras else "") + "."
