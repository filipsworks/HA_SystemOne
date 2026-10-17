"""Polish sentence templates per intent → the "action documents" stored in the vector index,
and the one-line candidate descriptions shown to the reranker and to TypeSafe."""

INTENT_LABELS = {
    "turn_on": "włączenie (włącz, zapal, uruchom)",
    "turn_off": "wyłączenie (wyłącz, zgaś)",
    "toggle": "przełączenie stanu na przeciwny (przełącz)",
    "set_brightness": "zmiana jasności (ustaw jasność na X%, rozjaśnij, przyciemnij)",
    "set_color": "zmiana koloru światła (na czerwono, niebieski…)",
    "set_volume": "zmiana głośności (ustaw głośność na X, ścisz, pogłośnij)",
    "media_play": "odtwarzanie / wznowienie (graj, puść, wznów)",
    "media_pause": "pauza (zatrzymaj, wstrzymaj)",
    "media_next": "następny utwór / kanał",
    "media_previous": "poprzedni utwór / kanał",
    "select_option": "wybór opcji",
    "press": "naciśnięcie przycisku",
    "query_state": "pytanie o aktualny stan, bez zmiany (czy jest włączone? czy się świeci? co gra?)",
}

SENTENCES = {
    "turn_on": ["włącz {n}", "zapal {n}", "uruchom {n}", "odpal {n}"],
    "turn_off": ["wyłącz {n}", "zgaś {n}", "wyłącz {n} proszę"],
    "toggle": ["przełącz {n}", "zmień stan {n}"],
    "set_brightness": ["ustaw jasność {n} na 50%", "rozjaśnij {n}", "przyciemnij {n}", "{n} na 30 procent"],
    "set_color": ["zmień kolor {n} na czerwony", "ustaw {n} na niebiesko", "kolor {n} zielony"],
    "set_volume": ["ustaw głośność {n} na 20", "ścisz {n}", "pogłośnij {n}", "głośność {n} 40%"],
    "media_play": ["włącz odtwarzanie na {n}", "wznów {n}", "graj na {n}", "play {n}"],
    "media_pause": ["pauza na {n}", "zatrzymaj {n}", "wstrzymaj {n}"],
    "media_next": ["następny utwór na {n}", "następny kanał {n}", "dalej na {n}"],
    "media_previous": ["poprzedni utwór na {n}", "poprzedni kanał {n}", "wróć na {n}"],
    "select_option": ["ustaw {n} na {o}", "wybierz {o} w {n}"],
    "press": ["naciśnij {n}", "wciśnij {n}"],
    "query_state": ["czy {n} jest włączone?", "jaki jest stan {n}?", "sprawdź {n}", "czy {n} działa?"],
}


def names_for(entity):
    names = [entity.name, *entity.aliases]
    if entity.where:
        names.append(f"{entity.name} {entity.where}")
    return names


def candidate_description(entity, intent):
    parts = [f"{INTENT_LABELS[intent]}: {entity.name} ({entity.entity_id}, typ {entity.domain})"]
    if entity.area:
        parts.append(f"pomieszczenie: {entity.area}")
    if entity.aliases:
        parts.append("inne nazwy: " + ", ".join(entity.aliases))
    if entity.description:
        parts.append(entity.description)
    if intent == "select_option" and entity.options:
        parts.append("opcje: " + ", ".join(entity.options))
    return "; ".join(parts)


def action_documents(entity):
    """Yield (doc_id, text, metadata) for every (entity, intent) pair."""
    for intent in entity.intents:
        meta = {"entity_id": entity.entity_id, "intent": intent}
        yield f"{entity.entity_id}::{intent}::desc", candidate_description(entity, intent), meta
        option = entity.options[0] if entity.options else "opcja"
        for ni, name in enumerate(names_for(entity)):
            for si, template in enumerate(SENTENCES[intent]):
                text = template.format(n=name, o=option)
                yield f"{entity.entity_id}::{intent}::{ni}.{si}", text, meta


INTENT_QUESTIONS = {
    "turn_on": "turn on",
    "turn_off": "turn off",
    "toggle": "toggle (switch to the opposite state)",
    "set_brightness": "change the brightness of",
    "set_color": "change the colour of",
    "set_volume": "change the volume of",
    "media_play": "start or resume playback on",
    "media_pause": "pause",
    "media_next": "skip to the next track or channel on",
    "media_previous": "go back to the previous track or channel on",
    "select_option": "select an option on",
    "press": "press",
    "query_state": "only check (not change) the current state of",
}


def fits_question(entity, intent):
    """Short yes/no check of one candidate: the device by its names, plus the operation."""
    names = ", ".join(f"„{n}”" for n in [entity.name, *entity.aliases])
    where = f" in the {entity.area}" if entity.area else ""
    return f"Does `command` ask to {INTENT_QUESTIONS[intent]} the device {names}{where}?"
