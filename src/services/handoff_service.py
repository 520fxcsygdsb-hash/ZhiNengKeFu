"""Human agent handoff queue and session mode switching."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.handoff import HandoffRequest
from src.models.message import Message
from src.models.session import ChatSession

logger = structlog.get_logger()

HANDOFF_WAITING = "waiting"
HANDOFF_ACTIVE = "active"
HANDOFF_RESOLVED = "resolved"
HANDOFF_CANCELLED = "cancelled"

SESSION_ACTIVE = "active"
SESSION_WAITING_HUMAN = "waiting_human"
SESSION_HUMAN_ACTIVE = "human_active"


def handoff_ticket_id(handoff_id: str) -> str:
    return f"HND-{handoff_id.replace('-', '')[:8].upper()}"


def is_human_session_status(status: str | None) -> bool:
    return status in (SESSION_WAITING_HUMAN, SESSION_HUMAN_ACTIVE)


async def set_session_status(
    db: AsyncSession, session_id: str, status: str
) -> ChatSession | None:
    session = await db.get(ChatSession, session_id)
    if not session:
        return None
    session.status = status
    await db.flush()
    return session


async def get_open_handoff(
    db: AsyncSession, session_id: str
) -> HandoffRequest | None:
    result = await db.execute(
        select(HandoffRequest)
        .where(HandoffRequest.session_id == session_id)
        .where(HandoffRequest.status.in_([HANDOFF_WAITING, HANDOFF_ACTIVE]))
        .order_by(HandoffRequest.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_handoff(
    db: AsyncSession,
    *,
    session_id: str,
    user_id: str | None = None,
    reason: str | None = None,
) -> HandoffRequest:
    existing = await get_open_handoff(db, session_id)
    if existing:
        return existing

    handoff = HandoffRequest(
        session_id=session_id,
        user_id=user_id,
        reason=(reason or "").strip() or None,
        status=HANDOFF_WAITING,
    )
    db.add(handoff)
    await set_session_status(db, session_id, SESSION_WAITING_HUMAN)
    await db.flush()
    logger.info(
        "handoff_created",
        handoff_id=handoff.id,
        session_id=session_id,
        ticket_id=handoff_ticket_id(handoff.id),
    )
    return handoff


def build_handoff_ack(handoff: HandoffRequest, *, already_queued: bool = False) -> str:
    ticket = handoff_ticket_id(handoff.id)
    if already_queued:
        return (
            f"您已在人工客服排队中，工单号 {ticket}。"
            "请稍候，客服接入后会在此回复您。"
        )
    return (
        f"已为您转接人工客服，工单号 {ticket}。"
        "当前排队中，请描述您的问题，客服接入后将尽快回复。"
    )


async def claim_handoff(
    db: AsyncSession,
    handoff_id: str,
    agent_id: str = "admin",
) -> HandoffRequest:
    handoff = await db.get(HandoffRequest, handoff_id)
    if not handoff:
        raise LookupError("Handoff not found")
    if handoff.status not in (HANDOFF_WAITING, HANDOFF_ACTIVE):
        raise ValueError(f"Cannot claim handoff in status {handoff.status}")

    handoff.status = HANDOFF_ACTIVE
    handoff.agent_id = agent_id
    await set_session_status(db, handoff.session_id, SESSION_HUMAN_ACTIVE)
    await db.flush()
    logger.info("handoff_claimed", handoff_id=handoff_id, agent_id=agent_id)
    return handoff


async def resolve_handoff(
    db: AsyncSession,
    handoff_id: str,
) -> HandoffRequest:
    handoff = await db.get(HandoffRequest, handoff_id)
    if not handoff:
        raise LookupError("Handoff not found")
    if handoff.status == HANDOFF_RESOLVED:
        return handoff

    handoff.status = HANDOFF_RESOLVED
    handoff.resolved_at = datetime.now(timezone.utc)
    await set_session_status(db, handoff.session_id, SESSION_ACTIVE)
    await db.flush()
    logger.info("handoff_resolved", handoff_id=handoff_id)
    return handoff


async def add_agent_reply(
    db: AsyncSession,
    handoff_id: str,
    content: str,
    *,
    sessions,
) -> Message:
    handoff = await db.get(HandoffRequest, handoff_id)
    if not handoff:
        raise LookupError("Handoff not found")
    if handoff.status not in (HANDOFF_WAITING, HANDOFF_ACTIVE):
        raise ValueError("Handoff is closed")

    if handoff.status == HANDOFF_WAITING:
        handoff.status = HANDOFF_ACTIVE
        await set_session_status(db, handoff.session_id, SESSION_HUMAN_ACTIVE)

    message = await sessions.add_message(
        db, handoff.session_id, "agent", content.strip()
    )
    await db.flush()
    return message


async def list_handoffs(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[HandoffRequest]:
    q = select(HandoffRequest).order_by(HandoffRequest.created_at.desc())
    if status:
        q = q.where(HandoffRequest.status == status)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_session_messages_since(
    db: AsyncSession,
    session_id: str,
    after_id: str | None = None,
) -> list[dict[str, Any]]:
    messages = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    rows = list(messages.scalars().all())
    if after_id:
        ids = [m.id for m in rows]
        if after_id in ids:
            idx = ids.index(after_id)
            rows = rows[idx + 1 :]
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


def handoff_to_dict(h: HandoffRequest) -> dict[str, Any]:
    return {
        "id": h.id,
        "session_id": h.session_id,
        "user_id": h.user_id,
        "reason": h.reason,
        "status": h.status,
        "agent_id": h.agent_id,
        "ticket_id": handoff_ticket_id(h.id),
        "created_at": h.created_at.isoformat() if h.created_at else None,
        "updated_at": h.updated_at.isoformat() if h.updated_at else None,
        "resolved_at": h.resolved_at.isoformat() if h.resolved_at else None,
    }
