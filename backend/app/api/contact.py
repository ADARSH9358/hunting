"""Recruiter / HR contact directory."""  
from __future__ import annotations  
  
from fastapi import APIRouter, Depends, Query  
from pydantic import BaseModel, EmailStr, Field  
from sqlalchemy import func, select  
from sqlalchemy.ext.asyncio import AsyncSession  
  
from app.core.security import get_current_user  
from app.db import get_db  
from app.models import Contact, User  
  
router = APIRouter(prefix="/api/contacts", tags=["contacts"])  
  
  
class ContactIn(BaseModel):  
    name: str = Field(min_length=1, max_length=200)  
    company_name: str | None = Field(default=None, max_length=255)  
    position: str | None = Field(default=None, max_length=200)  
    email_ids: list[EmailStr] = Field(default_factory=list, max_length=20)  
    mobile_numbers: list[str] = Field(default_factory=list, max_length=20)  
  
  
class ContactBulkIn(BaseModel):  
    contacts: list[ContactIn] = Field(min_length=1, max_length=500)  
  
  
def _out(c: Contact) -> dict:  
    return {"id": c.id, "name": c.name, "company_name": c.company_name,  
            "position": c.position, "email_ids": c.email_ids,  
            "mobile_numbers": c.mobile_numbers, "created_at": c.created_at}  
  
  
@router.post("", status_code=201)  
async def create_contacts(body: ContactBulkIn, user: User = Depends(get_current_user),  
                          db: AsyncSession = Depends(get_db)):  
    """Bulk insert: accepts multiple contacts in one request."""  
    rows = [Contact(user_id=user.id, name=c.name, company_name=c.company_name,  
                    position=c.position, email_ids=[str(e) for e in c.email_ids],  
                    mobile_numbers=c.mobile_numbers) for c in body.contacts]  
    db.add_all(rows)  
    await db.commit()  
    for r in rows:  
        await db.refresh(r)  
    return {"created": len(rows), "contacts": [_out(r) for r in rows]}  
  
  
@router.get("")  
async def list_contacts(q: str | None = Query(None, max_length=100),  
                        company: str | None = Query(None, max_length=255),  
                        page_no: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),  
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):  
    stmt = select(Contact).where(Contact.user_id == user.id)  
    if q:  
        stmt = stmt.where(Contact.name.ilike(f"%{q}%"))  
    if company:  
        stmt = stmt.where(Contact.company_name.ilike(f"%{company}%"))  
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()  
    rows = (await db.execute(stmt.order_by(Contact.id.desc())  
                             .offset((page_no - 1) * page_size).limit(page_size))).scalars().all()  
    return {"total": total, "page_no": page_no, "page_size": page_size,  
            "contacts": [_out(c) for c in rows]}