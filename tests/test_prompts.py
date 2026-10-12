from src.rag.prompts import (
    extract_order_id,
    is_greeting,
    is_simple_faq,
    is_transfer_to_human,
)


def test_greeting_chinese():
    assert is_greeting("你好")
    assert is_greeting("早上好！")


def test_greeting_english():
    assert is_greeting("hello")
    assert is_greeting("Hi!")


def test_not_greeting():
    assert not is_greeting("手机保修多久？")
    assert not is_greeting("我要退货")


def test_greeting_plus_question_not_pure_greeting():
    assert not is_greeting("你好，质保政策是什么？")


def test_simple_faq_policy_questions():
    assert is_simple_faq("手机保修多久？")
    assert is_simple_faq("退货政策是什么")
    assert is_simple_faq("跨境物流要多久？")
    assert is_simple_faq("How long is the warranty?")
    assert is_simple_faq("你好，质保政策是什么？")


def test_simple_faq_excludes_actions():
    assert not is_simple_faq("我要退货")
    assert not is_simple_faq("帮我退款")
    assert not is_simple_faq("查订单 ORD-1001")
    assert not is_simple_faq("我的订单到哪了")
    assert not is_simple_faq("客服态度太差了")
    assert not is_simple_faq("物流单号 DHL123456")
    assert not is_simple_faq("你好")
    assert not is_simple_faq("转人工")
    assert not is_simple_faq("转人工客服")


def test_transfer_to_human():
    assert is_transfer_to_human("转人工")
    assert is_transfer_to_human("我想找人工客服")
    assert is_transfer_to_human("transfer to human")
    assert not is_transfer_to_human("手机保修多久？")


def test_extract_order_id():
    assert extract_order_id("查一下 ORD-1001") == "ORD-1001"
    assert extract_order_id("京东订单 123456789012") == "123456789012"
    assert extract_order_id("没有单号") is None
