"""Weekly medication schedule: pure helpers over a {day: {medication: taken}} dict."""
import unicodedata

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DAY_LETTERS = ["L", "M", "X", "J", "V", "S", "D"]

# Day status, shared by the AR overlay and the on-screen week view
NONE, PENDING, DONE = "none", "pending", "done"


def _plain(text):
    """Lowercase text without accents ("Miércoles" -> "miercoles")."""
    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalize_day(word):
    """Return the canonical day name for a spoken/typed word, or None if it is not a weekday."""
    return next((day for day in DAYS if _plain(day) == _plain(word)), None)


def _find(meds, day, name):
    """Return the stored medication name matching `name` case-insensitively, or None."""
    return next((med for med in meds.get(day, {}) if _plain(med) == _plain(name)), None)


def add_medication(meds, day, name):
    """Add a medication (not taken yet). Returns the stored name."""
    name = name.strip()
    existing = _find(meds, day, name)
    if existing:
        return existing
    meds.setdefault(day, {})[name] = False
    return name


def set_taken(meds, day, name, taken=True):
    """Mark a medication as taken (or not). Returns the stored name, or None if it does not exist."""
    existing = _find(meds, day, name)
    if existing is None:
        return None
    meds[day][existing] = taken
    return existing


def remove_medication(meds, day, name):
    """Remove a medication. Returns True if something was removed."""
    existing = _find(meds, day, name)
    if existing is None:
        return False
    del meds[day][existing]
    if not meds[day]:
        del meds[day]
    return True


def day_status(meds, day):
    """NONE if nothing is scheduled, DONE if everything was taken, PENDING otherwise."""
    items = meds.get(day)
    if not items:
        return NONE
    return DONE if all(items.values()) else PENDING


def pending(meds):
    """List of (day, medication) still to be taken, in weekday order."""
    return [(day, med) for day in DAYS for med, taken in meds.get(day, {}).items() if not taken]
