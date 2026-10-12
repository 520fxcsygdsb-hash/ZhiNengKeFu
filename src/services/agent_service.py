from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.metrics import TOOL_CALLS, TOOL_LATENCY, TOOL_SELECTION
from src.core.tracing import trace_span
from src.rag.prompts import (
    AGENT_SYSTEM_PROMPT,
    REACT_SYSTEM_HINT,
    TOOL_SELECTION_HINT,
    build_greeting_messages,
    is_greeting,
    is_simple_faq,
    is_transfer_to_human,
)
from src.rag.retriever import Retriever
from src.services.llm.kimi_client import (
    KimiClient,
    build_assistant_tool_message_multi,
)
from src.services.llm.local_qwen import LocalQwenService
from src.services.session_service import SessionService
from src.services.workflows.return_workflow import try_handle_return_workflow
from src.tools import complaint, handoff, knowledge_chat, logistics, order, returns
from src.tools.registry import get_openai_tools
from src.utils.text import sanitize_assistant_reply
from src.utils.tool_answer import format_tool_steps_answer

logger = structlog.get_logger()

_STREAM_CHUNK_SIZE = 20
_TERMINAL_TOOLS = frozenset(
    {"customer_chat", "create_return_request", "request_human_agent"}
)


class TurnKind(str, Enum):
    GREETING = "greeting"
    WORKFLOW = "workflow"
    HANDOFF = "handoff"
    FAQ = "faq"
    DIRECT = "direct"
    TOOLS = "tools"


@dataclass
class ToolStep:
    tool_name: str
    tool_input: dict
    tool_result: dict


@dataclass
class AgentResponse:
    answer: str
    tool_name: str | None = None
    tool_result: dict | None = None
    citations: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    handoff: bool = False
    session_status: str | None = None


@dataclass
class TurnPlan:
    kind: TurnKind
    answer: str = ""
    tool_name: str | None = None
    tool_result: dict | None = None
    citations: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    steps: list[ToolStep] = field(default_factory=list)
    context: list[dict[str, str]] = field(default_factory=list)
    question: str = ""
    handoff: bool = False
    session_status: str | None = None
    stream_rag: bool = False
    rag_query: str | None = None


def _done_event(
    answer: str,
    tool_name: str | None = None,
    citations: list[str] | None = None,
    tools_used: list[str] | None = None,
    *,
    handoff: bool = False,
    session_status: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "done",
        "answer": answer,
        "tool_name": tool_name,
        "citations": citations or [],
        "tools_used": tools_used or [],
    }
    if handoff:
        payload["handoff"] = True
        payload["session_status"] = session_status or "waiting_human"
    return payload


def _status_event(phase: str = "thinking") -> dict[str, Any]:
    return {"type": "status", "phase": phase}


def _collect_citations(steps: list[ToolStep]) -> list[str]:
    citations: list[str] = []
    for step in steps:
        citations.extend(step.tool_result.get("citations", []))
    return citations


def _chunk_text(text: str, size: int = _STREAM_CHUNK_SIZE) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


