"""Final decision with TypeSafe: one system_one call over the reranked shortlist, then a gate."""

from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul

NONE = "none"

ACTION_INSTRUCTIONS = (
    "The user gave a smart-home command in Polish (`command`). Which of these actions "
    "does the command ask for? Match both the device (name, room) and the operation. "
    "Choose 'none' if no option matches."
)
GATE_INSTRUCTIONS = (
    "Is `command` a request to control or check a device in the home "
    "(lights, switches, TV, speakers, media), rather than chit-chat or an unrelated question?"
)


@dataclass
class Decision:
    choice: str                       # candidate key or NONE
    confidence: float
    probabilities: dict[str, float]
    fits: dict[str, float]            # candidate key → noul
    gate: float
    accepted: bool
    reason: str = ""
    alternatives: list[str] = field(default_factory=list)


def build_questions(candidates, describe, fits_question):
    criteria = {c.key: describe(c) for c in candidates}
    criteria[NONE] = "Żadna z powyższych akcji nie pasuje do polecenia."
    questions = {
        "action": Choice(instructions=ACTION_INSTRUCTIONS, criteria=criteria),
        "gate": Noul(instructions=GATE_INSTRUCTIONS),
    }
    for i, c in enumerate(candidates):
        questions[f"fits_{i}"] = Noul(instructions=fits_question(c))
    return questions


def apply_gate(choice, confidence, fits, gate, settings):
    """Pure: return (accepted, reason)."""
    if gate < settings.min_gate:
        return False, f"to nie wygląda na polecenie dla domu (gate={gate:.2f})"
    if choice == NONE:
        return False, "żadna akcja nie pasuje"
    if confidence < settings.min_confidence:
        return False, f"zbyt niska pewność ({confidence:.2f} < {settings.min_confidence})"
    if fits.get(choice, 0.0) < settings.min_fits:
        return False, f"kontrola dopasowania nie przeszła (fits={fits.get(choice, 0.0):.2f})"
    return True, "ok"


def decide(client, text, candidates, describe, fits_question, settings, home=""):
    response = client.system_one(
        state={"command": text, "home": home},
        questions=build_questions(candidates, describe, fits_question),
        model=settings.typesafe_model,
    )
    action = response.choices["action"]
    fits = {c.key: response.nouls[f"fits_{i}"].noul for i, c in enumerate(candidates)}
    gate = response.nouls["gate"].noul
    accepted, reason = apply_gate(action.choice, action.confidence, fits, gate, settings)
    ranked = sorted(action.probabilities.items(), key=lambda kv: -kv[1])
    return Decision(
        choice=action.choice,
        confidence=action.confidence,
        probabilities=dict(action.probabilities),
        fits=fits,
        gate=gate,
        accepted=accepted,
        reason=reason,
        alternatives=[k for k, _ in ranked if k != NONE][:3],
    )


def choose_value(client, text, values, what, settings):
    """Pick one of several pre-parsed values (e.g. two numbers in one sentence)."""
    response = client.system_one(
        state={"command": text},
        questions={"value": Choice(
            instructions=f"Which value in `command` is the {what}?",
            criteria={str(v): None for v in values},
        )},
        model=settings.typesafe_model,
    )
    picked = response.choices["value"].choice
    return next(v for v in values if str(v) == picked)
