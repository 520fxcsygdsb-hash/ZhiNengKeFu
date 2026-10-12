from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.services import handoff_service as hs
from src.tools import ToolResult


async def request_human_agent(
    reason: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    db: AsyncSession | None = None,
    sessions=None,  # kept for call-site compatibility; persistence is route-owned
) -> ToolResult:
    del sessions  # message persistence happens in chat routes
    if not session_id or not db:
        return ToolResult(success=False, error="Session required for human handoff")

    existing = await hs.get_open_handoff(db, session_id)
    if existing:
        ack = hs.build_handoff_ack(existing, already_queued=True)
        return ToolResult(
            success=True,
            data={
                "handoff_id": existing.id,
                "ticket_id": hs.handoff_ticket_id(existing.id),
                "status": existing.status,
                "message": ack,
                "already_queued": True,
            },
        )

    handoff = await hs.create_handoff(
        db,
        session_id=session_id,
        user_id=user_id,
        reason=reason,
    )
    ack = hs.build_handoff_ack(handoff)
    return ToolResult(
        success=True,
        data={
            "handoff_id": handoff.id,
            "ticket_id": hs.handoff_ticket_id(handoff.id),
            "status": handoff.status,
            "message": ack,
        },
    )
