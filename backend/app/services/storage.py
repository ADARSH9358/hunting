"""Secure resume file storage: random filenames, outside web root, optional Fernet encryption."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import get_settings


class ResumeStorage:
    def __init__(self) -> None:
        s = get_settings()
        self.root = Path(s.storage_dir) / "resumes"
        self.root.mkdir(parents=True, exist_ok=True)
        self.fernet = Fernet(s.resume_encryption_key.encode()) if s.resume_encryption_key else None

    def save(self, user_id: int, data: bytes, ext: str) -> tuple[str, str, bool]:
        digest = hashlib.sha256(data).hexdigest()
        user_dir = self.root / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{ext}{'.enc' if self.fernet else ''}"
        path = user_dir / name
        path.write_bytes(self.fernet.encrypt(data) if self.fernet else data)
        return str(path.relative_to(self.root)), digest, bool(self.fernet)

    def load(self, rel_path: str, encrypted: bool) -> bytes:
        path = (self.root / rel_path).resolve()
        if self.root.resolve() not in path.parents:
            raise PermissionError("invalid path")
        raw = path.read_bytes()
        if encrypted:
            if not self.fernet:
                raise RuntimeError("RESUME_ENCRYPTION_KEY required to read encrypted resume")
            return self.fernet.decrypt(raw)
        return raw

    def delete(self, rel_path: str) -> None:
        path = (self.root / rel_path).resolve()
        if self.root.resolve() in path.parents and path.exists():
            path.unlink()
