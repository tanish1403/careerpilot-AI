"""Tolerant date parsing / normalisation shared by the extractor, contradiction checks and
the resume renderer. Normalised forms: 'YYYY-MM', 'YYYY', 'Present'."""
from __future__ import annotations

import re
from datetime import date

_MONTHS: dict[str, int] = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
    # Spanish / Portuguese / Italian
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12, "ene": 1, "abr": 4, "ago": 8, "dic": 12, "janeiro": 1, "fevereiro": 2,
    "março": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9, "outubro": 10,
    "dezembro": 12, "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "settembre": 9, "ottobre": 10, "dicembre": 12,
    # French
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12, "janv": 1, "févr": 2, "juil": 7,
    # German
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "juni": 6, "juli": 7, "oktober": 10,
    "dezember": 12, "mär": 3, "okt": 10, "dez": 12,
}
PRESENT_WORDS = {
    "present", "current", "now", "today", "ongoing", "till date", "to date", "till now",
    "actualidad", "presente", "actualmente", "heute", "aujourd'hui", "actuel", "atual", "oggi",
    "gegenwart", "bis heute", "en curso",
}

MONTH_ALT = "|".join(sorted((re.escape(k) for k in _MONTHS), key=len, reverse=True))
DATE_PAT = (rf"(?:(?:(?:{MONTH_ALT})\.?\s*,?\s*)?(?:19|20)\d{{2}}"
            r"|(?:0?[1-9]|1[0-2])\s*[/.-]\s*(?:19|20)\d{2}"
            r"|(?:19|20)\d{2}\s*[/.-]\s*(?:0?[1-9]|1[0-2]))")
PRESENT_PAT = "|".join(sorted((re.escape(w) for w in PRESENT_WORDS), key=len, reverse=True))
RANGE_RE = re.compile(
    rf"(?P<start>{DATE_PAT})\s*(?:[-–—‒]|\bto\b|\buntil\b|\bbis\b|\bhasta\b|"
    rf"\bà\b|\bau\b|\ba\b)\s*(?P<end>{DATE_PAT}|{PRESENT_PAT})(?![\w])",
    re.I,
)
_YM = re.compile(r"^(?P<y>(?:19|20)\d{2})\s*[/.-]\s*(?P<m>0?[1-9]|1[0-2])$")
_MY = re.compile(r"^(?P<m>0?[1-9]|1[0-2])\s*[/.-]\s*(?P<y>(?:19|20)\d{2})$")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def is_present(s: str | None) -> bool:
    return bool(s) and s.strip().lower().strip(".") in PRESENT_WORDS


def parse_ym(s: str | None, *, end: bool = False, today: date | None = None
             ) -> tuple[int, int] | None:
    """Return (year, month) or None. Year-only -> January (start) / December (end)."""
    if not s:
        return None
    t = s.strip()
    if is_present(t):
        d = today or date.today()
        return d.year, d.month
    m = _YM.match(t) or _MY.match(t)
    if m:
        return int(m["y"]), int(m["m"])
    if _YEAR.match(t):
        return int(t), 12 if end else 1
    words = re.findall(r"[^\W\d_]+", t.lower())
    years = re.findall(r"(?:19|20)\d{2}", t)
    if years:
        for w in words:
            if w in _MONTHS:
                return int(years[-1]), _MONTHS[w]
        if len(words) == 0 or all(w not in _MONTHS for w in words):
            return None
    return None


def normalize_date(s: str | None) -> str | None:
    """Normalise to 'YYYY-MM' / 'YYYY' / 'Present'. Returns None if unparseable."""
    if not s or not str(s).strip():
        return None
    t = str(s).strip()
    if is_present(t):
        return "Present"
    if _YEAR.match(t):
        return t
    ym = parse_ym(t)
    if ym is None:
        return None
    return f"{ym[0]:04d}-{ym[1]:02d}"


def format_date(s: str | None) -> str:
    """Human format used by the resume renderer: 'Jan 2020', '2020', 'Present'."""
    if not s:
        return ""
    n = normalize_date(s)
    if n is None:
        return str(s).strip()
    if n in ("Present",) or len(n) == 4:
        return n
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{names[int(n[5:7]) - 1]} {n[:4]}"


def month_index(ym: tuple[int, int]) -> int:
    return ym[0] * 12 + ym[1] - 1
