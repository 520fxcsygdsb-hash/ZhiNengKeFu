"""Text helpers for model output sanitization."""

from __future__ import annotations

import re

_LT, _GT = chr(60), chr(62)
_OPEN_THINK = _LT + "think" + _GT
_CLOSE_THINK = _LT + "/think" + _GT
_OPEN_RT = _LT + "redacted_thinking" + _GT
_CLOSE_RT = _LT + "/redacted_thinking" + _GT

# Kimi / reasoning models may emit think blocks in various tag styles.
_THINK_BLOCK_RE = re.compile(
    r"`[\s\S]*?`"
    + "|"
    + re.escape(_OPEN_THINK)
    + r"[\s\S]*?"
    + re.escape(_CLOSE_THINK)
    + "|"
    + re.escape(_OPEN_RT)
    + r"[\s\S]*?"
    + re.escape(_CLOSE_RT)
    + "|"
    + re.escape(_OPEN_THINK)
    + r"[\s\S]*?"
    + re.escape(_CLOSE_RT)
    + "|"
    + re.escape(_OPEN_RT)
    + r"[\s\S]*?"
    + re.escape(_CLOSE_RT),
    re.IGNORECASE,
)
_THINK_OPEN_RE = re.compile(
    r"`[\s\S]*$"
    + "|"
    + re.escape(_OPEN_THINK)
    + r"[\s\S]*$"
    + "|"
    + re.escape(_OPEN_RT)
    + r"[\s\S]*$",
    re.IGNORECASE,
)
# Local Qwen may continue generating fake multi-turn dialogue after the real answer.
_LEAKED_TURN_RE = re.compile(
    r"\n(?:user|assistant)\s*(?:\n|$)|<\|im_start\|>(?:user|assistant)\b",
    re.IGNORECASE,
)

_FENCE_RE = re.compile(r"```[\w+-]*\n?([\s\S]*?)```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC_RE = re.compile(
    r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)"
)
_LIST_RE = re.compile(r"(?m)^\s{0,3}(?:[-*+]|\d+\.)\s+")
_HR_RE = re.compile(r"(?m)^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

PLAIN_TEXT_REPLY_RULE = (
    "用正常文字回复，不要使用 Markdown 格式。"
    "禁止使用加粗、标题、列表符号、代码块、链接语法等。"
    "Reply in plain natural language only. Do not use Markdown "
    "(no bold, headings, bullet lists, code fences, or link syntax)."
)


def strip_think_blocks(text: str) -> str:
    """Remove model reasoning blocks from user-visible reply text."""
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    return cleaned.strip()


def strip_leaked_dialogue(text: str) -> str:
    """Truncate fabricated follow-up turns (user/assistant) appended after the answer."""
    if not text:
        return ""
    match = _LEAKED_TURN_RE.search(text)
    if match:
        return text[: match.start()].strip()
    return text.strip()


def strip_markdown(text: str) -> str:
    """Convert common Markdown markup into plain readable text."""
    if not text:
        return ""
    cleaned = _FENCE_RE.sub(r"\1", text)
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)
    cleaned = _LINK_RE.sub(r"\1（\2）", cleaned)
    cleaned = _HEADING_RE.sub("", cleaned)
    cleaned = _HR_RE.sub("", cleaned)
    cleaned = _BOLD_RE.sub(r"\2", cleaned)
    cleaned = _ITALIC_RE.sub(lambda m: m.group(1) or m.group(2) or "", cleaned)
    cleaned = _LIST_RE.sub("", cleaned)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def sanitize_assistant_reply(text: str) -> str:
    """Full cleanup for assistant messages shown to users."""
    return strip_markdown(strip_leaked_dialogue(strip_think_blocks(text)))
