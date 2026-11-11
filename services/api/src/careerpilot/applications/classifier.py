"""Question classifier. Decides whether an application question may be answered from confirmed
profile facts or must be escalated to the user. Sensitive and unmatched questions are NEVER guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_I = re.IGNORECASE

# Sensitive categories: always escalated, never auto-answered, never auto-filled.
SENSITIVE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("work_authorization", re.compile(
        r"(authori[sz]ed to work|work authori[sz]ation|legally (authori[sz]ed|eligible|permitted)|"
        r"right to work|eligible to work|work permit|\bvisa\b|sponsorship|\bsponsor\b|"
        r"citizen(ship)?\b|immigration|permanent resident|green card|employment eligibility)", _I)),
    ("demographic", re.compile(
        r"(\bgender\b|\bsex\b|\brace\b|racial|ethnic|ethnicity|hispanic|latino|latina|"
        r"sexual orientation|transgender|lgbt|pronouns?|\bveteran\b|military (status|service)|"
        r"marital|\bage\b|date of birth|birth ?date|\bdob\b|at least 18|over 18|older than 18|"
        r"religio|national origin|demographic|self[- ]identif)", _I)),
    ("disability", re.compile(
        r"(disabilit|disabled|reasonable accommodation|accommodations?\b|medical condition|"
        r"chronic (illness|condition)|health condition|neurodiver)", _I)),
    ("legal", re.compile(
        r"(criminal|convict|felony|misdemeanou?r|\barrest|lawsuit|litigation|non-?compete|"
        r"restrictive covenant|under oath|perjury|legal (action|proceeding|matter|issue)s?|"
        r"conflict of interest|previously (been )?terminated|fired from)", _I)),
    ("background_check", re.compile(
        r"(background (check|screen|investigation|verification)|drug (test|screen)|credit check|"
        r"reference check|security clearance|clearance level|fingerprint)", _I)),
    ("consent", re.compile(
        r"(\bconsent\b|\bagree\b|\bagreement\b|acknowledg|privacy (policy|notice)|"
        r"terms (and|&) conditions|terms of (use|service)|\bgdpr\b|data (processing|retention)|"
        r"retain my (data|information)|\bcertify\b|\bi authori[sz]e\b|opt[- ]?in|"
        r"text messages?|\bsms\b|e-?sign|electronic signature|\bsignature\b|talent (community|pool))",
        _I)),
    ("identifier", re.compile(
        r"(social security|\bssn\b|national (id|insurance)|passport|driver'?s? licen[sc]e|"
        r"tax (id|identification)|bank (account|details)|\biban\b|aadhaar|\bpan card\b)", _I)),
]

# Topics that CAN be answered from confirmed facts.
TOPIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("first_name", re.compile(r"^(legal )?(first|given) name|^forename", _I)),
    ("last_name", re.compile(r"^(legal )?(last|family|sur) ?name", _I)),
    ("full_name", re.compile(r"^(your )?(full |legal |preferred )?name\b|^full legal name", _I)),
    ("email", re.compile(r"e-?mail", _I)),
    ("phone", re.compile(r"\b(phone|mobile|telephone|cell)\b", _I)),
    ("linkedin", re.compile(r"linkedin", _I)),
    ("github", re.compile(r"github", _I)),
    ("website", re.compile(r"\b(website|portfolio|personal (site|url)|homepage)\b", _I)),
    ("location", re.compile(
        r"(current location|\blocation\b|\bcity\b|where are you (based|located)|"
        r"city (and|&) (state|country)|location \(city\))", _I)),
    ("current_company", re.compile(
        r"(current|present|most recent) (company|employer|organi[sz]ation)|^company$|^employer$", _I)),
    ("current_title", re.compile(
        r"(current|present|most recent) (job )?(title|role|position)|^job title$", _I)),
    ("school", re.compile(r"\b(school|university|college|institution)\b", _I)),
    ("degree", re.compile(r"\bdegree\b", _I)),
    ("headline", re.compile(r"\bheadline\b", _I)),
]

# Escalated but not "sensitive": need the user's own words / decision.
NEEDS_USER_HINTS = re.compile(
    r"(salary|compensation|expected pay|pay expectation|notice period|start date|"
    r"available to start|relocat|how did you hear|why (do you|are you|this)|cover letter|"
    r"tell us about|describe|additional information)", _I)


@dataclass(frozen=True)
class Classification:
    category: str            # a sensitive category | "profile" | "needs_user"
    sensitive: bool
    topic: str | None = None  # profile topic when answerable from confirmed facts

    @property
    def answerable(self) -> bool:
        return self.topic is not None and not self.sensitive


def normalize_question(q: str) -> str:
    q = re.sub(r"\(\s*required\s*\)|\*|✱", " ", q or "", flags=_I)
    return " ".join(q.split()).strip(" :?").lower()


def classify_question(question: str) -> Classification:
    q = " ".join((question or "").split())
    for cat, pat in SENSITIVE_RULES:
        if pat.search(q):
            return Classification(cat, True)
    clean = normalize_question(q)
    for topic, pat in TOPIC_RULES:
        if pat.search(clean):
            return Classification("profile", False, topic)
    if NEEDS_USER_HINTS.search(q):
        return Classification("needs_user", False)
    return Classification("needs_user", False)
