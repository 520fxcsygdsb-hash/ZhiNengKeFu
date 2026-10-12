from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.core.security import verify_api_key

router = APIRouter(tags=["inference"])


class InferenceRequest(BaseModel):
    messages: list[dict[str, str]] = Field(..., min_length=1)
    max_new_tokens: int | None = None


class InferenceResponse(BaseModel):
    answer: str


@router.post("/inference", response_model=InferenceResponse)
async def inference(
    request: Request,
    body: InferenceRequest,
    _: Annotated[str, Depends(verify_api_key)] = ...,
):
    # 优先使用云端 Kimi（Moonshot），本地 Qwen 仅作回退
    agent = getattr(request.app.state, "agent_service", None)
    kimi = getattr(agent, "kimi", None) if agent is not None else None

    # kimi-k2.6 是推理模型，思考本身会消耗大量 token，
    # 若 max_tokens 太小会出现"思考把额度用完、正式输出为空"的情况。
    # 因此给一个足够大的下限，保证正式回答有 token 可用。
    max_tokens = body.max_new_tokens or 2048
    if max_tokens < 1500:
        max_tokens = 2048

    if kimi is not None:
        try:
            answer = await kimi.chat(body.messages, max_tokens=max_tokens)
            if not isinstance(answer, str):
                answer = getattr(answer, "content", "") or ""
            if not answer:
                answer = "（模型思考后未返回正式内容，请换个问法再试）"
            return InferenceResponse(answer=answer)
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Kimi inference failed: {exc}"
            ) from exc

    qwen = getattr(request.app.state, "qwen_service", None)
    if qwen is None:
        raise HTTPException(
            status_code=503,
            detail="No inference backend available (Kimi not configured and local Qwen not loaded)",
        )

    try:
        answer = await qwen.generate_from_messages(body.messages)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Inference failed: {exc}") from exc

    return InferenceResponse(answer=answer)
