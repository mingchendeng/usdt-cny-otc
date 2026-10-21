from dataclasses import dataclass


@dataclass(frozen=True)
class Quote:
    """一条认证商家广告。side 是用户方向：buy 表示用人民币买 USDT。"""

    exchange: str
    exchange_name: str
    side: str
    price: float
    available_usdt: float | None
    min_cny: float | None
    max_cny: float | None
    payments: tuple[str, ...]
    merchant_name: str
    merchant_id: str
    merchant_tier: str
    month_orders: int | None
    order_window: str
    completion_rate: float | None
    positive_rate: float | None
    ad_id: str
    online: bool | None


def num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ratio_to_percent(value) -> float | None:
    """接口给的是 0 到 1 的比率。"""
    parsed = num(value)
    if parsed is None or parsed < 0:
        return None
    return round(parsed * 100, 4)


def as_percent(value) -> float | None:
    """接口给的已经是百分数。"""
    parsed = num(value)
    if parsed is None or parsed < 0:
        return None
    return round(parsed, 4)


def as_int(value) -> int | None:
    parsed = num(value)
    if parsed is None or parsed < 0:
        return None
    return int(parsed)


def valid_price(value) -> float | None:
    parsed = num(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed
