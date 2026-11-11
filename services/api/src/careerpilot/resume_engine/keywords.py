"""Keyword utilities for deterministic tailoring and the rewording validator."""
from __future__ import annotations

import re

STOP = set("""a an and are as at be been being but by can could do does for from had has have he her
his how i if in into is it its may might more most must no not of on or our out over per she should
so some such than that the their them then there these they this those to too under up us was we
were what when where which while who will with would you your about above across after again all
also any because before between both each few other own same very just etc able ability strong
experience experienced work working years year plus including include within using use used
role team company looking join candidate position job responsibilities requirements required
preferred qualifications skills knowledge understanding excellent good great new ideal
well-versed familiarity familiar proven demonstrated opportunity""".split())

TECH_TERMS = set("""python java javascript typescript go golang rust c++ c# c ruby php swift kotlin scala
r matlab sql nosql postgresql postgres mysql sqlite mongodb redis cassandra dynamodb elasticsearch
kafka rabbitmq spark hadoop airflow dbt snowflake bigquery redshift tableau powerbi react angular
vue svelte node.js nodejs express django flask fastapi spring rails graphql rest grpc docker
kubernetes terraform ansible jenkins git github gitlab ci/cd aws azure gcp linux bash unix
tensorflow pytorch keras scikit-learn pandas numpy opencv nlp llm llms html css sass webpack
junit pytest selenium cypress jira agile scrum microservices devops sre prometheus grafana
nginx oauth sso openapi hadoop hive flink beam kubernetes helm istio redis machine-learning
""".split())
_TECH_PHRASES = ("machine learning", "deep learning", "data science", "computer vision",
                 "natural language processing", "continuous integration", "distributed systems",
                 "data engineering", "unit testing")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#./-]*[a-z0-9+#]|[a-z0-9]")


def stem(t: str) -> str:
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def tokens(text: str) -> list[str]:
    return [stem(t.strip(".-/")) for t in _TOKEN.findall((text or "").lower()) if t.strip(".-/")]


def terms(text: str) -> set[str]:
    """Unigrams (non-stopword) and adjacent bigrams."""
    toks = tokens(text)
    out = {t for t in toks if t not in STOP and len(t) > 1}
    for a, b in zip(toks, toks[1:]):
        if a not in STOP and b not in STOP and len(a) > 1 and len(b) > 1:
            out.add(f"{a} {b}")
    return out


def phrase_in(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    pat = r"(?<![\w+#])" + re.escape(phrase.lower()) + r"(?![\w+#])"
    return re.search(pat, (text or "").lower()) is not None


def jd_tech(jd: str) -> list[str]:
    low = (jd or "").lower()
    found = [t for t in sorted(TECH_TERMS) if phrase_in(low, t)]
    found += [p for p in _TECH_PHRASES if p in low]
    return found


def score_text(text: str, jd_terms: set[str], skill_names: list[str], jd_text: str) -> float:
    t = terms(text)
    s = 0.0
    for x in t & jd_terms:
        s += 2.0 if " " in x else 1.0
    low = (text or "").lower()
    for name in skill_names:
        if phrase_in(low, name) and phrase_in(jd_text, name):
            s += 3.0
    return s
