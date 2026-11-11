"""JobKeywordGenerator: search keywords from the candidate profile (LLM optional)."""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from app.services.llm import LLMUnavailable, get_llm, wrap_untrusted

log = logging.getLogger(__name__)

SKILL_ROLE_TEMPLATES = {
    "Python": "Python Developer", "Java": "Java Developer", "Node.js": "Node.js Developer",
    "React": "React Developer", "Go": "Golang Developer", "LangChain": "Generative AI Engineer",
    "RAG": "RAG Engineer", "LLM": "LLM Engineer", "Machine Learning": "Machine Learning Engineer",
    "Django": "Django Developer", "FastAPI": "Python Backend Engineer", "Spring Boot": "Java Spring Boot Developer",
    "AWS": "Cloud Engineer", "Kubernetes": "DevOps Engineer", "Data Science": "Data Scientist",
    "Apache Spark": "Data Engineer", "Flutter": "Flutter Developer", "React Native": "React Native Developer",
}


class KeywordOut(BaseModel):
    keywords: list[str] = Field(default_factory=list)


PROMPT = """Generate 8-12 short job-search keyword phrases (job titles a recruiter would post) for this candidate.
Base them strictly on the candidate's roles and skills. Prefer titles at their real seniority level.
Return JSON: {{"keywords": ["..."]}}

{data}
"""


def rule_keywords(roles: list[str], skills: list[str], limit: int = 10) -> list[str]:
    out: list[str] = []
    for r in roles:
        if r and r.lower() not in {o.lower() for o in out}:
            out.append(r)
    for s in skills:
        t = SKILL_ROLE_TEMPLATES.get(s)
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    if not out:
        out = ["Software Engineer", "Software Developer"]
    return out[:limit]


async def generate_keywords(profile_data: dict, preferences: dict, use_llm: bool = True) -> tuple[list[str], str]:
    roles = preferences.get("preferred_roles") or profile_data.get("job_roles") or []
    skills = preferences.get("preferred_technologies") or profile_data.get("skills") or []
    base = rule_keywords(roles, skills)
    llm = get_llm()
    if not (use_llm and llm.available):
        return base, "rules"
    summary = (f"Experience level: {profile_data.get('experience_level')}\n"
               f"Target roles: {', '.join(roles)}\nSkills: {', '.join(skills[:30])}")
    _, block = wrap_untrusted(summary, "profile", 3000)
    try:
        data = KeywordOut.model_validate(await llm.complete_json(PROMPT.format(data=block), max_tokens=400))
        merged = list(dict.fromkeys([*roles, *[k.strip() for k in data.keywords if 2 < len(k.strip()) < 60]]))
        return merged[:12] or base, "llm"
    except (LLMUnavailable, ValidationError) as e:
        log.warning("keyword LLM failed: %s", e)
        return base, "rules"
