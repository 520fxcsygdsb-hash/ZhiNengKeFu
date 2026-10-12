"""Tests for JD order client helpers."""

from src.integrations.jd_client import build_jd_sign, normalize_jd_order


def test_build_jd_sign_is_stable():
    params = {
        "method": "jingdong.pop.order.get",
        "app_key": "key",
        "timestamp": "2024-01-01 00:00:00",
        "v": "2.0",
        "360buy_param_json": '{"order_id":"1"}',
    }
    sign1 = build_jd_sign(params, "secret")
    sign2 = build_jd_sign(params, "secret")
    assert sign1 == sign2
    assert len(sign1) == 32
    assert sign1 == sign1.upper()


def test_normalize_jd_order_maps_fields():
    raw = {
        "orderId": "123456789012",
        "orderState": "WAIT_GOODS_RECEIVE_CONFIRM",
        "waybill": "JDVA999",
        "orderTotalPrice": "88.5",
        "created": "2024-07-10 12:00:00",
        "logisticsCompany": "京东快递",
        "itemInfoList": [{"skuName": "测试商品", "itemTotal": 2}],
    }
    data = normalize_jd_order(raw, "123456789012")
    assert data["order_id"] == "123456789012"
    assert data["status"] == "已发货待签收"
    assert data["tracking_number"] == "JDVA999"
    assert data["platform"] == "jd"
    assert data["items"][0]["name"] == "测试商品"
    assert data["total"] == 88.5
