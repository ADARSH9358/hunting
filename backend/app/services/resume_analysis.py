"""ResumeAnalysisService: turns resume text into a structured, verified profile.

Two layers:
1. Deterministic rules (always run): contact info, sections, date ranges,
   taxonomy skills, education level. Works with no API keys.
2. LLM extraction (if configured): richer structure. Every LLM claim is
   verified against the resume text; unverifiable skills/companies are dropped,
   so the profile never contains invented experience or skills.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.services import skills_taxonomy as tax
from app.services.llm import LLMUnavailable, get_llm, wrap_untrusted
from app.services.text_utils import (
    DateRange,
    detect_education_level,
    experience_level,
    find_date_ranges,
    merge_months,
    parse_date_string,
)

log = logging.getLogger(__name__)

SECTION_ALIASES = {
    "experience": r"(work|professional|employment|industry|relevant)?\s*(experience|history|employment)",
    "internships": r"internships?(\s+experience)?",
    "education": r"education(al)?(\s+(background|qualifications?|details))?|academics?|academic\s+qualifications?",
    "projects": r"(academic\s+|personal\s+|key\s+|technical\s+)?projects?",
    "skills": r"(technical\s+|key\s+|core\s+)?(skills|competencies|technologies|tech\s+stack|skill\s*set)(\s*&\s*\w+)?",
    "certifications": r"certifications?(\s*&\s*\w+)?|licenses?\s*&\s*certifications|courses",
    "summary": r"(professional\s+)?(summary|profile|objective|about\s+me)",
    "achievements": r"achievements?|awards?|honou?rs",
}
_HEADING_RE = {k: re.compile(rf"^\s*({v})\s*:?\s*$", re.I) for k, v in SECTION_ALIASES.items()}

ROLE_RULES: list[tuple[str, set[str], int]] = [
    ("Backend Developer", {"Python", "Java", "Node.js", "Go", "Django", "Flask", "FastAPI", "Spring Boot", "Express.js", "NestJS", ".NET", "REST APIs", "PostgreSQL", "MySQL", "MongoDB"}, 3),
    ("Python Developer", {"Python", "Django", "Flask", "FastAPI", "Pandas"}, 2),
    ("Java Developer", {"Java", "Spring Boot", "Hibernate"}, 2),
    ("Node.js Developer", {"Node.js", "Express.js", "NestJS"}, 2),
    ("Full Stack Developer", {"React", "Angular", "Vue.js", "Next.js", "Node.js", "Express.js", "Django", "Spring Boot", "MongoDB", "PostgreSQL"}, 3),
    ("Frontend Developer", {"React", "Angular", "Vue.js", "Next.js", "TypeScript", "JavaScript", "HTML", "CSS", "Tailwind CSS"}, 3),
    ("AI Engineer", {"LLM", "LangChain", "RAG", "OpenAI API", "Generative AI", "Machine Learning", "AI Agents", "Hugging Face"}, 2),
    ("Generative AI Engineer", {"LLM", "LangChain", "RAG", "OpenAI API", "Generative AI", "LlamaIndex", "Prompt Engineering", "Vector Databases", "AI Agents"}, 2),
    ("RAG Engineer", {"RAG", "Vector Databases", "LangChain", "LlamaIndex", "Pinecone", "FAISS", "ChromaDB", "pgvector"}, 2),
    ("Machine Learning Engineer", {"Machine Learning", "PyTorch", "TensorFlow", "scikit-learn", "Deep Learning", "MLOps"}, 2),
    ("Data Scientist", {"Data Science", "Machine Learning", "Pandas", "NumPy", "scikit-learn", "Statistics"}, 3),
    ("Data Engineer", {"Apache Spark", "Airflow", "Kafka", "ETL", "Snowflake", "BigQuery", "Databricks", "dbt"}, 2),
    ("DevOps Engineer", {"Docker", "Kubernetes", "Terraform", "CI/CD", "Jenkins", "Ansible", "AWS"}, 3),
    ("Mobile Developer", {"React Native", "Flutter", "Android", "iOS", "Kotlin", "Swift"}, 2),
    ("Software Engineer", {"Python", "Java", "C++", "Go", "JavaScript", "TypeScript", "C#"}, 1),
]

TECH_TITLE_RE = re.compile(
    r"engineer|developer|programmer|scientist|analyst|architect|devops|sre|data|software|ml|ai|"
    r"technical|tech|full.?stack|back.?end|front.?end|it |qa|test",
    re.I,
)
INTERN_RE = re.compile(r"\b(intern|internship|trainee|apprentice)\b", re.I)


# ----------------------------------------------------------------- LLM schema

class LLMExperience(BaseModel):
    title: str | None = None
    company: str | None = None
    start: str | None = None
    end: str | None = None
    employment_type: str | None = None  # full_time | internship | contract | part_time | freelance
    responsibilities: list[str] = Field(default_factory=list)


class LLMEducation(BaseModel):
    degree: str | None = None
    institution: str | None = None
    year: str | None = None


class LLMProject(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)


class LLMResume(BaseModel):
    candidate: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    experience: list[LLMExperience] = Field(default_factory=list)
    education: list[LLMEducation] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[LLMProject] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    job_roles: list[str] = Field(default_factory=list)
    transferable_skills: list[str] = Field(default_factory=list)
    preferred_industries: list[str] = Field(default_factory=list)


LLM_PROMPT = """Extract a structured resume profile from the resume text in the data block below.

