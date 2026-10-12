from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import httpx
import structlog

from src.core.config import Settings

logger = structlog.get_logger()

# POP order_state → user-facing status (Chinese)
_JD_ORDER_STATE_LABELS: dict[str, str] = {
    "WAIT_SELLER_STOCK_OUT": "待发货",
    "WAIT_GOODS_RECEIVE_CONFIRM": "已发货待签收",
    "WAIT_SELLER_DELIVERY": "待发货",
    "FINISHED_L": "已完成",
    "TRADE_CANCELED": "已取消",
    "LOCKED": "锁定",
    "POP_ORDER_PAUSE": "暂停",
}


def build_jd_sign(params: dict[str, str], app_secret: str) -> str:
    """JOS MD5 sign: secret + sorted(key+value) + secret, uppercase."""
    pieces = [app_secret]
    for key in sorted(params.keys()):
        if key == "sign":
            continue
        pieces.append(f"{key}{params[key]}")
    pieces.append(app_secret)
    return hashlib.md5("".join(pieces).encode("utf-8")).hexdigest().upper()


def _dig(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def normalize_jd_order(raw: dict[str, Any], order_id: str) -> dict[str, Any]:
    """Map JOS pop order payload to kefu order tool schema."""
    order_info = (
        raw.get("orderDetailInfo")
        or raw.get("orderInfo")
        or raw.get("order_detail_info")
        or raw
    )
    state = str(
        order_info.get("orderState")
        or order_info.get("order_state")
        or order_info.get("orderStatus")
        or ""
    )
    status = _JD_ORDER_STATE_LABELS.get(state, state or "未知")
    tracking = (
        order_info.get("waybill")
        or order_info.get("logisticsId")
        or order_info.get("logistics_id")
        or ""
    )
    total_raw = (
        order_info.get("orderTotalPrice")
        or order_info.get("order_total_price")
        or order_info.get("orderPayment")
        or 0
    )
    try:
        total = float(total_raw)
    except (TypeError, ValueError):
        total = 0.0

    items_raw = order_info.get("itemInfoList") or order_info.get("item_info_list") or []
    items = []
    if isinstance(items_raw, list):
        for item in items_raw[:10]:
            if not isinstance(item, dict):
                continue
            items.append(
                {
                    "name": item.get("skuName") or item.get("sku_name") or "商品",
                    "quantity": item.get("itemTotal") or item.get("item_total") or 1,
                }
            )

    created = (
        order_info.get("created")
        or order_info.get("orderStartTime")
        or order_info.get("order_start_time")
        or ""
    )

    return {
        "order_id": str(order_info.get("orderId") or order_info.get("order_id") or order_id),
        "status": status,
        "destination_country": "CN",
        "currency": "CNY",
        "items": items,
        "total": total,
        "created_at": str(created),
        "carrier": order_info.get("logisticsCompany") or order_info.get("logistics_company") or "京东物流",
        "tracking_number": str(tracking) if tracking else "",
        "platform": "jd",
        "raw_order_state": state,
    }


def _parse_jd_response(payload: dict[str, Any], method: str) -> dict[str, Any]:
    """Extract inner response object; JOS wraps method name with typo 'responce'."""
    for suffix in ("_responce", "_response"):
        key = f"{method.replace('.', '_')}{suffix}"
        if key in payload:
            inner = payload[key]
            if isinstance(inner, dict):
                return inner
    if "error_response" in payload:
        err = payload["error_response"]
        code = err.get("code", "unknown")
        msg = err.get("zh_desc") or err.get("en_desc") or err.get("msg") or "JD API error"
        raise RuntimeError(f"JD API {code}: {msg}")
    return payload


async def fetch_pop_order(settings: Settings, order_id: str) -> dict[str, Any]:
    """Call jingdong.pop.order.get for a single POP order."""
    if not settings.jd_app_key or not settings.jd_app_secret or not settings.jd_access_token:
        raise RuntimeError("JD credentials not configured")

    method = "jingdong.pop.order.get"
    param_json = json.dumps(
        {
            "order_id": order_id,
            "optional_fields": (
                "orderId,orderState,waybill,logisticsId,orderTotalPrice,"
                "orderPayment,created,itemInfoList,logisticsCompany"
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    params: dict[str, str] = {
        "method": method,
        "app_key": settings.jd_app_key,
        "access_token": settings.jd_access_token,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "v": "2.0",
        "360buy_param_json": param_json,
    }
    params["sign"] = build_jd_sign(params, settings.jd_app_secret)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(settings.jd_api_url, params=params)
        resp.raise_for_status()
        payload = resp.json()

    inner = _parse_jd_response(payload, method)
    order_detail = inner.get("orderDetailInfo") or inner.get("order_detail_info") or inner
    if not isinstance(order_detail, dict):
        raise RuntimeError("JD order response missing order detail")
    return normalize_jd_order(order_detail, order_id)