class AgentService:
    def __init__(
        self,
        kimi: KimiClient,
        retriever: Retriever,
        qwen: LocalQwenService | None = None,
    ):
        self.kimi = kimi
        self.retriever = retriever
        self.qwen = qwen

    async def _call_tool(
        self,
        tool_name: str,
        tool_input: dict,
        session_id: str | None = None,
        db: AsyncSession | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
        sessions: SessionService | None = None,
    ) -> dict:
        TOOL_CALLS.labels(tool_name=tool_name).inc()
        start = time.perf_counter()
        try:
            if tool_name == "fetch_logistics_information":
                result = await logistics.fetch_logistics_information(
                    tool_input.get("logistics_number", "")
                )
            elif tool_name == "record_user_complaint":
                result = await complaint.record_user_complaint(
                    tool_input.get("complaint_details", ""),
                    session_id=session_id,
                    db=db,
                )
            elif tool_name == "create_return_request":
                result = await returns.create_return_request(
                    tool_input.get("query", ""),
                    order_id=tool_input.get("order_id"),
                    retriever=self.retriever,
                    qwen=self.qwen,
                    kimi=self.kimi,
                )
            elif tool_name == "customer_chat":
                result = await knowledge_chat.customer_chat(
                    tool_input.get("query", ""),
                    self.retriever,
                    qwen=self.qwen,
                    kimi=self.kimi,
                )
            elif tool_name == "query_order":
                result = await order.query_order(
                    tool_input.get("order_id", ""),
                    email=tool_input.get("email") or user_email,
                )
            elif tool_name == "query_my_orders":
                if not user_id:
                    return {
                        "success": False,
                        "error": "Please log in to view your orders.",
                        "login_required": True,
                    }
                result = await order.list_my_orders(user_id=user_id, email=user_email)
            elif tool_name == "request_human_agent":
                result = await handoff.request_human_agent(
                    tool_input.get("reason", ""),
                    session_id=session_id,
                    user_id=user_id,
                    db=db,
                    sessions=sessions,
                )
            else:
                return {"success": False, "error": "Unknown tool"}

            return result.to_dict()
        finally:
            TOOL_LATENCY.labels(tool_name=tool_name).observe(time.perf_counter() - start)

    async def _get_context(
        self,
        session_id: str | None,
        db: AsyncSession | None,
        sessions: SessionService | None,
    ) -> list[dict[str, str]]:
        if not session_id or not db or not sessions:
            return []
        return await sessions.get_context_messages(db, session_id)

    async def _run_react(
        self,
        question: str,
        context: list[dict[str, str]],
        *,
        session_id: str | None = None,
        db: AsyncSession | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
        sessions: SessionService | None = None,
    ) -> list[ToolStep]:
        settings = get_settings()
        steps: list[ToolStep] = []
        react_messages: list[dict] = [
            {
                "role": "system",
                "content": f"{REACT_SYSTEM_HINT}\n{TOOL_SELECTION_HINT}",
            },
        ]
        if context:
            react_messages.extend(context[-4:])
        react_messages.append({"role": "user", "content": question})

        for _ in range(settings.agent_max_steps):
            message = await self.kimi.chat(
                react_messages,
                tools=get_openai_tools(),
                tool_choice="auto",
            )
            if isinstance(message, str) or not getattr(message, "tool_calls", None):
                break

            calls = message.tool_calls
            react_messages.append(build_assistant_tool_message_multi(message))

            async def _invoke(call):
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                logger.info("react_tool_step", tool=name, session_id=session_id)
                TOOL_SELECTION.labels(tool_name=name).inc()
                tool_result = await self._call_tool(
                    name,
                    args,
                    session_id=session_id,
                    db=db,
                    user_id=user_id,
                    user_email=user_email,
                    sessions=sessions,
                )
                return call, name, args, tool_result

            if len(calls) == 1:
                results = [await _invoke(calls[0])]
            else:
                results = list(await asyncio.gather(*[_invoke(c) for c in calls]))

            for call, name, args, tool_result in results:
                steps.append(ToolStep(name, args, tool_result))
                react_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

            if any(r[1] in _TERMINAL_TOOLS for r in results):
                break

        return steps

    def _steps_payload(self, steps: list[ToolStep]) -> list[dict]:
        return [
            {
                "tool": s.tool_name,
                "input": s.tool_input,
                "result": s.tool_result,
            }
            for s in steps
        ]

    async def _build_handoff_plan(
        self,
        question: str,
        *,
        session_id: str | None,
        db: AsyncSession | None,
        user_id: str | None,
        sessions: SessionService | None,
    ) -> TurnPlan | None:
        if not is_transfer_to_human(question):
            return None
        result = await handoff.request_human_agent(
            question,
            session_id=session_id,
            user_id=user_id,
            db=db,
            sessions=sessions,
        )
        data = result.data or {}
        answer = data.get("message", "")
        if not answer and result.success:
            answer = "已为您转接人工客服，请稍候。"
        if not result.success:
            answer = result.error or "转人工失败，请稍后重试。"
        return TurnPlan(
            kind=TurnKind.HANDOFF,
            answer=answer,
            tool_name="request_human_agent",
            tool_result=result.to_dict(),
            tools_used=["request_human_agent"],
            handoff=result.success,
            session_status="waiting_human" if result.success else None,
            question=question,
        )

    def _plan_from_steps(
        self,
        question: str,
        context: list[dict[str, str]],
        steps: list[ToolStep],
    ) -> TurnPlan:
        if not steps:
            return TurnPlan(
                kind=TurnKind.DIRECT,
                context=context,
                question=question,
            )

        tools_used = [s.tool_name for s in steps]
        citations = _collect_citations(steps)
        is_handoff = "request_human_agent" in tools_used

        if len(steps) == 1 and steps[0].tool_name in _TERMINAL_TOOLS:
            data = steps[0].tool_result.get("data", {})
            answer = data.get("answer") or data.get("message", "")
            if steps[0].tool_name == "request_human_agent":
                return TurnPlan(
                    kind=TurnKind.HANDOFF,
                    answer=answer,
                    tool_name=steps[0].tool_name,
                    tool_result=steps[0].tool_result,
                    tools_used=tools_used,
                    steps=steps,
                    handoff=bool(steps[0].tool_result.get("success")),
                    session_status="waiting_human",
                    question=question,
                    context=context,
                )
            if answer and steps[0].tool_name == "customer_chat":
                return TurnPlan(
                    kind=TurnKind.FAQ,
                    answer=answer,
                    tool_name=steps[0].tool_name,
                    tool_result=steps[0].tool_result,
                    citations=citations,
                    tools_used=tools_used,
                    steps=steps,
                    stream_rag=True,
                    rag_query=steps[0].tool_input.get("query", question),
                    question=question,
                    context=context,
                )
            if answer and steps[0].tool_name == "create_return_request":
                query = f"退换货退货退款政策: {steps[0].tool_input.get('query', question)}"
                if steps[0].tool_input.get("order_id"):
                    query = f"{query} 订单号: {steps[0].tool_input['order_id']}"
                return TurnPlan(
                    kind=TurnKind.FAQ,
                    answer=answer,
                    tool_name=steps[0].tool_name,
                    tool_result=steps[0].tool_result,
                    citations=citations,
                    tools_used=tools_used,
                    steps=steps,
                    stream_rag=True,
                    rag_query=query,
                    question=question,
                    context=context,
                )

        return TurnPlan(
            kind=TurnKind.TOOLS,
            tool_name=tools_used[-1] if tools_used else None,
            tool_result=steps[-1].tool_result if steps else None,
            citations=citations,
            tools_used=tools_used,
            steps=steps,
            context=context,
            question=question,
            handoff=is_handoff,
            session_status="waiting_human" if is_handoff else None,
        )

    async def _try_rule_tool_shortcut(
        self,
        question: str,
        *,
        context: list[dict[str, str]],
        db: AsyncSession | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
        session_id: str | None = None,
    ) -> TurnPlan | None:
        """规则快捷路径：识别到明确的订单/物流/我的订单意图时，直接调用本地工具，
        并用模板生成回答，完全不调用大模型，避免 RPM 限流。"""
        import re

        q = question or ""
        m_ord = re.search(r"\bORD[-\s]*(\d{3,})\b", q, re.I)
        m_log = re.search(r"\b((?:ARX|DHL|SF|YT)\s*[-\w]*\d{6,})\b", q, re.I)
        wants_logistics = bool(
            re.search(r"物流|快递|运单|到哪|运输|发货|track|logistic|进度", q, re.I)
        )
        wants_my_orders = bool(
            re.search(r"我的订单|全部订单|我的包裹|my\s+orders|所有订单", q, re.I)
        )

        # 若整条消息只是一个裸订单号/运单号（没有"查/物流/到哪"等动作词），
        # 通常是在回答客服提问（如退货流程中提供订单号），不截胡，交还原对话流程。
        _bare = re.sub(r"(ORD[-\s]*\d{3,})|((?:ARX|DHL|SF|YT)\s*[-\w]*\d{6,})", "", q, flags=re.I)
        _bare = re.sub(r"[\s,，。.!！?？、~]", "", _bare)
        if len(_bare) < 2:
            return None

        steps: list[ToolStep] = []

        if m_log and not m_ord:
            num = re.sub(r"\s+", "", m_log.group(1))
            r = await self._call_tool(
                "fetch_logistics_information",
                {"logistics_number": num},
                session_id=session_id,
                db=db,
                user_id=user_id,
                user_email=user_email,
            )
            steps.append(
                ToolStep("fetch_logistics_information", {"logistics_number": num}, r)
            )
        elif m_ord:
            oid = "ORD-" + m_ord.group(1)
            r = await self._call_tool(
                "query_order",
                {"order_id": oid},
                session_id=session_id,
                db=db,
                user_id=user_id,
                user_email=user_email,
            )
            steps.append(ToolStep("query_order", {"order_id": oid}, r))
            if wants_logistics and r.get("success"):
                track = (r.get("data") or {}).get("tracking_number") or ""
                if track:
                    r2 = await self._call_tool(
                        "fetch_logistics_information",
                        {"logistics_number": track},
                        session_id=session_id,
                        db=db,
                        user_id=user_id,
                        user_email=user_email,
                    )
                    steps.append(
                        ToolStep(
                            "fetch_logistics_information",
                            {"logistics_number": track},
                            r2,
                        )
                    )
        elif wants_my_orders:
            r = await self._call_tool(
                "query_my_orders",
                {},
                session_id=session_id,
                db=db,
                user_id=user_id,
                user_email=user_email,
            )
            steps.append(ToolStep("query_my_orders", {}, r))
        else:
            return None

        payload = self._steps_payload(steps)
        answer = format_tool_steps_answer(question, payload)
        answer = sanitize_assistant_reply(answer) or "抱歉，暂时无法为您查询到相关信息，请稍后再试。"
        logger.info(
            "rule_tool_shortcut",
            tools=[s.tool_name for s in steps],
            question_preview=q[:80],
        )
        return TurnPlan(
            kind=TurnKind.WORKFLOW,
            answer=answer,
            tool_name=steps[-1].tool_name,
            tool_result=steps[-1].tool_result,
            citations=_collect_citations(steps),
            tools_used=[s.tool_name for s in steps],
            steps=steps,
            context=context,
            question=question,
        )

    async def _resolve_turn(
        self,
        question: str,
        *,
        session_id: str | None = None,
        db: AsyncSession | None = None,
        sessions: SessionService | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
    ) -> TurnPlan:
        context = await self._get_context(session_id, db, sessions)

        if is_greeting(question):
            return TurnPlan(
                kind=TurnKind.GREETING,
                context=context,
                question=question,
            )

        workflow_response = await try_handle_return_workflow(
            question, self, sessions, session_id
        )
        if workflow_response is not None:
            return TurnPlan(
                kind=TurnKind.WORKFLOW,
                answer=workflow_response.answer,
                tool_name=workflow_response.tool_name,
                citations=workflow_response.citations,
                tools_used=workflow_response.tools_used,
                question=question,
                context=context,
            )

        handoff_plan = await self._build_handoff_plan(
            question,
            session_id=session_id,
            db=db,
            user_id=user_id,
            sessions=sessions,
        )
        if handoff_plan is not None:
            handoff_plan.context = context
            return handoff_plan

        if is_simple_faq(question):
            logger.info("faq_fast_path", question_preview=question[:80])
            return TurnPlan(
                kind=TurnKind.FAQ,
                tool_name="customer_chat",
                tools_used=["customer_chat"],
                stream_rag=True,
                rag_query=question,
                question=question,
                context=context,
            )

        shortcut = await self._try_rule_tool_shortcut(
            question,
            context=context,
            db=db,
            user_id=user_id,
            user_email=user_email,
            session_id=session_id,
        )
        if shortcut is not None:
            return shortcut

        steps = await self._run_react(
            question,
            context,
            session_id=session_id,
            db=db,
            user_id=user_id,
            user_email=user_email,
            sessions=sessions,
        )
        return self._plan_from_steps(question, context, steps)

    async def _synthesize_tools_answer(self, plan: TurnPlan) -> str:
        payload = self._steps_payload(plan.steps)
        answer = await self.kimi.synthesize_multi_answer(
            plan.question, payload, context=plan.context
        )
        answer = sanitize_assistant_reply(answer)
        if not answer:
            answer = format_tool_steps_answer(plan.question, payload)
        return answer

    def _to_response(self, plan: TurnPlan, answer: str) -> AgentResponse:
        return AgentResponse(
            answer=answer,
            tool_name=plan.tool_name,
            tool_result=plan.tool_result,
            citations=plan.citations,
            tools_used=plan.tools_used,
            handoff=plan.handoff,
            session_status=plan.session_status,
        )

    async def process(
        self,
        question: str,
        session_id: str | None = None,
        db: AsyncSession | None = None,
        sessions: SessionService | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
        profile_id: str | None = None,
    ) -> AgentResponse:
        with trace_span(
            "agent.process",
            session_id=session_id or "",
            user_id=user_id or "",
        ):
            plan = await self._resolve_turn(
                question,
                session_id=session_id,
                db=db,
                sessions=sessions,
                user_id=user_id,
                user_email=user_email,
            )

            if plan.kind == TurnKind.GREETING:
                answer = await self.kimi.chat(build_greeting_messages(question))
                if not isinstance(answer, str):
                    answer = getattr(answer, "content", "") or ""
                return self._to_response(plan, answer)

            if plan.kind in (TurnKind.WORKFLOW, TurnKind.HANDOFF):
                return self._to_response(plan, plan.answer)

            if plan.kind == TurnKind.FAQ:
                if plan.answer:
                    return self._to_response(plan, plan.answer)
                result = await knowledge_chat.customer_chat(
                    plan.rag_query or question,
                    self.retriever,
                    qwen=self.qwen,
                    kimi=self.kimi,
                )
                answer = result.data.get("answer", "")
                plan.citations = result.citations or plan.citations
                plan.tool_result = result.to_dict()
                return self._to_response(plan, answer)

            if plan.kind == TurnKind.DIRECT:
                messages: list[dict] = [
                    {"role": "system", "content": AGENT_SYSTEM_PROMPT}
                ]
                messages.extend(plan.context[-6:])
                messages.append({"role": "user", "content": question})
                answer = await self.kimi.chat(messages)
                if not isinstance(answer, str):
                    answer = getattr(answer, "content", "") or ""
                return self._to_response(plan, answer)

            answer = await self._synthesize_tools_answer(plan)
            return self._to_response(plan, answer)

    async def process_stream(
        self,
        question: str,
        session_id: str | None = None,
        db: AsyncSession | None = None,
        sessions: SessionService | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
        profile_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        with trace_span(
            "agent.process_stream",
            session_id=session_id or "",
            user_id=user_id or "",
        ):
            yield _status_event("thinking")

            plan = await self._resolve_turn(
                question,
                session_id=session_id,
                db=db,
                sessions=sessions,
                user_id=user_id,
                user_email=user_email,
            )
            parts: list[str] = []

            async def _emit_done(answer: str) -> AsyncIterator[dict[str, Any]]:
                yield _done_event(
                    answer,
                    tool_name=plan.tool_name,
                    citations=plan.citations,
                    tools_used=plan.tools_used,
                    handoff=plan.handoff,
                    session_status=plan.session_status,
                )

            if plan.kind == TurnKind.GREETING:
                async for token in self.kimi.chat_stream(
                    build_greeting_messages(question)
                ):
                    parts.append(token)
                    yield {"type": "chunk", "content": token}
                async for event in _emit_done("".join(parts)):
                    yield event
                return

            if plan.kind in (TurnKind.WORKFLOW, TurnKind.HANDOFF):
                for chunk in _chunk_text(plan.answer):
                    parts.append(chunk)
                    yield {"type": "chunk", "content": chunk}
                async for event in _emit_done(plan.answer):
                    yield event
                return

            if plan.kind == TurnKind.FAQ and plan.stream_rag:
                citations, token_stream = await knowledge_chat.customer_chat_stream(
                    plan.rag_query or question,
                    self.retriever,
                    qwen=self.qwen,
                    kimi=self.kimi,
                )
                if citations:
                    plan.citations = citations
                yield _status_event("searching")
                async for token in token_stream:
                    parts.append(token)
                    yield {"type": "chunk", "content": token}
                async for event in _emit_done("".join(parts)):
                    yield event
                return

            if plan.kind == TurnKind.FAQ:
                for chunk in _chunk_text(plan.answer):
                    parts.append(chunk)
                    yield {"type": "chunk", "content": chunk}
                async for event in _emit_done(plan.answer):
                    yield event
                return

            if plan.kind == TurnKind.DIRECT:
                messages: list[dict] = [
                    {"role": "system", "content": AGENT_SYSTEM_PROMPT}
                ]
                messages.extend(plan.context[-6:])
                messages.append({"role": "user", "content": question})
                async for token in self.kimi.chat_stream(messages):
                    parts.append(token)
                    yield {"type": "chunk", "content": token}
                async for event in _emit_done("".join(parts)):
                    yield event
                return

            payload = self._steps_payload(plan.steps)
            async for token in self.kimi.synthesize_multi_stream(
                question, payload, context=plan.context
            ):
                parts.append(token)
                yield {"type": "chunk", "content": token}
            answer_text = sanitize_assistant_reply("".join(parts))
            if not answer_text:
                fallback = format_tool_steps_answer(question, payload)
                if fallback:
                    parts = [fallback]
                    yield {"type": "chunk", "content": fallback}
                    answer_text = fallback
            async for event in _emit_done(answer_text or "".join(parts)):
                yield event
