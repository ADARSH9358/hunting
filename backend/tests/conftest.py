import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="jobhunt-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
    "STORAGE_DIR": str(_TMP / "storage"),
    "LLM_PROVIDER": "none",
    "TASK_BACKEND": "inprocess",
    "ENABLED_SOURCES": "remoteok,remotive",
    "MAX_COMPANIES_PER_RUN": "10",
    "SECRET_KEY": "test-secret-key-test-secret-key-123456",
    "API_RATE_LIMIT_PER_MINUTE": "10000",
})
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "RAPIDAPI_KEY", "SERPAPI_KEY", "ADZUNA_APP_ID", "JOOBLE_API_KEY",
          "APIFY_TOKEN", "BRAVE_SEARCH_API_KEY", "RESUME_ENCRYPTION_KEY"):
    os.environ.pop(k, None)

import io  # noqa: E402

import pytest  # noqa: E402
from docx import Document  # noqa: E402

RESUME_TEXT = """Priya Sharma
priya.sharma@example.com | +91 98765 43210 | Bengaluru, India

SUMMARY
Backend and GenAI engineer building Python and Node.js services and RAG pipelines.

EXPERIENCE
Software Engineer | Acme Analytics Pvt Ltd | Jan 2024 - Present
- Built REST APIs in Python (FastAPI) and Node.js (Express.js) backed by PostgreSQL and Redis
- Designed a RAG pipeline with LangChain and pgvector deployed on AWS with Docker

Software Engineering Intern | Bright Labs | Jun 2023 - Dec 2023
- Developed React dashboards and MongoDB data models

EDUCATION
Master of Computer Applications (MCA), Christ University, 2023
BCA, Bangalore University, 2021

PROJECTS
DocChat
- Chat-with-your-documents app using LangChain, OpenAI API and FAISS

SKILLS
Python, Java, Node.js, Express.js, React, FastAPI, PostgreSQL, MongoDB, Redis, AWS, Docker, LangChain, RAG, Git

CERTIFICATIONS
AWS Certified Cloud Practitioner
"""


def make_docx(text: str = RESUME_TEXT) -> bytes:
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf(text: str = RESUME_TEXT) -> bytes:
    """Minimal hand-built text PDF (Helvetica)."""
    lines = text.splitlines()
    esc = [l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace").decode("latin-1") for l in lines]
    content = "BT /F1 10 Tf 40 800 Td 12 TL\n" + "\n".join(f"({l}) Tj T*" for l in esc) + "\nET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


@pytest.fixture
def resume_docx() -> bytes:
    return make_docx()


@pytest.fixture
def resume_pdf() -> bytes:
    return make_pdf()
