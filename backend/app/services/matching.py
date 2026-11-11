"""JobMatchingService.

Deterministic, transparent 0-100 score (default weights, user-configurable):
  technical skills 35 | relevant experience 25 | role compatibility 20 |
  education 10 | location & work preference 10
LLM is used only for the optional narrative explanation of a match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from app.services import skills_taxonomy as tax
from app.services.llm import LLMUnavailable, get_llm, wrap_untrusted
from app.services.text_utils import education_rank, normalize_location, normalize_title, required_education

DEFAULT_WEIGHTS = {"skills": 35, "experience": 25, "role": 20, "education": 10, "location": 10}

ROLE_FAMILIES = {
    "backend": ["backend", "back end", "server", "api", "python developer", "java developer", "node", "golang", "platform engineer"],
    "frontend": ["frontend", "front end", "ui engineer", "react developer", "web developer", "angular"],
    "fullstack": ["full stack", "fullstack", "full-stack"],
    "ai": ["ai engineer", "machine learning", "ml engineer", "genai", "generative ai", "llm", "applied scientist",
           "nlp", "rag", "ai developer", "ai/ml", "ai ml", "research engineer", "applied ai", "agent"],
    "data": ["data engineer", "data scientist", "analytics engineer", "data analyst", "etl", "big data"],
    "devops": ["devops", "sre", "site reliability", "infrastructure", "cloud engineer", "platform engineer"],
    "mobile": ["android", "ios", "mobile", "flutter", "react native"],
    "qa": ["qa", "quality", "test", "sdet", "automation engineer"],
    "support": ["support engineer", "technical support", "customer support", "customer success", "solutions engineer",
                "sales engineer", "pre sales", "presales", "implementation engineer", "it systems", "helpdesk", "help desk"],
    "general": ["software engineer", "software developer", "sde", "programmer", "developer", "engineer"],
}
ADJACENT = {
    ("backend", "fullstack"), ("frontend", "fullstack"), ("backend", "ai"), ("backend", "data"),
    ("ai", "data"), ("backend", "devops"), ("backend", "general"), ("fullstack", "general"),
    ("frontend", "general"), ("ai", "general"), ("data", "general"), ("mobile", "general"),
}


def families(title: str) -> set[str]:
    t = f" {normalize_title(title)} "
    out = {f for f, kws in ROLE_FAMILIES.items() if f != "general" and any(k in t for k in kws)}
    if not out and any(k in t for k in ROLE_FAMILIES["general"]):
        out.add("general")
    return out


@dataclass
class CandidateView:
    skills: list[str]
    roles: list[str]
    professional_months: int
    internship_months: int
    relevant_months: int
    education_level: str | None
    preferences: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_years(self) -> float:
        # Internships count at 50% toward professional-experience requirements (shown in UI).
        return round((self.professional_months + 0.5 * self.internship_months) / 12, 1)

    @classmethod
    def from_profile(cls, profile) -> "CandidateView":
        d = profile.data or {}
        skills = [s.canonical for s in profile.skills] or d.get("skills", [])
        prefs = profile.preferences or {}
        roles = prefs.get("preferred_roles") or d.get("job_roles", [])
        return cls(
            skills=skills, roles=roles,
            professional_months=profile.professional_experience_months or 0,
            internship_months=profile.internship_experience_months or 0,
            relevant_months=profile.relevant_experience_months or 0,
            education_level=profile.education_level, preferences=prefs,
        )


@dataclass
class MatchResult:
    score: float
    breakdown: dict[str, Any]
    matched_skills: list[str]
    missing_skills: list[str]
    experience_fit: str
    explanation: str
    gaps: list[str]


def _skills_component(cand: set[str], job_skills: list[str], title: str) -> tuple[float, list[str], list[str], str]:
    if not job_skills:
        return 0.5, [], [], "Job description lists no recognisable technical skills; neutral score applied."
    title_sk = {s.canonical for s in tax.extract_skills(title)}
    total = matched_w = 0.0
    matched, missing = [], []
    for s in job_skills:
        w = tax.weight_of(s) * (1.5 if s in title_sk else 1.0)
        total += w
        if s in cand:
            matched_w += w
            matched.append(s)
        else:
            missing.append(s)
    ratio = matched_w / total if total else 0
    # jobs listing many skills rarely expect all of them
    if len(job_skills) > 8:
        ratio = min(1.0, ratio * 1.15)
    # little evidence (1-3 recognised skills) pulls the score toward neutral
    evidence = min(1.0, len(job_skills) / 4)
    ratio = evidence * ratio + (1 - evidence) * 0.5
    note = f"{len(matched)}/{len(job_skills)} required skills matched (weighted {ratio:.0%})."
    return ratio, matched, missing, note


def _experience_component(c: CandidateView, mn: float | None, mx: float | None) -> tuple[float, str, list[str]]:
    yrs = c.effective_years
    pro = round(c.professional_months / 12, 1)
    desc = f"You: {pro:g} yrs professional + {round(c.internship_months / 12, 1):g} yrs internships (effective {yrs:g} yrs)"
    if mn is None and mx is None:
        return 0.7, f"Experience requirement not specified. {desc}.", []
    lo = mn or 0
    req = f"{lo:g}–{mx:g} yrs" if mx is not None else f"{lo:g}+ yrs"
    gaps = []
    if yrs >= lo and (mx is None or yrs <= mx + 2):
        return 1.0, f"Meets requirement ({req}). {desc}.", gaps
    if yrs < lo:
        gap = lo - yrs
        gaps.append(f"Requires {req}; you have about {yrs:g} effective years.")
        score = 0.75 if gap <= 1 else 0.45 if gap <= 2 else 0.2 if gap <= 4 else 0.05
        return score, f"Below requirement ({req}) by ~{gap:g} yrs. {desc}.", gaps
    return 0.6, f"You exceed the range ({req}); role may be junior for you. {desc}.", gaps


def _role_component(c: CandidateView, title: str) -> tuple[float, str]:
    if not c.roles:
        return 0.5, "No target roles set."
    nt = normalize_title(title)
    best, best_role = 0.0, None
    for r in c.roles:
        s = fuzz.token_set_ratio(normalize_title(r), nt) / 100
        if s > best:
            best, best_role = s, r
    jf = families(title)
    cf = set().union(*(families(r) for r in c.roles)) if c.roles else set()
    fam = 0.0
    if jf & cf:
        fam = 0.9
    elif any((a, b) in ADJACENT or (b, a) in ADJACENT for a in jf for b in cf):
        fam = 0.65
    elif "general" in jf:
        fam = 0.6
    score = max(best if best >= 0.75 else best * 0.8, fam)
    if "support" in jf and "support" not in cf:
        score = min(score, 0.35)
    if re.search(r"\b(manager|director|head of|vp|principal|staff)\b", nt) and not any(
            re.search(r"\b(manager|director|head|principal|staff)\b", r.lower()) for r in c.roles):
        score *= 0.4
    return min(score, 1.0), f"Closest target role: {best_role} (title similarity {best:.0%}; role family {'match' if fam >= 0.9 else 'adjacent' if fam >= 0.6 else 'different'})."


def _education_component(c: CandidateView, description: str) -> tuple[float, str, list[str]]:
    req = required_education(description)
    if not req:
        return 1.0, "No specific degree requirement found.", []
    have = education_rank(c.education_level)
    need = education_rank(req)
    if have >= need:
        return 1.0, f"Meets education requirement ({req}).", []
    if have == 0:
        return 0.6, f"Job mentions a {req} degree; your education level could not be verified.", []
    return 0.4, f"Job asks for {req}; your highest level is {c.education_level}.", [f"Education: job mentions {req}."]


def _location_component(c: CandidateView, job_location: str | None, work_mode: str) -> tuple[float, str, list[str]]:
    p = c.preferences
    pref_mode = p.get("remote_preference", "any")
    pref_locs = [normalize_location(l) for l in p.get("preferred_locations") or [] if l]
    countries = [x.lower() for x in p.get("countries") or []]
    loc = normalize_location(job_location)
    gaps = []
    mode_score = 1.0
    if pref_mode != "any" and work_mode != "unknown" and work_mode != pref_mode:
        mode_score = 0.6 if {pref_mode, work_mode} == {"remote", "hybrid"} else 0.3
        gaps.append(f"Work mode is {work_mode}; you prefer {pref_mode}.")
    if work_mode == "remote":
        restricted = re.search(r"\b(us|usa|united states|uk|canada|europe|eu|emea|latam|americas)\b( only)?", loc or "")
        if restricted and countries and not any(cn in (loc or "") for cn in countries):
            gaps.append(f"Remote role may be restricted to {restricted.group(0).upper()}.")
            return 0.5 * mode_score, "Remote, possibly region-restricted.", gaps
        return mode_score, "Remote role.", gaps
    if not pref_locs and not countries:
        return 0.8 * mode_score, "No location preference set.", gaps
    if loc and any(pl and (pl in loc or loc.split(",")[0] in pl) for pl in pref_locs):
        return mode_score, "In a preferred location.", gaps
    if loc and any(cn in loc for cn in countries):
        return 0.8 * mode_score, "In a preferred country.", gaps
    if not loc:
        return 0.6 * mode_score, "Location not specified.", gaps
    gaps.append(f"Location {job_location} is outside your preferred locations.")
    return 0.3 * mode_score, "Outside preferred locations.", gaps


def score_job(c: CandidateView, *, title: str, description: str, job_skills: list[str],
              exp_min: float | None, exp_max: float | None, location: str | None, work_mode: str,
              weights: dict[str, float] | None = None) -> MatchResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    total_w = sum(w.values()) or 1
    cand = set(c.skills)
    sk, matched, missing, sk_note = _skills_component(cand, job_skills, title)
    ex, ex_note, ex_gaps = _experience_component(c, exp_min, exp_max)
    ro, ro_note = _role_component(c, title)
    ed, ed_note, ed_gaps = _education_component(c, description)
    lo, lo_note, lo_gaps = _location_component(c, location, work_mode)
    parts = {"skills": sk, "experience": ex, "role": ro, "education": ed, "location": lo}
    score = sum(parts[k] * w[k] for k in parts) / total_w * 100
    # hard cap: a job needing far more experience can never be a "top" match
    if ex <= 0.05:
        score = min(score, 45)
    breakdown = {
        k: {"score": round(parts[k] * 100), "weight": w[k], "points": round(parts[k] * w[k] / total_w * 100, 1),
            "note": n}
        for k, n in zip(parts, [sk_note, ex_note, ro_note, ed_note, lo_note])
    }
    gaps = ex_gaps + ed_gaps + lo_gaps
    if missing:
        key_missing = [m for m in missing if tax.weight_of(m) >= 1][:5]
        if key_missing:
            gaps.append("Skills to highlight or learn: " + ", ".join(key_missing))
    why = []
    if matched:
        why.append(f"You have {len(matched)} of the {len(job_skills)} technologies mentioned ({', '.join(matched[:6])}).")
    if ro >= 0.75:
        why.append("The role closely matches your target roles.")
    if ex >= 1.0:
        why.append("Your experience fits the stated requirement.")
    if not why:
        why.append("Partial overlap with your profile.")
    return MatchResult(
        score=round(score, 1), breakdown=breakdown, matched_skills=matched, missing_skills=missing,
        experience_fit=ex_note.split(". You:")[0], explanation=" ".join(why), gaps=gaps,
    )


EXPLAIN_PROMPT = """Write a short, honest assessment (max 120 words) of how well this candidate fits this job.
Mention the strongest overlaps, real eligibility gaps, and one concrete tip for the application.
Only use facts from the two data blocks. Return JSON: {{"assessment": "...", "tips": ["..."]}}

Candidate profile (data):
{cand}

Job posting (data):
{job}
"""


async def llm_explain(candidate_summary: str, job_text: str) -> dict | None:
    llm = get_llm()
    if not llm.available:
        return None
    _, cand = wrap_untrusted(candidate_summary, "candidate", 4000)
    _, job = wrap_untrusted(job_text, "job", 8000)
    try:
        return await llm.complete_json(EXPLAIN_PROMPT.format(cand=cand, job=job), max_tokens=600)
    except LLMUnavailable:
        return None
