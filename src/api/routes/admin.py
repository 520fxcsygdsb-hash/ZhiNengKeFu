from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_state import refresh_app_retriever
from src.core.config import get_settings
from src.core.security import verify_api_key
from src.db import get_db
from src.models.complaint import Complaint
from src.models.handoff import HandoffRequest
from src.models.knowledge import KnowledgeDoc
from src.rag.indexer import rebuild_index_async
from src.services.complaint_service import (
    ticket_id_for,
    update_complaint_status as apply_complaint_status,
)
from src.services import handoff_service as hs
from src.services.session_service import SessionService
from src.api.deps import get_session_service

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class ComplaintStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(Received|InReview|Resolved)$")


class HandoffReplyBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class HandoffClaimBody(BaseModel):
    agent_id: str = Field(default="admin", max_length=128)


@router.get("/knowledge")
async def list_knowledge(
  _: Annotated[str, Depends(verify_api_key)],
  db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = get_settings()
    files: list[dict] = []
    if settings.knowledge_dir.exists():
        for path in sorted(settings.knowledge_dir.rglob("*")):
            if path.suffix.lower() not in {".txt", ".md"}:
                continue
            stat = path.stat()
            files.append(
                {
                    "filename": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )

    result = await db.execute(select(KnowledgeDoc).order_by(KnowledgeDoc.indexed_at.desc()))
    docs = result.scalars().all()
    return {
        "files": files,
        "indexed_docs": [
            {
                "filename": d.filename,
                "chunk_count": d.chunk_count,
                "indexed_at": d.indexed_at.isoformat() if d.indexed_at else None,
            }
            for d in docs
        ],
    }


@router.delete("/knowledge/{filename}")
async def delete_knowledge_file(
    filename: str,
    request: Request,
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    settings = get_settings()
    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")

    target = settings.knowledge_dir / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")

    target.unlink()
    chunk_count = await rebuild_index_async(settings)
    refresh_app_retriever(request.app)
    logger.info("admin_knowledge_deleted", filename=safe_name, chunk_count=chunk_count)
    return {"filename": safe_name, "chunk_count": chunk_count, "message": "Deleted and reindexed"}


@router.get("/complaints")
async def list_complaints(
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
    offset: int = 0,
):
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    result = await db.execute(
        select(Complaint).order_by(Complaint.created_at.desc()).limit(limit).offset(offset)
    )
    items = result.scalars().all()
    return {
        "items": [
            {
                "id": c.id,
                "session_id": c.session_id,
                "details": c.details,
                "status": c.status,
                "ticket_id": ticket_id_for(c.id),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in items
        ],
        "limit": limit,
        "offset": offset,
    }


@router.patch("/complaints/{complaint_id}")
async def update_complaint_status(
    complaint_id: str,
    body: ComplaintStatusUpdate,
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        complaint = await apply_complaint_status(db, complaint_id, body.status)
    except LookupError:
        raise HTTPException(status_code=404, detail="Complaint not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "id": complaint.id,
        "status": complaint.status,
        "ticket_id": ticket_id_for(complaint.id),
    }


@router.get("/handoffs")
async def list_handoffs_admin(
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    items = await hs.list_handoffs(db, status=status, limit=limit, offset=offset)
    return {
        "items": [hs.handoff_to_dict(h) for h in items],
        "limit": limit,
        "offset": offset,
    }


@router.get("/handoffs/{handoff_id}")
async def get_handoff_detail(
    handoff_id: str,
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
):
    handoff = await db.get(HandoffRequest, handoff_id)
    if not handoff:
        raise HTTPException(status_code=404, detail="Handoff not found")
    messages = await sessions.get_messages(db, handoff.session_id, limit=100)
    return {
        **hs.handoff_to_dict(handoff),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.post("/handoffs/{handoff_id}/claim")
async def claim_handoff_admin(
    handoff_id: str,
    body: HandoffClaimBody,
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        handoff = await hs.claim_handoff(db, handoff_id, agent_id=body.agent_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Handoff not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return hs.handoff_to_dict(handoff)


@router.post("/handoffs/{handoff_id}/reply")
async def reply_handoff_admin(
    handoff_id: str,
    body: HandoffReplyBody,
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
):
    try:
        message = await hs.add_agent_reply(
            db, handoff_id, body.message, sessions=sessions
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Handoff not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return {
        "message_id": message.id,
        "session_id": message.session_id,
        "content": message.content,
    }


@router.post("/handoffs/{handoff_id}/resolve")
async def resolve_handoff_admin(
    handoff_id: str,
    _: Annotated[str, Depends(verify_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        handoff = await hs.resolve_handoff(db, handoff_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Handoff not found") from None
    await db.commit()
    return hs.handoff_to_dict(handoff)
