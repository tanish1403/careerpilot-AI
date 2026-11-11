"""Interview practice. Questions are generic PRACTICE questions, never claimed to be real company questions.
Rubric mode is deterministic and offline: factual coverage (keyword rubric) is scored separately from
communication (length/structure/filler)."""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import InterviewFeedback, InterviewSession, Job, JobRequirement

KINDS = ("technical", "coding", "project", "system_design", "behavioral")
LABEL = "practice question"

# id, text, topic, expected concept groups (each group: any-of synonyms)
BANK: dict[str, list[dict]] = {
 "technical": [
  {"id": "t1", "topic": "databases", "text": "What is a database index and what is the trade-off of adding one?",
   "expect": [["lookup", "faster", "speed", "search"], ["write", "insert", "update"], ["space", "storage", "memory", "disk"]]},
  {"id": "t2", "topic": "http", "text": "Explain the difference between PUT and PATCH, and what idempotent means.",
   "expect": [["replace", "whole", "entire", "full"], ["partial", "subset", "some fields"], ["same result", "repeat", "multiple times", "idempotent"]]},
  {"id": "t3", "topic": "concurrency", "text": "What is a race condition and how can you prevent one?",
   "expect": [["shared", "concurrent", "simultaneous", "threads"], ["lock", "mutex", "atomic", "transaction", "synchron"]]},
  {"id": "t4", "topic": "testing", "text": "How do unit tests differ from integration tests, and when would you use each?",
   "expect": [["isolat", "single", "unit", "function"], ["integration", "together", "components", "database"], ["mock", "fast", "slow"]]}],
 "coding": [
  {"id": "c1", "topic": "hashing", "text": "Describe how you would find two numbers in an array that sum to a target.",
   "expect": [["hash", "map", "dictionary", "set"], ["o(n)", "linear", "one pass"], ["complement", "difference", "target minus", "target -"]]},
  {"id": "c2", "topic": "trees", "text": "How would you check whether a binary tree is a valid binary search tree?",
   "expect": [["in-order", "inorder", "bounds", "min", "max", "range"], ["recurs", "dfs", "traversal"]]},
  {"id": "c3", "topic": "complexity", "text": "Explain time and space complexity of binary search and why it needs sorted input.",
   "expect": [["log", "o(log n)"], ["sorted", "order"], ["half", "halv", "discard"]]}],
 "project": [
  {"id": "p1", "topic": "project", "text": "Walk me through a project you are proud of: the problem, your role and the outcome.",
   "expect": []},
  {"id": "p2", "topic": "project", "text": "What was the hardest technical decision in that project and what alternatives did you reject?",
   "expect": []},
  {"id": "p3", "topic": "project", "text": "What would you change if you rebuilt it today?", "expect": []}],
 "system_design": [
  {"id": "s1", "topic": "system design", "text": "Design a URL shortener. What are the core components and how does it scale?",
   "expect": [["hash", "id", "encode", "base62", "counter"], ["database", "store", "key-value"], ["cache", "cdn"], ["scale", "shard", "replica", "load balanc"]]},
  {"id": "s2", "topic": "system design", "text": "How would you design a rate limiter for a public API?",
   "expect": [["token bucket", "leaky", "sliding window", "fixed window"], ["redis", "counter", "store", "distributed"], ["429", "reject", "throttle"]]},
  {"id": "s3", "topic": "distributed systems", "text": "Explain the CAP theorem with an example trade-off.",
   "expect": [["consisten"], ["availab"], ["partition"]]}],
 "behavioral": [
  {"id": "b1", "topic": "behavioral", "text": "Tell me about a time you disagreed with a teammate. What happened?", "expect": []},
  {"id": "b2", "topic": "behavioral", "text": "Describe a time you failed or missed a deadline and what you learned.", "expect": []},
  {"id": "b3", "topic": "behavioral", "text": "Tell me about a time you had to learn something quickly.", "expect": []}],
}
FILLERS = ("um", "uh", "like", "basically", "you know", "actually", "sort of", "kind of")
STAR = {"situation": ("situation", "context", "when i", "at the time"), "task": ("task", "goal", "responsib", "needed to"),
        "action": ("i decided", "i built", "i led", "i wrote", "i did", "i implemented", "i proposed", "action"),
        "result": ("result", "outcome", "as a consequence", "improved", "reduced", "increased", "learned")}


