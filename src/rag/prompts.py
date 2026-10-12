import re

LANGUAGE_MATCH_INSTRUCTION = (
    "你是跨境电商智能客服。"
    "始终使用与用户相同的语言回复（用户用英文则英文，用中文则中文，用阿拉伯语则阿拉伯语，以此类推）。"
    "You are a cross-border e-commerce assistant. "
    "Always respond in the same language as the user's message."
)

_PINYIN_GREETING_HINT = (
    "常见拼音问候等同于中文：nihao→你好，xiexie→谢谢，zaoshanghao→早上好。"
)

AGENT_SYSTEM_PROMPT = (
    f"{LANGUAGE_MATCH_INSTRUCTION}\n"
    f"{_PINYIN_GREETING_HINT}\n"
    "若用户仅为问候（中文、英文或拼音形式），友好回复即可，不要查询知识库。"
    "用正常文字回复，不要使用 Markdown（不要加粗、标题、列表符号、代码块）。"
)

TOOL_SELECTION_FEW_SHOT = """
边界示例（仅供判断，不要复述示例原文）：
- 用户: "你好" → 不调用工具（纯问候）
- 用户: "你好，手机保修多久？" → customer_chat（问候+咨询，以咨询为主）
- 用户: "我要退货" → create_return_request（退换货诉求，不是投诉）
- 用户: "客服态度太差了" → record_user_complaint（服务质量投诉）
- 用户: "我的订单到哪了？"（已登录）→ query_my_orders；若返回 tracking_number 且问物流，可同时 fetch_logistics_information
- 用户: "查订单 ORD-1001 物流" → 可同时 query_order 与 fetch_logistics_information（若已知单号则直接查物流）
"""

TOOL_SELECTION_HINT = (
    f"{_PINYIN_GREETING_HINT}\n"
    "若用户消息仅为问候（如 你好、hello、hi、nihao），不要调用任何工具，"
    "直接输出 {\"tool\": null}。"
    "不要将问候语当作产品或政策咨询传给 customer_chat。"
    "若用户要退货、退款、换货或申请退换货（如 帮我退一下货、我要退款），"
    "使用 create_return_request，不要使用 record_user_complaint。"
    "record_user_complaint 仅用于服务质量投诉（如态度差、未收到货），"
    "不用于退换货政策咨询或退货申请。"
    "若用户问「我的订单」「my orders」且已登录，使用 query_my_orders。"
    "若用户明确要求转人工、人工客服、真人客服，使用 request_human_agent。"
    "复杂问题可连续调用多个工具；若需订单与物流，可在同一轮并行调用 query_order 与 fetch_logistics_information。"
    f"{TOOL_SELECTION_FEW_SHOT}"
)

REACT_SYSTEM_HINT = (
    "You are a cross-border customer service agent with tools. "
    "Use tools step by step until you have enough information to answer. "
    "After query_order or query_my_orders returns a tracking_number, "
    "call fetch_logistics_information with that number if user asks about shipping. "
    "When no more tools are needed, stop calling tools."
)

_GREETING_RE = re.compile(
    r"^(?:"
    r"你好|您好|哈喽|嗨|嗨喽|"
    r"hello|hi|hey|howdy|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"nihao|ni\s*hao|nǐ\s*hǎo|"
    r"你好啊|早上好|下午好|晚上好|"
    r"thanks|thank\s+you|xiexie|xie\s*xie|"
    r"مرحبا|السلام\s*عليكم|أهلا"
    r")[\s!.?，,~！]*$",
    re.IGNORECASE,
)


def is_greeting(text: str) -> bool:
    return bool(_GREETING_RE.match(text.strip()))


_ORDER_ID_RE = re.compile(r"\b(ORD-[A-Z0-9]+)\b", re.IGNORECASE)
_JD_ORDER_ID_RE = re.compile(r"\b(\d{10,18})\b")

_TRANSFER_HUMAN_RE = re.compile(
    r"(?:"
    r"转人工|人工客服|找人工|要人工|联系人工|真人客服|"
    r"human\s+agent|transfer\s+to\s+human|speak\s+to\s+(?:a\s+)?human|"
    r"live\s+agent|real\s+person"
    r")",
    re.IGNORECASE,
)

_RETURN_POLICY_RE = re.compile(
    r"(?:"
    r"退货政策|退款政策|退换货政策|退换政策|"
    r"怎么退|如何退|能否退|可以退吗|能退吗|"
    r"return\s+policy|refund\s+policy|how\s+(?:do\s+)?(?:i\s+)?return|can\s+i\s+return"
    r")",
    re.IGNORECASE,
)

_RETURN_ACTION_RE = re.compile(
    r"(?:"
    r"(?:我要|帮我|申请|想要|办理).{0,8}(?:退|换)|"
    r"(?:i\s+)?(?:want|need)\s+to\s+(?:return|refund|exchange)|"
    r"(?:process|apply\s+for)\s+(?:a\s+)?(?:return|refund)|"
    r"^(?:退[款货]|换货|退款|退货)[了啦吗]?$|"
    r"^(?:return|refund)(?:\s+please)?[.!?]?$"
    r")",
    re.IGNORECASE,
)

_COMPLAINT_RE = re.compile(
    r"(?:投诉|态度差|服务差|未收到货|没收到|太差了|不满意|"
    r"complaint|poor\s+service|terrible\s+service|never\s+received)",
    re.IGNORECASE,
)

