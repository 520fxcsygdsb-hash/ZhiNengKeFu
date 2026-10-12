"""User-facing handoff status and message polling."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import verify_api_key
from src.db import get_db
from src.services import handoff_service as hs
from src.services.session_service import SessionService
from src.api.deps import get_session_service

router = APIRouter(prefix="/api/v1/handoffs", tags=["handoffs"])


@router.get("/session/{session_id}")
async def get_session_handoff_status(
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    sessions: Annotated[SessionService, Depends(get_session_service)],
    _: Annotated[str, Depends(verify_api_key)],
    after_message_id: str | None = None,
):
    session = await sessions.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    handoff = await hs.get_open_handoff(db, session_id)
    new_messages = await hs.get_session_messages_since(
        db, session_id, after_id=after_message_id
    )
    agent_messages = [m for m in new_messages if m["role"] == "agent"]

    return {
        "session_id": session_id,
        "session_status": session.status,
        "human_mode": hs.is_human_session_status(session.status),
        "handoff": hs.handoff_to_dict(handoff) if handoff else None,
        "new_messages": new_messages,
        "agent_messages": agent_messages,
    }