def questions_for(db: Session, s: InterviewSession) -> list[dict]:
    qs = [dict(q) for q in BANK[s.kind]]
    if s.job_id and s.kind in ("technical", "coding"):
        reqs = db.query(JobRequirement).filter(JobRequirement.job_id == s.job_id, JobRequirement.kind == "skill",
                                               JobRequirement.deleted_at.is_(None)).order_by(JobRequirement.text).all()
        for i, r in enumerate(reqs[:2]):
            qs.append({"id": f"j{i + 1}", "topic": r.normalized or r.text,
                       "text": f"The role mentions '{r.normalized or r.text}'. Describe how you have used it and its main pitfalls.",
                       "expect": []})   # no expected concepts: factual correctness cannot be assessed
    for q in qs:
        q["label"] = LABEL
    return qs


def public_q(q: dict | None) -> dict | None:
    return None if q is None else {"id": q["id"], "text": q["text"], "topic": q["topic"], "label": LABEL,
                                   "verified_company_question": False}


def create_session(db: Session, kind: str, job_id: str | None, target_role: str | None) -> InterviewSession:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if job_id:
        job = db.get(Job, job_id)
        if job is None or job.deleted_at is not None:
            raise LookupError("job not found")
        target_role = target_role or job.title
    s = InterviewSession(kind=kind, job_id=job_id, target_role=target_role, transcript=[], status="active")
    db.add(s)
    db.flush()
    first = questions_for(db, s)[0]
    s.transcript = [{"role": "interviewer", "question_id": first["id"], "text": first["text"], "label": LABEL}]
    db.flush()
    return s


