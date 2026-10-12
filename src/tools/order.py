from __future__ import annotations

import httpx
import structlog

from src.core.config import Settings, get_settings
from src.tools import ToolResult

logger = structlog.get_logger()

# Demo orders bound to user email (development / mock)
_MOCK_USER_ORDERS: dict[str, list[dict]] = {
    "demo@gulf.ae": [
        {
            "order_id": "ORD-1001",
            "status": "Shipped",
            "destination_country": "AE",
            "currency": "AED",
            "total": 1299.00,
            "tracking_number": "DHL987654321",
            "carrier": "DHL Express",
            "created_at": "2024-07-01 10:00:00",
        },
        {
            "order_id": "ORD-1002",
            "status": "Delivered",
            "destination_country": "SA",
            "currency": "SAR",
            "total": 899.00,
            "tracking_number": "ARX123456789",
            "carrier": "Aramex",
            "created_at": "2024-06-15 14:30:00",
        },
    ],
}

_MOCK_JD_ORDERS: dict[str, dict] = {
    "123456789012": {
        "order_id": "123456789012",
        "status": "已发货待签收",
        "destination_country": "CN",
        "currency": "CNY",
        "items": [{"name": "示例商品", "quantity": 1}],
        "total": 199.0,
        "created_at": "2024-07-10 14:20:00",
        "carrier": "京东物流",
        "tracking_number": "JDVA12345678901",
        "platform": "jd",
        "_mock": True,
    },
}


def _mock_order_data(order_id: str) -> dict:
    if order_id in _MOCK_JD_ORDERS:
        return dict(_MOCK_JD_ORDERS[order_id])
    return {
        "order_id": order_id,
        "status": "Shipped",
        "destination_country": "SA",
        "currency": "USD",
        "items": [{"name": "智能手机 / Smartphone", "quantity": 1}],
        "total": 2999.00,
        "created_at": "2024-07-01 10:00:00",
        "carrier": "Aramex",
        "tracking_number": "ARX123456789",
        "_mock": True,
    }


def _resolve_provider(settings: Settings) -> str:
    """
    Explicit ORDER_PROVIDER wins.
    Legacy fallback: ORDER_API_URL set → rest; otherwise mock.
    """
    provider = (settings.order_provider or "mock").lower()
    if provider == "mock" and settings.order_api_url:
        return "rest"
    return provider


async def _query_via_rest(order_id: str, email: str | None, settings: Settings) -> ToolResult:
    params: dict[str, str] = {"order_id": order_id}
    if email:
        params["email"] = email
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.order_api_url.rstrip('/')}/{order_id}",
            params=params,
            headers={"Authorization": f"Bearer {settings.order_api_key}"},
        )
        resp.raise_for_status()
        return ToolResult(success=True, data=resp.json())


async def _query_via_jd(order_id: str, email: str | None, settings: Settings) -> ToolResult:
    from src.integrations.jd_client import fetch_pop_order

    has_creds = bool(
        settings.jd_app_key and settings.jd_app_secret and settings.jd_access_token
    )
    if not has_creds:
        if settings.env == "production":
            return ToolResult(success=False, error="京东订单 API 未配置，请联系管理员。")
        data = _mock_order_data(order_id)
        data["platform"] = "jd"
        if email:
            data["email_verified"] = True
        return ToolResult(success=True, data=data)

    try:
        data = await fetch_pop_order(settings, order_id)
        if email:
            data["email_verified"] = True
        return ToolResult(success=True, data=data)
    except Exception as exc:
        logger.warning("jd_order_lookup_failed", order_id=order_id, error=str(exc))
        return ToolResult(success=False, error=f"京东订单查询失败：{exc}")


async def query_order(order_id: str, email: str | None = None) -> ToolResult:
    settings = get_settings()
    order_id = (order_id or "").strip()
    if not order_id:
        return ToolResult(success=False, error="订单号不能为空")

    provider = _resolve_provider(settings)

    if provider == "rest":
        if not settings.order_api_url:
            return ToolResult(success=False, error="ORDER_API_URL 未配置")
        try:
            return await _query_via_rest(order_id, email, settings)
        except Exception as exc:
            logger.warning("rest_order_lookup_failed", order_id=order_id, error=str(exc))
            return ToolResult(success=False, error="Order lookup failed")

    if provider == "jd":
        return await _query_via_jd(order_id, email, settings)

    if settings.env == "production":
        return ToolResult(
            success=False,
            error="Order API is not configured. Contact support.",
        )

    data = _mock_order_data(order_id)
    if email:
        data["email_verified"] = True
    return ToolResult(success=True, data=data)


async def list_my_orders(
    user_id: str | None = None,
    email: str | None = None,
) -> ToolResult:
    """List orders for authenticated user."""
    settings = get_settings()
    email_key = (email or "").lower()
    provider = _resolve_provider(settings)

    if provider == "jd":
        return ToolResult(
            success=False,
            error="京东模式请直接提供订单号查询（暂不支持「我的订单」列表）。",
            data={"jd_mode": True},
        )

    if provider == "rest" and settings.order_api_url and user_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{settings.order_api_url.rstrip('/')}/user/{user_id}",
                    headers={"Authorization": f"Bearer {settings.order_api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                return ToolResult(
                    success=True,
                    data={"orders": data, "user_id": user_id},
                )
        except Exception as exc:
            logger.warning("rest_my_orders_failed", user_id=user_id, error=str(exc))
            return ToolResult(success=False, error="Failed to fetch orders")

    if settings.env == "production":
        return ToolResult(
            success=False,
            error="Order API is not configured. Please log in via the store website.",
        )

    orders = _MOCK_USER_ORDERS.get(email_key, [])
    if not orders and email_key:
        orders = [
            {
                **_mock_order_data(f"ORD-{email_key.split('@')[0][:6].upper()}"),
                "email": email_key,
            }
        ]
    return ToolResult(
        success=True,
        data={
            "orders": orders,
            "user_id": user_id,
            "email": email_key,
            "count": len(orders),
            "_mock": True,
        },
    )