_ORDER_QUERY_RE = re.compile(
    r"(?:我的订单|查订单|订单状态|订单号|订单到哪|"
    r"my\s+orders?|order\s+status|track\s+my\s+order|where\s+is\s+my\s+order)",
    re.IGNORECASE,
)

_LOGISTICS_QUERY_RE = re.compile(
    r"(?:物流单号|运单号|快递单号|查物流|物流到哪|包裹到哪|"
    r"tracking\s+number|track\s+(?:my\s+)?(?:package|shipment)|where\s+is\s+my\s+package)",
    re.IGNORECASE,
)

_FAQ_TOPIC_RE = re.compile(
    r"(?:"
    r"质保|保修|warranty|"
    r"退货|退款|退换|return|refund|"
    r"物流|运费|配送|shipping|delivery|"
    r"清关|海关|customs|"
    r"支付|付款|货币|payment|currency|"
    r"海湾|gulf|gcc|"
    r"营业|客服|热线|邮箱|contact|hours|hotline|"
    r"政策|流程|规定|faq|"
    r"多久|多长时间|怎么办|如何|怎么|是什么|什么是|"
    r"how\s+long|how\s+to|what\s+is|what\s+are"
    r")",
    re.IGNORECASE,
)

_QUESTION_RE = re.compile(
    r"(?:[?？]|吗[?？]?|呢[?？]?|么[?？]?|"
    r"\b(?:what|how|when|where|why|which|can|do|does|is|are)\b)",
    re.IGNORECASE,
)


def is_transfer_to_human(text: str) -> bool:
    return bool(_TRANSFER_HUMAN_RE.search(text.strip()))


def extract_order_id(message: str) -> str | None:
    """Extract ORD-* or JD numeric order id from free text."""
    match = _ORDER_ID_RE.search(message)
    if match:
        return match.group(1).upper()
    match = _JD_ORDER_ID_RE.search(message)
    if match:
        return match.group(1)
    return None


def _is_return_action_intent(message: str) -> bool:
    if _RETURN_POLICY_RE.search(message):
        return False
    return bool(_RETURN_ACTION_RE.search(message.strip()))


def _has_tool_routing_signals(message: str) -> bool:
    text = message.strip()
    if extract_order_id(text):
        return True
    if is_transfer_to_human(text):
        return True
    if _is_return_action_intent(text):
        return True
    if _COMPLAINT_RE.search(text):
        return True
    if _ORDER_QUERY_RE.search(text):
        return True
    if _LOGISTICS_QUERY_RE.search(text):
        return True
    return False


def is_simple_faq(text: str) -> bool:
    """
  True when the message is a single-topic knowledge/FAQ question that can skip
  ReAct tool selection and go straight to customer_chat RAG.
  """
    if is_greeting(text):
        return False
    stripped = text.strip()
    if not stripped or len(stripped) > 400:
        return False
    if _has_tool_routing_signals(stripped):
        return False
    if _FAQ_TOPIC_RE.search(stripped):
        return True
    return bool(_QUESTION_RE.search(stripped))


def build_greeting_messages(text: str) -> list[dict]:
    lang = detect_user_language(text)
    if lang == "en":
        system = (
            "You are a cross-border e-commerce customer service assistant. "
            "The user sent a short greeting. Reply warmly in English only. "
            "Do not use Chinese. Do not query or cite the knowledge base. "
            "Reply in plain text only, no Markdown."
        )
    elif lang == "ar":
        system = (
            "أنت مساعد خدمة عملاء للتجارة الإلكترونية عبر الحدود. "
            "رد بتحية دافئة بالعربية فقط. لا تستخدم لغات أخرى."
        )
    else:
        system = AGENT_SYSTEM_PROMPT
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text.strip()},
    ]


def detect_user_language(text: str) -> str:
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[a-zA-Z]", text):
        return "en"
    return "zh"


def language_reply_instruction(lang: str) -> str:
    if lang == "en":
        return (
            "The user wrote in English. You MUST reply entirely in English. "
            "Translate or summarize any Chinese knowledge into English."
        )
    if lang == "ar":
        return (
            "The user wrote in Arabic. You MUST reply entirely in Arabic. "
            "Translate or summarize any knowledge into Arabic."
        )
    return LANGUAGE_MATCH_INSTRUCTION

RAG_SYSTEM_PROMPT = """你是一个跨境智能客服，请根据以下知识回答用户问题。

知识内容：
{informations}

要求：
1. 只能依据上述知识回答
2. 找不到对应内容时，用与用户相同的语言告知无法找到
3. 不要回答参考资料之外的内容
4. 知识库含中文、英文、阿拉伯语文档；优先采用与用户语言一致的片段，其余内容翻译后再作答
5. 最终回复只能使用一种语言（与用户相同），不得在回复中夹杂其他语言
6. 只输出对用户当前问题的直接回答，不要输出对话历史、多轮格式或 user/assistant 角色标记
7. 用正常文字回复，不要使用 Markdown（禁止加粗、标题、列表符号、代码块、链接语法）
8. {language_instruction}
"""


def build_rag_messages(query: str, informations: list[str]) -> list[dict]:
    info_text = "\n---\n".join(informations)
    lang = detect_user_language(query)
    lang_instruction = language_reply_instruction(lang)
    user_content = query
    if lang == "en":
        user_content = f"Answer in English only.\n\n{query}"
    elif lang == "ar":
        user_content = f"Answer in Arabic only.\n\n{query}"
    return [
        {
            "role": "system",
            "content": RAG_SYSTEM_PROMPT.format(
                informations=info_text,
                language_instruction=lang_instruction,
            ),
        },
        {"role": "user", "content": user_content},
    ]
