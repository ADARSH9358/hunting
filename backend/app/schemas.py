from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Str100 = str


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None


class ExperienceItem(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    employment_type: Literal["full_time", "internship", "contract", "part_time", "freelance"] | None = "full_time"
    responsibilities: list[str] = Field(default_factory=list, max_length=30)
    months: int | None = None
    relevant: bool | None = None


class EducationItem(BaseModel):
    degree: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    year: str | None = Field(default=None, max_length=20)
    level: str | None = None


class ProjectItem(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    technologies: list[str] = Field(default_factory=list, max_length=40)


class ProfileUpdate(BaseModel):
    candidate: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=3000)
    experience: list[ExperienceItem] | None = Field(default=None, max_length=40)
    education: list[EducationItem] | None = Field(default=None, max_length=20)
    education_level: Literal["phd", "masters", "bachelors", "diploma", "high_school"] | None = None
    skills: list[str] | None = Field(default=None, max_length=200)
    projects: list[ProjectItem] | None = Field(default=None, max_length=40)
    certifications: list[str] | None = Field(default=None, max_length=50)
    job_roles: list[str] | None = Field(default=None, max_length=20)
    transferable_skills: list[str] | None = Field(default=None, max_length=50)
    preferred_industries: list[str] | None = Field(default=None, max_length=20)
    # manual overrides (months); if omitted they are recomputed from experience entries
    professional_experience_months: int | None = Field(default=None, ge=0, le=600)
    internship_experience_months: int | None = Field(default=None, ge=0, le=240)

    @field_validator("skills", "job_roles", "certifications", "transferable_skills", "preferred_industries")
    @classmethod
    def _clean(cls, v):
        if v is None:
            return v
        out = []
        for x in v:
            x = (x or "").strip()[:100]
            if x and x.lower() not in {o.lower() for o in out}:
                out.append(x)
        return out


class Preferences(BaseModel):
    preferred_roles: list[str] = Field(default_factory=list, max_length=20)
    min_experience_years: float = Field(default=0, ge=0, le=50)
    max_experience_years: float = Field(default=10, ge=0, le=50)
    preferred_locations: list[str] = Field(default_factory=list, max_length=20)
    countries: list[str] = Field(default_factory=list, max_length=20)
    remote_preference: Literal["any", "remote", "hybrid", "onsite"] = "any"
    company_sizes: list[Literal["small", "medium", "large", "unknown"]] = Field(
        default_factory=lambda: ["small", "medium", "large", "unknown"])
    preferred_technologies: list[str] = Field(default_factory=list, max_length=60)
    min_match_score: float = Field(default=40, ge=0, le=100)
    posted_within_days: int = Field(default=30, ge=1, le=365)
    prioritize_small_medium: bool = True
    weights: dict[str, float] | None = None

    @field_validator("weights")
    @classmethod
    def _weights(cls, v):
        if v is None:
            return v
        allowed = {"skills", "experience", "role", "education", "location"}
        if set(v) - allowed:
            raise ValueError(f"weights keys must be within {sorted(allowed)}")
        if any(x < 0 or x > 100 for x in v.values()) or sum(v.values()) <= 0:
            raise ValueError("weights must be between 0 and 100 and not all zero")
        return v


class RunSearchIn(BaseModel):
    overrides: Preferences | None = None


class CompanyUpdate(BaseModel):
    employee_count: int | None = Field(default=None, ge=1, le=5_000_000)
    company_type: str | None = Field(default=None, max_length=50)
    careers_url: str | None = Field(default=None, max_length=512)
    website: str | None = Field(default=None, max_length=512)


class SaveJobIn(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class UserSettings(BaseModel):
    small_company_max: int = Field(default=50, ge=1, le=10000)
    medium_company_max: int = Field(default=500, ge=2, le=100000)


def page(items: list[Any], total: int, page_no: int, size: int) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page_no, "page_size": size,
            "pages": (total + size - 1) // size if size else 0}
