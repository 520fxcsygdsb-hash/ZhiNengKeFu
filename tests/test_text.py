from src.utils.text import sanitize_assistant_reply, strip_markdown


def test_strip_markdown_bold_and_heading():
    text = "## 质保说明\n手机保修 **12个月**。"
    assert strip_markdown(text) == "质保说明\n手机保修 12个月。"


def test_strip_markdown_list_and_link():
    text = "- 第一步\n- 第二步\n详见 [官网](https://example.com)"
    cleaned = strip_markdown(text)
    assert "*" not in cleaned
    assert "-" not in cleaned.split("\n")[0]
    assert "第一步" in cleaned
    assert "官网" in cleaned
    assert "[" not in cleaned


def test_sanitize_assistant_reply_strips_markdown():
    text = "您好，**订单已发货**。\n\n1. 等待签收\n2. 确认收货"
    cleaned = sanitize_assistant_reply(text)
    assert "**" not in cleaned
    assert "订单已发货" in cleaned
    assert "等待签收" in cleaned
