"""Domain vocabulary and spoken-language normalisation.

Speech recognition returns loose, inconsistent text: "salinity" may arrive as
"sanity", numbers may be words or digits, and users say "currents" when the
dataset calls them "u" and "v". Everything that bridges that gap lives here,
so the intent grammar can work against clean, canonical tokens.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
#: Spoken forms mapped to canonical dataset variable names. Includes common
#: mis-recognitions, because a demo should not fail on a wobbly microphone.
VARIABLE_SYNONYMS: dict[str, str] = {
    "temperature": "temperature",
    "temp": "temperature",
    "temperatures": "temperature",
    "thermal": "temperature",
    "heat": "temperature",
    "sst": "temperature",
    "sea temperature": "temperature",
    "water temperature": "temperature",
    "salinity": "salinity",
    "sanity": "salinity",       # frequent mis-hearing
    "salinities": "salinity",
    "salt": "salinity",
    "saltiness": "salinity",
    "chlorophyll": "chlorophyll",
    "chlorophyl": "chlorophyll",
    "chloro": "chlorophyll",
    "chlorophyll a": "chlorophyll",
    "algae": "chlorophyll",
    "biology": "chlorophyll",
    "productivity": "chlorophyll",
    "current": "u",
    "currents": "u",
    "flow": "u",
    "velocity": "u",
    "circulation": "u",
    "ssh": "ssh",
    "sea surface height": "ssh",
    "surface height": "ssh",
    "sea level": "ssh",
    "bathymetry": "bathymetry",
    "seafloor": "bathymetry",
    "sea floor": "bathymetry",
    "topography": "bathymetry",
    "oxygen": "oxygen",
}

#: Variables that are layers rather than the primary coloured field.
LAYER_SYNONYMS: dict[str, str] = {
    "temperature": "surface",
    "surface temperature": "surface",
    "surface temp": "surface",
    "sst": "surface",
    "field": "surface",
    "current": "currents",
    "currents": "currents",
    "flow": "currents",
    "streamlines": "currents",
    "particles": "currents",
    "chlorophyll": "chlorophyll",
    "algae": "chlorophyll",
    "salinity": "salinity",
    "salt": "salinity",
    "sea surface height": "ssh",
    "ssh": "ssh",
    "sea level": "ssh",
    "bathymetry": "bathymetry",
    "seafloor": "bathymetry",
    "sea floor": "bathymetry",
    "terrain": "bathymetry",
}

# ---------------------------------------------------------------------------
# Analysis layers
# ---------------------------------------------------------------------------
ANALYSIS_SYNONYMS: dict[str, str] = {
    "anomaly": "anomaly",
    "anomalies": "anomaly",
    "heatwave": "anomaly",
    "heat wave": "anomaly",
    "marine heatwave": "anomaly",
    "climatology": "anomaly",
    "eddy": "eddies",
    "eddies": "eddies",
    "eddy census": "eddies",
    "vortices": "eddies",
    "okubo weiss": "eddies",
    "bias": "bias",
    "bias map": "bias",
    "verification": "bias",
    "model bias": "bias",
    "validation": "bias",
    "mixed layer": "mixed_layer_depth",
    "mixed layer depth": "mixed_layer_depth",
    "mld": "mixed_layer_depth",
    "thermocline": "thermocline",
}

# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------
COLORMAP_SYNONYMS: dict[str, str] = {
    "thermal": "thermal",
    "haline": "haline",
    "saline": "haline",
    "deep": "deep",
    "dense": "dense",
    "algae": "algae",
    "ice": "ice",
    "solar": "solar",
    "turbid": "turbid",
    "speed": "speed",
    "oxy": "oxy",
    "matter": "matter",
    "amp": "amp",
    "balance": "balance",
    "delta": "delta",
    "curl": "curl",
    "diff": "diff",
    "viridis": "viridis",
    "plasma": "plasma",
    "inferno": "inferno",
    "magma": "magma",
    "cividis": "cividis",
    "phase": "phase",
    "twilight": "twilight",
}

# ---------------------------------------------------------------------------
# Named regions, with a camera target and a framing altitude
# ---------------------------------------------------------------------------
REGIONS: dict[str, tuple[float, float, float, str]] = {
    # spoken key -> (lat, lon, height_km, display name)
    "bay of bengal": (15.0, 88.0, 2200, "the Bay of Bengal"),
    "bengal": (15.0, 88.0, 2200, "the Bay of Bengal"),
    "arabian sea": (16.0, 65.0, 2200, "the Arabian Sea"),
    "arabia": (16.0, 65.0, 2200, "the Arabian Sea"),
    "somali coast": (6.0, 51.0, 1800, "the Somali coast"),
    "somalia": (6.0, 51.0, 1800, "the Somali coast"),
    "oman": (19.0, 58.5, 1600, "the Oman coast"),
    "andaman sea": (12.0, 95.0, 1700, "the Andaman Sea"),
    "andaman": (12.0, 95.0, 1700, "the Andaman Sea"),
    "laccadive sea": (9.0, 74.0, 1700, "the Laccadive Sea"),
    "lakshadweep": (10.0, 72.5, 1500, "Lakshadweep"),
    "maldives": (3.0, 73.0, 1600, "the Maldives"),
    "sri lanka": (7.5, 80.5, 1400, "Sri Lanka"),
    "equator": (0.0, 75.0, 2600, "the equatorial Indian Ocean"),
    "equatorial indian ocean": (0.0, 75.0, 2600, "the equatorial Indian Ocean"),
    "southern indian ocean": (-8.0, 75.0, 2600, "the southern Indian Ocean"),
    "west coast": (14.0, 72.0, 1700, "India's west coast"),
    "east coast": (15.0, 82.0, 1700, "India's east coast"),
    "india": (12.0, 78.0, 3200, "India"),
    "gujarat": (21.0, 68.0, 1400, "the Gujarat coast"),
    "kerala": (9.5, 75.0, 1300, "the Kerala coast"),
    "chennai": (13.0, 80.5, 1200, "Chennai"),
    "mumbai": (19.0, 72.0, 1200, "Mumbai"),
    "visakhapatnam": (17.7, 83.3, 1200, "Visakhapatnam"),
    "kochi": (10.0, 76.0, 1200, "Kochi"),
}

# ---------------------------------------------------------------------------
# Spoken numbers
# ---------------------------------------------------------------------------
_UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000}

_NUMBER_WORD = re.compile(
    r"\b(" + "|".join(list(_UNITS) + list(_TENS) + list(_SCALES) + ["and"]) + r")\b"
)


def words_to_number(text: str) -> float | None:
    """Convert a spoken number phrase to a value.

    Handles "five hundred", "twelve fifty", "one thousand two hundred".
    Returns ``None`` when the phrase contains no number words at all.
    """
    tokens = _NUMBER_WORD.findall(text.lower())
    if not tokens:
        return None

    total = 0.0
    current = 0.0
    seen = False

    for token in tokens:
        if token == "and":
            continue
        if token in _UNITS:
            current += _UNITS[token]
            seen = True
        elif token in _TENS:
            current += _TENS[token]
            seen = True
        elif token in _SCALES:
            scale = _SCALES[token]
            if scale == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * scale
                current = 0.0
            seen = True

    if not seen:
        return None
    return total + current


_DIGITS = re.compile(r"-?\d+(?:\.\d+)?")


def extract_number(text: str) -> float | None:
    """First number in a phrase, whether written as digits or words."""
    match = _DIGITS.search(text)
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return words_to_number(text)


def extract_numbers(text: str, limit: int = 2) -> list[float]:
    """Up to ``limit`` numbers, for range commands like '22 to 30'."""
    values = [float(m) for m in _DIGITS.findall(text)[:limit]]
    if values:
        return values
    single = words_to_number(text)
    return [single] if single is not None else []


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
# "can you" / "could you" is deliberately NOT stripped: removing it turns
# "what can you do" into "what do", which no longer reads as a request for
# help. Patterns use search(), so leaving politeness in place is harmless.
_FILLER = re.compile(
    r"\b(please|kindly|i want to|i would like to|"
    r"lets|just|um|uh|okay|alright|hey|hi|hello)\b"
)
_PUNCT = re.compile(r"[^\w\s.\-]")
_SPACE = re.compile(r"\s+")

#: Wake words that address the agent directly.
WAKE_WORDS = ("deep", "hey deep", "ok deep", "okay deep", "hello deep", "dip")


def normalise(text: str) -> str:
    """Lower-case, strip punctuation and filler, collapse whitespace."""
    lowered = (text or "").lower().strip()
    lowered = _PUNCT.sub(" ", lowered)
    lowered = _FILLER.sub(" ", lowered)
    return _SPACE.sub(" ", lowered).strip()


def strip_wake_word(text: str) -> str:
    """Remove a leading address to the agent: 'deep, show salinity'."""
    cleaned = normalise(text)
    for wake in sorted(WAKE_WORDS, key=len, reverse=True):
        if cleaned.startswith(wake):
            cleaned = cleaned[len(wake) :].strip(" ,")
            break
    return cleaned


def contains_wake_word(text: str) -> bool:
    cleaned = normalise(text)
    return any(
        re.search(rf"\b{re.escape(wake)}\b", cleaned) for wake in WAKE_WORDS
    )


def lookup(table: dict[str, str], text: str) -> str | None:
    """Longest-match lookup of a synonym table inside a phrase.

    Longest first so "sea surface height" is not shadowed by "sea".
    """
    for phrase in sorted(table, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return table[phrase]
    return None


def lookup_region(text: str) -> tuple[float, float, float, str] | None:
    for phrase in sorted(REGIONS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return REGIONS[phrase]
    return None


# ---------------------------------------------------------------------------
# Spoken units
# ---------------------------------------------------------------------------
#: CF unit strings are precise but unspeakable: a synthesiser reads
#: "degree_Celsius" as "degree underscore Celsius". These are the forms Deep
#: says aloud.
SPOKEN_UNITS: dict[str, str] = {
    "degree_celsius": "degrees Celsius",
    "degrees_celsius": "degrees Celsius",
    "celsius": "degrees Celsius",
    "degc": "degrees Celsius",
    "psu": "P S U",
    "m s-1": "metres per second",
    "m/s": "metres per second",
    "mg m-3": "milligrams per cubic metre",
    "micromole kg-1": "micromoles per kilogram",
    "m": "metres",
    "1": "",
}


def speak_units(units: str | None) -> str:
    """Render a CF unit string in a form a synthesiser reads correctly."""
    if not units:
        return ""
    return SPOKEN_UNITS.get(units.strip().lower(), units)
