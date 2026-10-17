"""Value extraction from Polish commands: numbers/percentages, colours, select options."""

import re

NUMBER = re.compile(r"(?<![\d.,])(\d{1,3})(?:\s*(%|proc\w*))?(?![\d.,])")
WORD_VALUES = [
    (re.compile(r"\b(pół|połow\w*)\b"), 50),
    (re.compile(r"\b(max\w*|maks\w*|pełn\w*|na full)\b"), 100),
    (re.compile(r"\b(minimum|minimaln\w*)\b"), 1),
]

COLORS = {
    "czerwon": [255, 0, 0],
    "zielon": [0, 255, 0],
    "niebiesk": [0, 0, 255],
    "żółt": [255, 255, 0],
    "pomarańcz": [255, 128, 0],
    "fiolet": [128, 0, 255],
    "różow": [255, 105, 180],
    "biał": [255, 255, 255],
    "turkus": [64, 224, 208],
}


def extract_numbers(text):
    """All 0–100 values mentioned, in order of appearance, without duplicates."""
    lowered = text.lower()
    found = [(m.start(), int(m.group(1))) for m in NUMBER.finditer(lowered)]
    for pattern, value in WORD_VALUES:
        found += [(m.start(), value) for m in pattern.finditer(lowered)]
    values = []
    for _, value in sorted(found):
        if 0 <= value <= 100 and value not in values:
            values.append(value)
    return values


def extract_color(text):
    lowered = text.lower()
    for stem, rgb in COLORS.items():
        if stem in lowered:
            return rgb
    return None


def extract_options(text, options):
    lowered = text.lower()
    return [o for o in options if re.search(rf"\b{re.escape(o.lower())}\b", lowered)]


def clamp(value, low, high):
    return max(low, min(high, value))
