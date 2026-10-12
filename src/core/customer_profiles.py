"""智能客服多模型 profile 定义。

三个 profile 对应三个微调模型：
- c1: Qwen3.5-2B + qwen35_2b_lora (v1)
- c2: Qwen3.5-2B + qwen35_2b_lora_v2
- c3: OpenBMB/MiniCPM-V-4.6 + OpenBMB_MiniCPM_lora

当前阶段：本地基座模型未下载、本地推理栈未安装，三个 profile 暂时都走云端
Kimi，但使用不同的 system prompt 区分人设与回答风格。待本地环境就绪后，
可在 agent_service 中按 profile_id 切换到对应的本地 LoRA 推理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.core.config import PROJECT_ROOT


@dataclass(frozen=True)
class CustomerProfile:
    profile_id: str
    name: str
    description: str
    base_model: str
    lora_path: str | None = None
    system_prompt: str = ""
    # 本地模型是否已就绪（基座已下载 + 推理栈已装）。当前 False，走云端。
    local_ready: bool = False


def _models_dir() -> Path:
    return PROJECT_ROOT / "models"


PROFILES: dict[str, CustomerProfile] = {
    "c1": CustomerProfile(
        profile_id="c1",
        name="智能客服1",
        description="Qwen3.5-2B + v1 LoRA · 标准客服",
        base_model="Qwen/Qwen3.5-2B",
        lora_path=str(_models_dir() / "qwen35_2b_lora"),
        system_prompt=(
            "你是跨境电商平台的标准智能客服，语气专业、简洁、礼貌。"
            "回答以解决用户问题为首要目标，先说结论再给细节。"
        ),
    ),
    "c2": CustomerProfile(
        profile_id="c2",
        name="智能客服2",
        description="Qwen3.5-2B + v2 LoRA · 热情导购",
        base_model="Qwen/Qwen3.5-2B",
        lora_path=str(_models_dir() / "qwen35_2b_lora_v2"),
        system_prompt=(
            "你是跨境电商平台的热情导购型客服，语气亲切、主动、有亲和力。"
            "在回答问题之余，可主动给出相关商品建议或优惠提示，但不要过度推销。"
        ),
    ),
    "c3": CustomerProfile(
        profile_id="c3",
        name="智能客服3",
        description="MiniCPM-V-4.6 + LoRA · 严谨专员",
        base_model="OpenBMB/MiniCPM-V-4.6",
        lora_path=str(_models_dir() / "OpenBMB_MiniCPM_lora"),
        system_prompt=(
            "你是跨境电商平台的售后严谨专员，回答严谨、重证据、按政策办事。"
            "涉及退换货、质保、退款时，严格引用平台政策条款，不做超出政策的承诺。"
        ),
    ),
}

DEFAULT_PROFILE_ID = "c1"


def get_profile(profile_id: str | None) -> CustomerProfile:
    if profile_id and profile_id in PROFILES:
        return PROFILES[profile_id]
    return PROFILES[DEFAULT_PROFILE_ID]


def list_profiles() -> list[dict]:
    return [
        {
            "profile_id": p.profile_id,
            "name": p.name,
            "description": p.description,
            "local_ready": p.local_ready,
        }
        for p in PROFILES.values()
    ]
