"""Tests for human handoff queue."""

from __future__ import annotations

import pytest

from src.services import handoff_service as hs


@pytest.mark.asyncio
async def test_handoff_lifecycle(db_session):
    from src.services.session_service import SessionService

    sessions = SessionService(redis_client=None)
    session = await sessions.create_session(db_session)
    await db_session.commit()

    handoff = await hs.create_handoff(
        db_session,
        session_id=session.id,
        reason="转人工",
    )
    await db_session.commit()
    assert handoff.status == hs.HANDOFF_WAITING
    assert (await sessions.get_session(db_session, session.id)).status == hs.SESSION_WAITING_HUMAN

    claimed = await hs.claim_handoff(db_session, handoff.id, agent_id="agent-1")
    await db_session.commit()
    assert claimed.status == hs.HANDOFF_ACTIVE
    assert (await sessions.get_session(db_session, session.id)).status == hs.SESSION_HUMAN_ACTIVE

    msg = await hs.add_agent_reply(
        db_session, handoff.id, "您好，我是人工客服", sessions=sessions
    )
    await db_session.commit()
    assert msg.role == "agent"
    assert "人工客服" in msg.content

    resolved = await hs.resolve_handoff(db_session, handoff.id)
    await db_session.commit()
    assert resolved.status == hs.HANDOFF_RESOLVED
    assert (await sessions.get_session(db_session, session.id)).status == hs.SESSION_ACTIVE


@pytest.mark.asyncio
async def test_handoff_tool_requires_session(db_session):
    from src.tools.handoff import request_human_agent

    result = await request_human_agent("转人工", session_id=None, db=None)
    assert not result.success


@pytest.mark.asyncio
async def test_handoff_tool_creates_ticket(db_session):
    from src.services.session_service import SessionService
    from src.tools.handoff import request_human_agent

    sessions = SessionService(redis_client=None)
    session = await sessions.create_session(db_session)
    await db_session.commit()

    result = await request_human_agent(
        "转人工客服",
        session_id=session.id,
        db=db_session,
    )
    await db_session.commit()
    assert result.success
    assert result.data["ticket_id"].startswith("HND-")
    assert "人工客服" in result.data["message"]