def _words(t: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", t)


def assess_factual(q: dict, text: str) -> dict:
    if not q["expect"]:
        return {"assessed": False, "score": None, "covered": [], "missing": [],
                "note": "No objective rubric for this question; self-review recommended."}
    low = text.lower()
    covered, missing = [], []
    for group in q["expect"]:
        (covered if any(k in low for k in group) else missing).append(group[0])
    return {"assessed": True, "score": round(len(covered) / len(q["expect"]), 2), "covered": covered, "missing": missing}


def assess_communication(kind: str, text: str) -> dict:
    words = _words(text)
    n = len(words)
    low = text.lower()
    filler = sum(len(re.findall(rf"\b{re.escape(f)}\b", low)) for f in FILLERS)
    notes, score = [], 1.0
    if n < 25:
        notes.append("Answer is very short; add reasoning and an example."); score -= 0.4
    elif n > 350:
        notes.append("Answer is long; aim for a tighter structure."); score -= 0.2
    if n and filler / n > 0.05:
        notes.append("Frequent filler words."); score -= 0.2
    structure = None
    if kind in ("behavioral", "project"):
        hit = [k for k, ws in STAR.items() if any(w in low for w in ws)]
        structure = {"star_elements_present": hit, "star_elements_missing": [k for k in STAR if k not in hit]}
        if len(hit) < 3:
            notes.append("Use situation/task/action/result structure."); score -= 0.2
    return {"score": round(max(score, 0.0), 2), "word_count": n, "filler_count": filler, "structure": structure,
            "notes": notes or ["Clear and reasonably structured."]}


def answer(db: Session, s: InterviewSession, text: str) -> dict:
    if s.status != "active":
        raise ValueError("session is finished")
    qs = questions_for(db, s)
    answered = sum(1 for t in s.transcript if t["role"] == "candidate")
    if answered >= len(qs):
        raise ValueError("no more questions; finish the session")
    q = qs[answered]
    f, c = assess_factual(q, text), assess_communication(s.kind, text)
    tr = list(s.transcript)
    tr.append({"role": "candidate", "question_id": q["id"], "text": text, "factual": f, "communication": c,
               "at": utcnow().isoformat()})
    nxt = qs[answered + 1] if answered + 1 < len(qs) else None
    if nxt:
        tr.append({"role": "interviewer", "question_id": nxt["id"], "text": nxt["text"], "label": LABEL})
    s.transcript = tr
    db.flush()
    return {"next_question": public_q(nxt), "done": nxt is None,
            "running_notes": [{"question_id": t["question_id"], "factual": t["factual"],
                               "communication": t["communication"]} for t in tr if t["role"] == "candidate"]}


def build_feedback(db: Session, s: InterviewSession) -> dict:
    qmap = {q["id"]: q for q in questions_for(db, s)}
    ans = [t for t in s.transcript if t["role"] == "candidate"]
    per_q, rev = [], []
    for t in ans:
        f = t["factual"]
        per_q.append({"question_id": t["question_id"], "topic": qmap[t["question_id"]]["topic"], **f})
        if f.get("assessed") and f["missing"]:
            rev.append({"topic": qmap[t["question_id"]]["topic"],
                        "task": "Revise and re-answer: " + qmap[t["question_id"]]["text"],
                        "concepts_missing": f["missing"], "reason": "Rubric concepts not mentioned in your answer."})
        elif not f.get("assessed"):
            rev.append({"topic": qmap[t["question_id"]]["topic"], "task": "Self-review this answer against your notes/evidence.",
                        "concepts_missing": [], "reason": "No objective rubric available."})
    scored = [p["score"] for p in per_q if p.get("assessed")]
    factual = {"mode": "rubric", "overall": round(sum(scored) / len(scored), 2) if scored else None,
               "assessed_count": len(scored), "per_question": per_q,
               "note": "Keyword-rubric coverage on practice questions; not a guarantee of correctness."}
    cs = [t["communication"] for t in ans]
    comm = {"overall": round(sum(c["score"] for c in cs) / len(cs), 2) if cs else None,
            "avg_word_count": round(sum(c["word_count"] for c in cs) / len(cs), 1) if cs else 0,
            "notes": sorted({n for c in cs for n in c["notes"]})}
    return {"factual_correctness": factual, "communication": comm, "revision_tasks": rev}


async def llm_review(db: Session, s: InterviewSession) -> dict:
    """Optional: gateway-based review, clearly labelled model-generated. Lazy import; never raises."""
    try:
        from ..core.untrusted import wrap_untrusted
        from ..provider_gateway import deps
        from ..provider_gateway.interface import GenerateRequest, TaskPolicy
        gw = deps.make_gateway(db)
        body = "\n\n".join(f"Q: {t['text']}" if t["role"] == "interviewer" else f"A: {t['text']}" for t in s.transcript)
        schema = {"type": "object", "properties": {"factual_issues": {"type": "array", "items": {"type": "string"}},
                                                    "communication_tips": {"type": "array", "items": {"type": "string"}}},
                  "required": ["factual_issues", "communication_tips"]}
        res = await gw.generate(GenerateRequest(messages=[
            {"role": "system", "content": "Review a mock interview. Report factual errors separately from communication tips. JSON only."},
            {"role": "user", "content": wrap_untrusted(body, "interview_transcript")}]),
            TaskPolicy(task_type="interview_review", agent="interview", json_schema=schema, sensitive_document=True))
        return {"source": "model-generated", "model": res.model_id, **(res.parsed or {})}
    except Exception as e:  # noqa: BLE001
        return {"source": "unavailable", "error": f"{type(e).__name__}: {str(e)[:200]}"}


def finish(db: Session, s: InterviewSession, use_llm: bool = False) -> InterviewFeedback:
    import asyncio
    if s.status == "finished":
        return db.query(InterviewFeedback).filter(InterviewFeedback.session_id == s.id).first()
    fb = build_feedback(db, s)
    if use_llm:
        fb["factual_correctness"]["llm_review"] = asyncio.run(llm_review(db, s))
    row = InterviewFeedback(session_id=s.id, **fb)
    db.add(row)
    s.status = "finished"
    db.flush()
    return row


def feedback_dict(fb: InterviewFeedback | None) -> dict | None:
    return None if fb is None else {"factual_correctness": fb.factual_correctness, "communication": fb.communication,
                                    "revision_tasks": fb.revision_tasks}


def export_markdown(db: Session, s: InterviewSession) -> str:
    fb = db.query(InterviewFeedback).filter(InterviewFeedback.session_id == s.id).first()
    L = [f"# Interview practice: {s.kind}", "", f"- Target role: {s.target_role or 'n/a'}", f"- Status: {s.status}",
         "- Questions are generic practice questions, not verified company questions.", "", "## Transcript"]
    for t in s.transcript:
        L.append(f"**{'Interviewer' if t['role'] == 'interviewer' else 'You'}:** {t['text']}")
        L.append("")
    if fb:
        f, c = fb.factual_correctness, fb.communication
        L += ["## Factual correctness", f"- Overall rubric coverage: {f.get('overall')}", "",
              "## Communication", f"- Overall: {c.get('overall')}"] + [f"- {n}" for n in c.get("notes", [])]
        L += ["", "## Revision tasks"] + [f"- [{r['topic']}] {r['task']}" for r in fb.revision_tasks]
    return "\n".join(L) + "\n"
