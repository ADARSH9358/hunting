"""ResumeParserService: validates uploaded files and extracts plain text."""
from __future__ import annotations

import io
import re
import zipfile

from pypdf import PdfReader
from docx import Document


class ResumeValidationError(ValueError):
    pass


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def detect_type(filename: str, data: bytes) -> tuple[str, str]:
    """Validate by magic bytes (not just extension). Returns (mime, ext)."""
    name = (filename or "").lower()
    if data[:5] == b"%PDF-":
        if not name.endswith(".pdf"):
            raise ResumeValidationError("File content is PDF but extension is not .pdf")
        return PDF_MIME, ".pdf"
    if data[:4] == b"PK\x03\x04":
        if not name.endswith(".docx"):
            raise ResumeValidationError("Only .docx Word documents are supported")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "word/document.xml" not in names:
                    raise ResumeValidationError("Not a valid DOCX document")
                if any(n.lower().endswith("vbaproject.bin") for n in names):
                    raise ResumeValidationError("Macro-enabled documents are not accepted")
                total = sum(i.file_size for i in z.infolist())
                if total > 100 * 1024 * 1024:
                    raise ResumeValidationError("Document expands to an unsafe size")
        except zipfile.BadZipFile as e:
            raise ResumeValidationError("Corrupted DOCX file") from e
        return DOCX_MIME, ".docx"
    raise ResumeValidationError("Unsupported file type. Please upload a PDF or DOCX resume.")


def extract_text(data: bytes, mime: str) -> str:
    if mime == PDF_MIME:
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as e:  # noqa: BLE001
                    raise ResumeValidationError("Password-protected PDFs are not supported") from e
            pages = [(p.extract_text() or "") for p in reader.pages[:20]]
        except ResumeValidationError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ResumeValidationError(f"Could not read PDF: {e}") from e
        text = "\n".join(pages)
    else:
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        text = "\n".join(parts)
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 50:
        raise ResumeValidationError(
            "Very little text could be extracted. If this is a scanned PDF, please upload a text-based PDF or DOCX."
        )
    return text