Return JSON with exactly these keys:
candidate, email, phone, location, summary (1-2 sentences, factual),
experience: list of {{title, company, start ("Mon YYYY" or "YYYY"), end ("Mon YYYY" | "Present"),
  employment_type (one of full_time, internship, contract, part_time, freelance), responsibilities (list of short strings)}},
education: list of {{degree, institution, year}},
skills: list of technical skills explicitly written in the resume,
projects: list of {{name, description, technologies}},
certifications: list of strings,
job_roles: up to 8 job titles this candidate is realistically suited to apply for, based only on their stated experience and skills,
transferable_skills: skills from the resume that transfer to adjacent roles,
preferred_industries: industries implied by the resume (e.g. Software, IT, AI, FinTech).

Rules: Internships must have employment_type "internship". Do not merge internships into full-time roles.
Use null / [] for anything not present. Do not add skills that are not literally in the resume.

{data}
"""


# ----------------------------------------------------------------- rules helpers

def _split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.splitlines():
        stripped = line.strip()
        matched = None
        if 0 < len(stripped) <= 45:
            for key, rx in _HEADING_RE.items():
                if rx.match(stripped):
                    matched = key
                    break
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _contact(text: str) -> dict[str, str | None]:
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    phone = re.search(r"(\+?\d{1,3}[\s-]?)?(\(?\d{3,5}\)?[\s-]?)\d{3,5}[\s-]?\d{3,5}", text)
    name = None
    for line in text.splitlines()[:8]:
        l = line.strip()
        if not l or "@" in l or re.search(r"\d", l) or len(l) > 40:
            continue
        words = l.split()
        if 1 < len(words) <= 4 and all(w[:1].isalpha() for w in words) and not any(
            rx.match(l) for rx in _HEADING_RE.values()
        ):
            name = l.title() if l.isupper() else l
            break
    phone_val = phone.group(0).strip() if phone and len(re.sub(r"\D", "", phone.group(0))) >= 10 else None
    return {"candidate": name, "email": email.group(0) if email else None, "phone": phone_val}


def _rule_experience(sections: dict[str, list[str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for sec in ("experience", "internships"):
        lines = sections.get(sec, [])
        for i, line in enumerate(lines):
            ranges = find_date_ranges(line)
            if not ranges:
                continue
            r = ranges[0]
            context_lines = [l.strip() for l in lines[max(0, i - 2): i + 1] if l.strip()]
            header = line.replace(r.raw, "").strip(" |,-–—\t")
            if not header and context_lines:
                header = context_lines[-2] if len(context_lines) > 1 else context_lines[-1]
            nxt = [l.strip() for l in lines[i + 1: i + 3] if l.strip()]
            block = " ".join(context_lines + nxt)
            parts = [p.strip() for p in re.split(r"\s+[|@–—-]\s+|,\s+|\s+at\s+", header) if p.strip()]
            title = parts[0] if parts else header
            company = parts[1] if len(parts) > 1 else (nxt[0] if nxt and len(nxt[0]) < 60 and not find_date_ranges(nxt[0]) else None)
            is_intern = sec == "internships" or bool(INTERN_RE.search(block))
            resp = []
            for l in lines[i + 1: i + 12]:
                if find_date_ranges(l):
                    break
                ls = l.strip()
                if ls.startswith(("•", "-", "*", "●", "▪", "◦")) or (len(ls) > 40 and ls[:1].isupper()):
                    resp.append(ls.lstrip("•-*●▪◦ ").strip())
            entries.append({
                "title": title[:120] or None,
                "company": company[:120] if company else None,
                "start": r.start.strftime("%b %Y"),
                "end": "Present" if r.is_present else r.end.strftime("%b %Y"),
                "employment_type": "internship" if is_intern else "full_time",
                "responsibilities": resp[:8],
                "_range": r,
            })
    return entries


def _list_section(lines: list[str], limit: int = 15) -> list[str]:
    out = []
    for l in lines:
        s = l.strip().lstrip("•-*●▪◦ ").strip()
        if 3 <= len(s) <= 160:
            out.append(s)
    return out[:limit]


def _rule_projects(lines: list[str]) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for l in lines:
        s = l.strip()
        if not s:
            continue
        bullet = s.startswith(("•", "-", "*", "●", "▪", "◦"))
        if not bullet and len(s) <= 90:
            cur = {"name": s.split("|")[0].strip(" :"), "description": "", "technologies": []}
            projects.append(cur)
        elif cur is not None:
            cur["description"] = (cur["description"] + " " + s.lstrip("•-*●▪◦ ")).strip()[:600]
    for p in projects:
        p["technologies"] = [s.canonical for s in tax.extract_skills(p["name"] + " " + p["description"])]
    return [p for p in projects if p["description"] or p["technologies"]][:10]


def suggest_roles(skills: list[str], titles: list[str]) -> list[str]:
    have = set(skills)
    roles: list[str] = []
    for t in titles:
        if t and TECH_TITLE_RE.search(t) and not INTERN_RE.search(t):
            clean = re.sub(r"\s+", " ", t).strip().title()
            if clean not in roles and len(clean) < 60:
                roles.append(clean)
    scored = []
    for role, req, minimum in ROLE_RULES:
        n = len(have & req)
        if n >= minimum:
            scored.append((n, role))
    for _, role in sorted(scored, reverse=True):
        if role not in roles:
            roles.append(role)
    return roles[:10]


# ----------------------------------------------------------------- experience math

def _entry_range(e: dict[str, Any]) -> DateRange | None:
    if isinstance(e.get("_range"), DateRange):
        return e["_range"]
    s, en = parse_date_string(e.get("start")), parse_date_string(e.get("end") or "Present")
    if s and en and s <= en:
        return DateRange(s, en, f"{e.get('start')} - {e.get('end')}", (e.get("end") or "").lower() == "present")
    return None


def compute_experience(entries: list[dict[str, Any]]) -> dict[str, int]:
    prof, intern, relevant_prof, relevant_intern = [], [], [], []
    for e in entries:
        r = _entry_range(e)
        if not r:
            continue
        e["months"] = r.months
        etype = (e.get("employment_type") or "").lower()
        is_intern = etype == "internship" or bool(INTERN_RE.search(e.get("title") or ""))
        e["employment_type"] = "internship" if is_intern else (etype or "full_time")
        text = " ".join([e.get("title") or ""] + list(e.get("responsibilities") or []))
        relevant = bool(TECH_TITLE_RE.search(e.get("title") or "")) or bool(tax.extract_skills(text))
        e["relevant"] = relevant
        (intern if is_intern else prof).append(r)
        if relevant:
            (relevant_intern if is_intern else relevant_prof).append(r)
    p, i = merge_months(prof), merge_months(intern)
    return {
        "professional_experience_months": p,
        "internship_experience_months": i,
        "total_experience_months": merge_months(prof + intern),
        "relevant_experience_months": merge_months(relevant_prof + relevant_intern),
        "relevant_professional_months": merge_months(relevant_prof),
    }


def categorize(skills: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in skills:
        out.setdefault(tax.category_of(s), []).append(s)
    return out


# ----------------------------------------------------------------- main entry

def _company_verified(e: "LLMExperience", text_lower: str) -> bool:
    """A company claimed by the LLM must appear in the resume close to its claimed
    start year - so injected text elsewhere cannot fabricate an employment entry."""
    if not e.company:
        return True
    name = re.sub(r"\s+", " ", e.company.lower()).strip()
    year = re.search(r"(19|20)\d{2}", e.start or "")
    for m in re.finditer(re.escape(name), text_lower):
        if not year:
            return True
        window = text_lower[max(0, m.start() - 250): m.end() + 250]
        if year.group(0) in window:
            return True
    return False


def _in_text(value: str | None, text_lower: str) -> bool:
    if not value:
        return False
    v = re.sub(r"\s+", " ", value.lower()).strip()
    return len(v) >= 2 and v in text_lower


async def analyze_resume(text: str, use_llm: bool = True) -> dict[str, Any]:
    sections = _split_sections(text)
    contact = _contact(text)
    tax_skills = [s.canonical for s in tax.extract_skills(text)]
    rule_exp = _rule_experience(sections)
    text_lower = re.sub(r"\s+", " ", text.lower())

    method = "rules"
    llm_data: LLMResume | None = None
    llm = get_llm()
    if use_llm and llm.available:
        _, block = wrap_untrusted(text, "resume")
        try:
            raw = await llm.complete_json(LLM_PROMPT.format(data=block), max_tokens=4000)
            llm_data = LLMResume.model_validate(raw)
            method = "llm"
        except (LLMUnavailable, ValidationError) as e:
            log.warning("LLM resume analysis failed, using rules: %s", e)

    if llm_data:
        # --- verify every LLM claim against the source text ---
        skills: list[str] = []
        for sk in llm_data.skills + tax_skills:
            canon = tax.canonical_name(sk)
            if canon not in skills and (tax.skill_in_text(sk, text) or tax.skill_in_text(canon, text)):
                skills.append(canon)
        experience = []
        for e in llm_data.experience:
            if e.company and not _company_verified(e, text_lower):
                log.info("Dropping unverifiable company from LLM output: %s", e.company)
                continue
            experience.append(e.model_dump())
        if not experience:
            experience = rule_exp
        education = [ed.model_dump() for ed in llm_data.education
                     if _in_text(ed.institution, text_lower) or _in_text(ed.degree, text_lower)]
        projects = []
        for p in llm_data.projects:
            d = p.model_dump()
            d["technologies"] = [tax.canonical_name(t) for t in p.technologies if tax.skill_in_text(t, text)]
            projects.append(d)
        certs = [c for c in llm_data.certifications if c and any(w in text_lower for w in c.lower().split()[:3])]
        candidate = llm_data.candidate if _in_text(llm_data.candidate, text_lower) else contact["candidate"]
        email = llm_data.email if _in_text(llm_data.email, text_lower) else contact["email"]
        phone = contact["phone"] or llm_data.phone
        transferable = [tax.canonical_name(t) for t in llm_data.transferable_skills if tax.skill_in_text(t, text)]
        summary = llm_data.summary
        location = llm_data.location if _in_text(llm_data.location, text_lower) else None
        industries = llm_data.preferred_industries[:6] or ["Software", "IT"]
        llm_roles = [r for r in llm_data.job_roles if r]
    else:
        skills = tax_skills
        experience = rule_exp
        edu_lines = _list_section(sections.get("education", []), 8)
        education = [{"degree": l, "institution": None, "year": (re.findall(r"(?:19|20)\d{2}", l) or [None])[-1]}
                     for l in edu_lines if detect_education_level(l) or re.search(r"university|college|institute|school", l, re.I)]
        projects = _rule_projects(sections.get("projects", []))
        certs = _list_section(sections.get("certifications", []), 12)
        candidate, email, phone = contact["candidate"], contact["email"], contact["phone"]
        transferable = []
        summary = " ".join(_list_section(sections.get("summary", []), 3))[:500] or None
        location = None
        industries = ["Software", "IT"] + (["AI"] if any(tax.category_of(s) == "ai_ml" for s in skills) else [])
        llm_roles = []

    exp = compute_experience(experience)
    for e in experience:
        e.pop("_range", None)
    edu_text = " ".join(f"{e.get('degree') or ''} {e.get('institution') or ''}" for e in education) or text
    edu_level = detect_education_level(edu_text) or detect_education_level(text)
    for e in education:
        e["level"] = detect_education_level(f"{e.get('degree') or ''}")

    titles = [e.get("title") for e in experience if e.get("title")]
    roles = []
    for r in llm_roles + suggest_roles(skills, titles):
        if r.lower() not in {x.lower() for x in roles}:
            roles.append(r)
    if not transferable:
        transferable = [s for s in skills if tax.category_of(s) in ("concept", "language", "cloud", "devops")][:10]

    companies = []
    for e in experience:
        c = e.get("company")
        if c and c not in companies:
            companies.append(c)

    level = experience_level(exp["professional_experience_months"], exp["internship_experience_months"])
    return {
        "candidate": candidate,
        "email": email,
        "phone": phone,
        "location": location,
        "summary": summary,
        "experience_level": level,
        **exp,
        "experience": experience,
        "previous_companies": companies,
        "education": education,
        "education_level": edu_level,
        "skills": skills,
        "skills_by_category": categorize(skills),
        "projects": projects,
        "certifications": certs,
        "job_roles": roles[:10],
        "transferable_skills": transferable,
        "preferred_industries": industries,
        "analysis_method": method,
    }


def default_preferences(profile: dict[str, Any]) -> dict[str, Any]:
    """Suggest search preferences from a profile (user can edit)."""
    years = profile.get("professional_experience_months", 0) / 12
    loc = profile.get("location")
    return {
        "preferred_roles": profile.get("job_roles", [])[:6],
        "min_experience_years": 0,
        "max_experience_years": max(2, round(years + 3)),
        "preferred_locations": [loc] if loc else [],
        "remote_preference": "any",  # any | remote | hybrid | onsite
        "company_sizes": ["small", "medium", "large", "unknown"],
        "preferred_technologies": profile.get("skills", [])[:12],
        "min_match_score": 40,
        "posted_within_days": 30,
        "countries": [],
        "prioritize_small_medium": True,
    }
