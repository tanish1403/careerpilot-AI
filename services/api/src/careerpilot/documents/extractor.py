"""Deterministic, rule-based extraction of PROPOSED profile facts from parsed documents.

Nothing produced here is ever 'confirmed'. Confidence is a heuristic in [0, 1]."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dates import DATE_PAT, RANGE_RE, normalize_date
from .factschema import fact_key, normalize_value
from .parsers import Line, ParsedDocument

SECTION_WORDS: dict[str, set[str]] = {
    "experience": {"experience", "work experience", "professional experience", "employment",
                   "employment history", "work history", "career history", "internships",
                   "relevant experience", "experiencia", "experiencia laboral",
                   "experiencia profesional", "expérience", "expérience professionnelle",
                   "berufserfahrung", "experiência", "esperienza", "experience professionnelle"},
    "education": {"education", "academic background", "education and training", "academics",
                  "educación", "formación", "formación académica", "formation", "éducation",
                  "ausbildung", "bildung", "educação", "formação", "istruzione",
                  "academic qualifications"},
    "skills": {"skills", "technical skills", "core competencies", "technologies", "key skills",
               "skills and tools", "tools and technologies", "technical proficiencies",
               "habilidades", "competencias", "compétences", "kenntnisse", "fähigkeiten",
               "competências", "competenze", "tech stack", "areas of expertise"},
    "projects": {"projects", "personal projects", "selected projects", "academic projects",
                 "side projects", "proyectos", "projets", "projekte", "projetos", "progetti"},
    "publications": {"publications", "papers", "research publications",
                     "selected publications", "publicaciones", "veröffentlichungen",
                     "publicações"},
    "certifications": {"certifications", "certificates", "licenses and certifications",
                       "certifications and licenses", "courses", "certificaciones",
                       "zertifikate", "certificações", "licenses"},
    "summary": {"summary", "professional summary", "profile", "about me", "objective",
                "career objective", "personal statement", "resumen", "perfil", "profil",
                "zusammenfassung", "resumo", "executive summary"},
    "ignore": {"languages", "interests", "hobbies", "references", "awards", "honors",
               "awards and honors", "volunteering", "volunteer experience", "idiomas",
               "langues", "sprachen", "intereses", "activities", "achievements", "contact"},
}
_HEAD_LOOKUP = {w: k for k, ws in SECTION_WORDS.items() for w in ws}
BULLET_RE = re.compile(r"^\s*[•●▪◦‣·■⁃∙○"
                       r"*\-–—>+]\s+")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s,;|)>\]]+|"
                    r"\b(?:linkedin\.com/in|github\.com|gitlab\.com)/[^\s,;|)>\]]+", re.I)
PHONE_RE = re.compile(r"(?<![\w/])(\+?\(?\d[\d\s().-]{7,}\d)(?![\w/])")
TITLE_WORDS = re.compile(
    r"\b(engineer|developer|manager|analyst|intern|internship|scientist|designer|consultant|"
    r"lead|director|architect|specialist|associate|assistant|officer|researcher|"
    r"administrator|coordinator|head|president|vp|founder|co-founder|technician|tester|qa|"
    r"sre|devops|programmer|teacher|professor|lecturer|instructor|executive|supervisor|"
    r"representative|advisor|tutor|fellow|trainee|ingenier[oa]|desarrolladora?|analista|gerente|"
    r"ingénieur|développeur|entwickler|ingenieur|leiter|engenheiro|desenvolvedor)\b", re.I)
DEGREE_RE = re.compile(
    r"\b(bachelor|b\.?\s?sc?\.?|b\.?\s?tech|b\.?\s?e\.?|b\.?\s?a\.?|b\.?b\.?a|master|"
    r"m\.?\s?sc?\.?|m\.?\s?tech|m\.?\s?a\.?|m\.?b\.?a|ph\.?\s?d|doctor(?:ate)?|associate|"
    r"diploma|licenciatura|grado|maestr[ií]a|doctorado|licence|mast[eè]re|diplom|"
    r"bacharel|mestrado|laurea)\b\.?", re.I)
INSTITUTION_RE = re.compile(
    r"\b(university|college|institute|school|academy|universidad|universit[aäé]t?|"
    r"universit[eé]|polytechnic|politecnico|instituto|escuela|faculty|iit|mit|"
    r"hochschule|école|ecole)\b", re.I)
LOCATION_RE = re.compile(r"^[^\W\d_][\w .'’-]+,\s*[^\W\d_][\w .'’-]+$", re.U)
DEGREE_STOP = r"(?:\s+(?:at|from)\b|\s*[,|(–—]|\s+-\s|$)"


@dataclass
class ProposedFact:
    category: str
    value: dict
    confidence: float
    source_location: str | None
    key: str = ""
    status: str = "proposed"  # invariant: extraction never confirms

    def __post_init__(self) -> None:
        self.value = normalize_value(self.category, self.value)
        self.key = self.key or fact_key(self.category, self.value)
        self.confidence = max(0.0, min(1.0, round(self.confidence, 2)))
        self.status = "proposed"


@dataclass
class ExtractionResult:
    facts: list[ProposedFact] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm_head(t: str) -> str:
    t = t.strip().strip(":").strip()
    t = t.replace("&", " and ").replace("/", " ")
    t = re.sub(r"[^\w\sÀ-ɏ]", " ", t.lower())
    return " ".join(t.split())


def section_of(line: str) -> str | None:
    if not line or len(line) > 45 or BULLET_RE.match(line):
        return None
    if any(c.isdigit() for c in line) or "@" in line:
        return None
    return _HEAD_LOOKUP.get(_norm_head(line))


def split_sections(lines: list[Line]) -> tuple[list[Line], dict[str, list[Line]], list[str]]:
    header: list[Line] = []
    sections: dict[str, list[Line]] = {}
    unmapped: list[str] = []
    cur: str | None = None
    for ln in lines:
        s = section_of(ln.text)
        if s:
            cur = s
            sections.setdefault(cur, [])
            if s == "ignore":
                unmapped.append(ln.text)
            continue
        (header if cur is None else sections[cur]).append(ln)
    return header, sections, unmapped


def _is_bullet(t: str) -> bool:
    return bool(BULLET_RE.match(t))


def _strip_bullet(t: str) -> str:
    return BULLET_RE.sub("", t, count=1).strip()


# ----------------------------------------------------------------- contact
def _phone(text: str) -> str | None:
    for m in PHONE_RE.finditer(text):
        raw = m.group(1).strip()
        digits = re.sub(r"\D", "", raw)
        if not 8 <= len(digits) <= 15 or RANGE_RE.search(raw):
            continue
        if re.fullmatch(r"(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}", raw):
            continue
        return raw
    return None


def _classify_link(u: str) -> str:
    low = u.lower()
    for key in ("linkedin", "github", "gitlab", "kaggle", "orcid", "scholar.google",
                "medium", "twitter", "x.com"):
        if key in low:
            return key.replace(".google", "")
    return "website"


def extract_contact(doc: ParsedDocument, header: list[Line]) -> ProposedFact | None:
    head_lines = [ln for ln in (header or doc.lines[:12]) if ln.text][:15]
    head_text = "\n".join(ln.text for ln in head_lines)
    full = doc.text
    v: dict = {}
    em = EMAIL_RE.search(head_text) or EMAIL_RE.search(full)
    if em:
        v["email"] = em.group(0)
    ph = _phone(head_text) or _phone(full[:3000])
    if ph:
        v["phone"] = ph
    links: dict[str, str] = {}
    for u in URL_RE.findall(full) + [x for x in doc.links if x.startswith("http")]:
        u = u.rstrip(".,;")
        if EMAIL_RE.fullmatch(u):
            continue
        links.setdefault(_classify_link(u), u if u.lower().startswith("http") else "https://" + u)
    if links:
        v["links"] = links
    name_loc = None
    segs: list[tuple[str, Line]] = []
    for ln in head_lines:
        for seg in re.split(r"\s*[|•·●]\s*|\s{3,}", ln.text):
            if seg.strip():
                segs.append((seg.strip(), ln))
    for seg, ln in segs:
        if EMAIL_RE.search(seg) or URL_RE.search(seg) or _phone(seg):
            continue
        words = seg.split()
        if "full_name" not in v and 2 <= len(words) <= 4 and all(
                re.fullmatch(r"[^\W\d_][\w.'’-]*", w, re.U) for w in words) and not (
                _HEAD_LOOKUP.get(_norm_head(seg))) and not TITLE_WORDS.search(seg):
            v["full_name"] = seg
            name_loc = ln.loc
            continue
        if "location" not in v and LOCATION_RE.match(seg) and not TITLE_WORDS.search(seg):
            v["location"] = seg
            continue
        if "headline" not in v and "full_name" in v and TITLE_WORDS.search(seg) and \
                len(seg) <= 100:
            v["headline"] = seg
    if not v:
        return None
    conf = 0.4 + 0.15 * sum(k in v for k in ("full_name", "email", "phone"))
    return ProposedFact("contact", v, conf, name_loc or (head_lines[0].loc if head_lines
                                                         else None))


# ----------------------------------------------------------------- experience
def _split_header(text: str) -> list[str]:
    parts = re.split(r"\s+[|•·]\s+|\s+[–—-]\s+|\s{3,}|\s+@\s+|\s+at\s+"
                     r"|\s+en\s+|\s+bei\s+|\s+chez\s+|\t", text)
    out = []
    for p in parts:
        p = p.strip(" ,;|-–—")
        if p:
            out.append(p)
    return out


def _assign_header(parts: list[str]) -> dict:
    title = company = location = None
    rest: list[str] = []
    for p in parts:
        if title is None and TITLE_WORDS.search(p) and len(p.split()) <= 8:
            title = p
        elif location is None and LOCATION_RE.match(p) and not TITLE_WORDS.search(p) and \
                len(p.split()) <= 5:
            location = p
        elif p.lower() in ("remote", "hybrid", "on-site", "onsite"):
            location = location or p
        else:
            rest.append(p)
    if title is None and rest:
        # "Title, Company" with comma
        first = rest[0]
        if "," in first:
            a, b = first.split(",", 1)
            if TITLE_WORDS.search(a):
                title, rest[0] = a.strip(), b.strip()
    if title and "," in title:
        a, _, b = title.partition(",")
        if TITLE_WORDS.search(a) and b.strip() and not TITLE_WORDS.search(b):
            title = a.strip()
            rest.insert(0, b.strip())
    if rest:
        company = rest[0]
        if company and "," in company and location is None:
            c, _, loc = company.rpartition(",")
            if c and len(loc.split()) <= 3:
                company, location = c.strip(), loc.strip()
    if title is None and len(rest) > 1:
        title = rest[1]
    return {"company": company, "title": title, "location": location}


def _strip_range(text: str, m: re.Match) -> str:
    return (text[:m.start()] + " " + text[m.end():]).strip(" \t,;|()-–—")


def _plausible_header(t: str) -> bool:
    return bool(t) and not _is_bullet(t) and len(t) <= 100 and len(t.split()) <= 14 and \
        not t.rstrip().endswith((".", "!", ";"))


def extract_experience(lines: list[Line]) -> list[ProposedFact]:
    anchors = [i for i, ln in enumerate(lines) if RANGE_RE.search(ln.text)
               and not _is_bullet(ln.text)]
    facts: list[ProposedFact] = []
    for n, a in enumerate(anchors):
        ln = lines[a]
        m = RANGE_RE.search(ln.text)
        assert m
        head_parts = [_strip_range(ln.text, m)]
        # preceding header line(s) that belong to this entry
        lo = anchors[n - 1] + 1 if n else 0
        j = a - 1
        used = 0
        while j >= lo and used < 2 and _plausible_header(lines[j].text):
            head_parts.insert(0, lines[j].text)
            j -= 1
            used += 1
        # bullets that sit between previous anchor and the first header line are not ours
        end = anchors[n + 1] if n + 1 < len(anchors) else len(lines)
        body_end = end
        # trailing header lines of the next entry belong to the next entry
        k = end - 1
        taken = 0
        while n + 1 < len(anchors) and k > a and taken < 2 and \
                _plausible_header(lines[k].text) and not _is_bullet(lines[k].text):
            body_end = k
            k -= 1
            taken += 1
        bullets: list[str] = []
        for bl in lines[a + 1:body_end]:
            t = bl.text
            if not t:
                continue
            if _is_bullet(t):
                bullets.append(_strip_bullet(t))
            elif bullets and (not bullets[-1].endswith((".", "!", ";", ":")) or t[0].islower()):
                bullets[-1] += " " + t
            else:
                bullets.append(t)
        fields: dict = {}
        for p in head_parts:
            for k2, v2 in _assign_header(_split_header(p)).items():
                if v2 and not fields.get(k2):
                    fields[k2] = v2
        # single-line header with only one part but both lines present: re-run on joined parts
        if not (fields.get("company") and fields.get("title")) and len(head_parts) > 1:
            fields2 = _assign_header([x for p in head_parts for x in _split_header(p)])
            for k2, v2 in fields2.items():
                if v2 and not fields.get(k2):
                    fields[k2] = v2
        end_raw = m.group("end")
        value = {**fields, "start_date": m.group("start"),
                 "end_date": "Present" if normalize_date(end_raw) == "Present" else end_raw,
                 "bullets": bullets}
        score = 0.35 + 0.2 * bool(fields.get("company")) + 0.2 * bool(fields.get("title")) \
            + 0.1 * bool(bullets) + 0.05 * bool(normalize_date(m.group("start")))
        if not (fields.get("company") or fields.get("title")):
            continue
        facts.append(ProposedFact("experience", value, score, ln.loc))
    return facts


# ----------------------------------------------------------------- education
def extract_education(lines: list[Line]) -> list[ProposedFact]:
    facts: list[ProposedFact] = []
    cur: dict = {}
    loc: str | None = None

    def flush() -> None:
        nonlocal cur, loc
        if cur.get("institution") or cur.get("degree"):
            conf = 0.35 + 0.2 * bool(cur.get("institution")) + 0.2 * bool(cur.get("degree")) \
                + 0.1 * bool(cur.get("end_date"))
            facts.append(ProposedFact("education", cur, conf, loc))
        cur, loc = {}, None

    for ln in lines:
        t = ln.text
        if not t:
            continue
        if _is_bullet(t):
            continue
        rng = RANGE_RE.search(t)
        single = re.search(rf"\b((?:19|20)\d{{2}})\b", t)
        body = _strip_range(t, rng) if rng else t
        gm = re.search(r"(?:gpa|cgpa|grade|nota|note)\s*[:=]?\s*([\d.,]+(?:\s*/\s*[\d.]+)?%?)",
                       t, re.I)
        if gm:
            cur["grade"] = gm.group(1)
            body = re.sub(r"[\(\[]?(?:gpa|cgpa|grade|nota|note)\s*[:=]?\s*[\d.,/ ]+%?[\)\]]?",
                          "", body, flags=re.I).strip(" ,;|-–—")
        has_inst = bool(INSTITUTION_RE.search(body))
        has_deg = bool(DEGREE_RE.search(body))
        if has_inst or has_deg:
            if has_deg and cur.get("degree") and (not has_inst or cur.get("institution")):
                flush()
            if has_inst and cur.get("institution"):
                flush()
            loc = loc or ln.loc
        parts = _split_header(body) if (has_inst or has_deg) else []
        for p in parts:
            if INSTITUTION_RE.search(p) and not cur.get("institution") and not (
                    DEGREE_RE.search(p) and re.match(r"(?i)^(bachelor|master|doctor)", p)):
                cur["institution"] = p
            elif DEGREE_RE.search(p) and not cur.get("degree"):
                dm = re.match(r"(?i)^(.*?)(?:\s+(?:in|of|en|de)\s+(.+))?$", p)
                cur["degree"] = dm.group(1).strip() if dm and dm.group(2) else p
                if dm and dm.group(2):
                    cur["degree"] = p.split(" in ")[0] if " in " in p else p
                    cur["field"] = dm.group(2).strip()
                    if " in " not in p:
                        cur["degree"] = p
            elif not cur.get("field") and cur.get("degree") and not INSTITUTION_RE.search(p) \
                    and len(p.split()) <= 6 and not LOCATION_RE.match(p):
                cur["field"] = p
        if rng:
            cur["start_date"] = rng.group("start")
            cur["end_date"] = rng.group("end")
        elif single and (has_inst or has_deg or cur):
            cur["end_date"] = single.group(1)
            if not (has_inst or has_deg) and (cur.get("institution") or cur.get("degree")):
                pass
    flush()
    return facts


# ----------------------------------------------------------------- skills
def split_skill_items(s: str) -> list[str]:
    items: list[str] = []
    buf, depth = "", 0
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch in ",;|•·" and depth == 0:
            items.append(buf)
            buf = ""
        else:
            buf += ch
    items.append(buf)
    return [i.strip(" .\t") for i in items if i.strip(" .\t")]


def extract_skills(lines: list[Line]) -> list[ProposedFact]:
    facts: list[ProposedFact] = []
    seen: set[str] = set()
    for ln in lines:
        t = _strip_bullet(ln.text) if _is_bullet(ln.text) else ln.text
        if not t:
            continue
        cat = None
        m = re.match(r"^([^:]{2,40}):\s*(.+)$", t)
        if m and not t.lower().startswith(("http", "mailto")):
            cat, t = m.group(1).strip(), m.group(2)
        for item in split_skill_items(t):
            inner = re.match(r"^([^(\[]+)[(\[]([^)\]]+)[)\]]$", item)
            names = [item]
            if inner:
                names = [inner.group(1).strip()] + split_skill_items(inner.group(2))
            for name in names:
                if not name or len(name) > 40 or len(name.split()) > 5 or name.endswith("."):
                    continue
                k = name.lower()
                if k in seen:
                    continue
                seen.add(k)
                facts.append(ProposedFact("skill", {"name": name, "category": cat},
                                          0.8 if cat else 0.65, ln.loc))
    return facts


# ----------------------------------------------------------------- projects
def extract_projects(lines: list[Line]) -> list[ProposedFact]:
    facts: list[ProposedFact] = []
    cur: dict | None = None
    cur_loc = None
    prev_bullet = False

    def flush() -> None:
        nonlocal cur
        if cur and cur.get("name"):
            conf = 0.45 + 0.15 * bool(cur.get("bullets")) + 0.1 * bool(cur.get("technologies"))
            facts.append(ProposedFact("project", cur, conf, cur_loc))
        cur = None

    for ln in lines:
        t = ln.text
        if not t:
            prev_bullet = False
            continue
        if _is_bullet(t):
            if cur is None:
                cur, cur_loc = {"name": "Untitled project", "bullets": []}, ln.loc
            cur.setdefault("bullets", []).append(_strip_bullet(t))
            prev_bullet = True
            continue
        if cur is not None and prev_bullet and (t[0].islower() or
                                                not cur["bullets"][-1].endswith((".", "!"))):
            cur["bullets"][-1] += " " + t
            continue
        if _plausible_header(t) and (cur is None or cur.get("bullets") or cur.get("description")
                                     or True):
            flush()
            cur_loc = ln.loc
            url = URL_RE.search(t)
            body = URL_RE.sub("", t).strip(" |-–—")
            parts = re.split(r"\s+[|–—]\s+|:\s+|\s+-\s+", body, maxsplit=1)
            name = parts[0].strip()
            tech: list[str] = []
            pm = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", name)
            rest = parts[1] if len(parts) > 1 else ""
            if pm:
                name, rest = pm.group(1), pm.group(2) + ("," + rest if rest else "")
            if rest and len(rest) < 150 and "," in rest or (rest and len(rest.split()) <= 3):
                tech = split_skill_items(RANGE_RE.sub("", rest))
                rest = ""
            cur = {"name": name, "technologies": tech, "bullets": []}
            if url:
                cur["url"] = url.group(0)
            if rest:
                cur["description"] = rest
        elif cur is not None:
            cur["description"] = (cur.get("description", "") + " " + t).strip()
        prev_bullet = False
    flush()
    return facts


# ----------------------------------------------------------------- publications / certs
def extract_publications(lines: list[Line]) -> list[ProposedFact]:
    entries: list[tuple[str, str]] = []
    marker = re.compile(r"^\s*(?:\[\d+\]|\d+[.)])\s+")
    has_marks = any(_is_bullet(ln.text) or marker.match(ln.text) for ln in lines)
    buf: list[str] = []
    loc = None
    for ln in lines:
        t = ln.text
        if not t:
            continue
        starts = _is_bullet(t) or marker.match(t)
        if has_marks and starts and buf:
            entries.append((" ".join(buf), loc or ln.loc))
            buf = []
        if not buf:
            loc = ln.loc
        buf.append(marker.sub("", _strip_bullet(t) if _is_bullet(t) else t))
        if not has_marks and re.search(r"(?:19|20)\d{2}\)?\.?$", t):
            entries.append((" ".join(buf), loc))
            buf = []
    if buf:
        entries.append((" ".join(buf), loc or ""))
    facts = []
    for text, l in entries:
        year = re.findall(r"\b(?:19|20)\d{2}\b", text)
        url = URL_RE.search(text)
        q = re.search(r"[\"“]([^\"”]{8,})[\"”]", text)
        if q:
            title = q.group(1).strip(" ,.")
            venue = text[q.end():].strip(" ,.")
        else:
            title, venue = text, None
            segs = [s.strip() for s in re.split(r"\.\s+", text) if s.strip()]
            if len(segs) >= 2:
                title = segs[1] if len(segs[0].split()) <= 12 and "," in segs[0] else segs[0]
                venue = ". ".join(s for s in segs if s != title) or None
        if venue:
            venue = re.sub(r"\b(?:19|20)\d{2}\b", "", venue).strip(" ,.;()") or None
        facts.append(ProposedFact("publication", {
            "title": title, "venue": venue, "year": year[-1] if year else None,
            "url": url.group(0) if url else None}, 0.55 if q else 0.4, l))
    return facts


def extract_certifications(lines: list[Line]) -> list[ProposedFact]:
    facts = []
    for ln in lines:
        t = _strip_bullet(ln.text) if _is_bullet(ln.text) else ln.text
        if not t or len(t) > 200:
            continue
        url = URL_RE.search(t)
        t2 = URL_RE.sub("", t)
        d = re.search(DATE_PAT, t2, re.I)
        date = d.group(0) if d else None
        if d:
            t2 = (t2[:d.start()] + t2[d.end():])
        t2 = t2.strip(" ,;|()-–—")
        parts = re.split(r"\s+[|–—-]\s+|,\s+|\s+by\s+|\s+•\s+", t2, maxsplit=1)
        name = parts[0].strip(" ()")
        issuer = parts[1].strip(" ()") if len(parts) > 1 else None
        if name:
            facts.append(ProposedFact("certification", {
                "name": name, "issuer": issuer, "date": date,
                "url": url.group(0) if url else None}, 0.6 if issuer or date else 0.45, ln.loc))
    return facts


def extract_summary(lines: list[Line]) -> ProposedFact | None:
    text = " ".join(_strip_bullet(ln.text) for ln in lines if ln.text).strip()
    if len(text) < 20:
        return None
    return ProposedFact("summary", {"text": text}, 0.6, next((ln.loc for ln in lines
                                                              if ln.text), None))


# ----------------------------------------------------------------- driver
def extract(doc: ParsedDocument) -> ExtractionResult:
    res = ExtractionResult()
    header, sections, unmapped = split_sections(doc.lines)
    if not sections:
        res.warnings.append("No recognisable section headings; only contact details and "
                            "skills-like lists could be proposed. Add facts manually.")
    contact = extract_contact(doc, header)
    if contact:
        res.facts.append(contact)
    if "summary" in sections:
        s = extract_summary(sections["summary"])
        if s:
            res.facts.append(s)
    drivers = {"experience": extract_experience, "education": extract_education,
               "skills": extract_skills, "projects": extract_projects,
               "publications": extract_publications, "certifications": extract_certifications}
    for name, fn in drivers.items():
        if name in sections:
            found = fn(sections[name])
            if not found and any(ln.text for ln in sections[name]):
                res.warnings.append(f"Section '{name}' was found but nothing could be parsed "
                                    "from it.")
            res.facts.extend(found)
    if unmapped:
        res.warnings.append("Sections not mapped to profile data were skipped: "
                            + ", ".join(sorted(set(unmapped))[:6]))
    return res
