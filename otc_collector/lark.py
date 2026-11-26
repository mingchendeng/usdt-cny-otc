"""把一轮报价摘要推送到飞书 / Lark 自定义机器人。"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from otc_collector.models import Quote
from otc_collector.report import (
    TOP_MERCHANTS,
    TRADE_AMOUNT_CNY,
    TRADE_PAYMENTS,
    display_width,
    summarize,
    top_merchants_by_orders,
)

_ORDER = ("binance", "okx", "htx", "bitget")
_ALLOWED_HOSTS = {"open.feishu.cn", "open.larksuite.com"}


class LarkError(RuntimeError):
    pass


def load_dotenv(path: Path):
    """补上环境变量里还没有的键。已有的值优先，避免盖掉 Actions 注入的密钥。"""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def webhook_settings() -> tuple[str, str | None]:
    url = os.environ.get("LARK_WEBHOOK_URL", "").strip()
    secret = os.environ.get("LARK_WEBHOOK_SECRET", "").strip() or None
    if not url:
        raise LarkError("没有 LARK_WEBHOOK_URL。把自定义机器人的 Webhook 写进环境变量或项目根目录的 .env")
    if not _valid_webhook(url):
        raise LarkError("LARK_WEBHOOK_URL 必须是飞书或 Lark 自定义机器人地址")
    return url, secret


def sign(timestamp: str, secret: str) -> str:
    """飞书签名：把「时间戳\\n密钥」当作 HMAC 的 key，消息体为空。"""
    payload = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(payload, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def build_cards(quotes: list[Quote], collected_at: str, failures: list[dict] | None = None) -> list[dict]:
    """四个交易所放在同一张卡片里，一次推送只发一条消息。"""
    failures = failures or []
    failed = {item["exchange"]: item for item in failures}
    summary = [row for row in summarize(quotes) if row["exchange"] not in failed]
    by_exchange: dict[str, dict[str, dict]] = {}
    names: dict[str, str] = {}
    for quote in quotes:
        if quote.exchange not in failed:
            names[quote.exchange] = quote.exchange_name
    for row in summary:
        by_exchange.setdefault(row["exchange"], {}).setdefault(row["payment"], {})[row["side"]] = row
        names[row["exchange"]] = row["exchange_name"]
    for item in failures:
        names[item["exchange"]] = item["exchange_name"]

    codes = [code for code in _ORDER if code in names]
    codes.extend(code for code in names if code not in codes)
    if not codes:
        return [_shell("USDT/CNY", collected_at, "grey", "本轮没有报价", [{"tag": "markdown", "content": "这一轮没有采到认证商家广告。", "margin": "0px"}])]

    merchants = {
        group["exchange"]: group["merchants"]
        for group in top_merchants_by_orders(
            [quote for quote in quotes if quote.exchange not in failed],
            TOP_MERCHANTS,
        )
    }
    priced = [code for code in codes if code not in failed and by_exchange.get(code)]
    elements: list[dict] = []
    if priced:
        elements.append(_price_line(["", "买入", "卖出", "价差"], "notation"))
    summary_parts = []
    merchant_blocks = []
    for code in codes:
        name = names[code]
        if code in failed:
            error = _short(failed[code].get("error") or "未知错误")
            elements.append(_line(f"**{name}**  <font color='red'>没有采到</font>  {error}"))
            summary_parts.append(f"{name}失败")
            continue
        rails = by_exchange.get(code) or {}
        if not rails:
            elements.append(_line(f"**{name}**  没有符合条件的广告"))
            summary_parts.append(f"{name}无报价")
            continue
        for payment in TRADE_PAYMENTS:
            sides = rails.get(payment)
            if not sides:
                continue
            buy = sides.get("buy")
            sell = sides.get("sell")
            label = f"{name} · {payment}"
            elements.append(_price_line([label, _price(buy), _price(sell), _spread(buy, sell)], "normal", bold_name=True))
            summary_parts.append(f"{label} {_price(buy)}/{_price(sell)}")
        merchant_text = _merchant_block(merchants.get(code, []), name)
        if merchant_text:
            merchant_blocks.append(merchant_text)
    for index, text in enumerate(merchant_blocks):
        elements.append(
            {
                "tag": "markdown",
                "content": text,
                "text_size": "notation",
                "margin": "8px 0px 0px 0px" if index == 0 else "4px 0px 0px 0px",
            }
        )
    fetch_failures = sum(code in failed for code in codes)
    if fetch_failures == len(codes):
        template = "red"
    elif fetch_failures:
        template = "orange"
    elif priced:
        template = "blue"
    else:
        template = "grey"
    return [_shell("USDT/CNY", collected_at, template, " · ".join(summary_parts), elements)]


def _shell(title: str, collected_at: str, template: str, summary: str, elements: list[dict]) -> dict:
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "summary": {"content": summary[:120]}},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": f"{_clock(collected_at)} · {_filter_label()}"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


_COLUMN_WEIGHTS = (5, 4, 4, 3)


def _price_line(cells: list[str], size: str, bold_name: bool = False) -> dict:
    columns = []
    for index, (content, weight) in enumerate(zip(cells, _COLUMN_WEIGHTS)):
        text = f"**{content}**" if bold_name and index == 0 else content
        columns.append(
            {
                "tag": "column",
                "width": "weighted",
                "weight": weight,
                "vertical_align": "center",
                "elements": [
                    {
                        "tag": "markdown",
                        "content": text or " ",
                        "text_align": "left" if index == 0 else "right",
                        "text_size": size,
                        "margin": "0px",
                    }
                ],
            }
        )
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "horizontal_spacing": "small",
        "margin": "2px 0px 0px 0px",
        "columns": columns,
    }


def _line(content: str) -> dict:
    return {"tag": "markdown", "content": content, "text_size": "normal", "margin": "4px 0px 0px 0px"}


def send_card(url: str, card: dict, secret: str | None = None, timestamp: str | None = None):
    if not _valid_webhook(url):
        raise LarkError("Webhook 地址不是飞书或 Lark 自定义机器人")
    body: dict = {"msg_type": "interactive", "card": card}
    if secret:
        stamp = timestamp or str(int(time.time()))
        body["timestamp"] = stamp
        body["sign"] = sign(stamp, secret)
    data = json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        raise LarkError(f"飞书返回 HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise LarkError(f"飞书网络错误: {exc.reason}") from exc
    try:
        result = json.loads(raw.decode())
    except json.JSONDecodeError as exc:
        raise LarkError("飞书响应不是 JSON") from exc
    code = result.get("code", result.get("StatusCode"))
    if code not in (0, "0"):
        message = result.get("msg") or result.get("StatusMessage") or code
        raise LarkError(f"飞书拒绝了这张卡片: {message}")
    return result


def _merchant_block(merchants: list[dict], exchange_name: str) -> str:
    if not merchants:
        return ""
    windows = {merchant["order_window"] for merchant in merchants if merchant["order_window"]}
    shared = next(iter(windows)) if len(windows) == 1 else ""
    title = f"**{exchange_name} · 成交靠前**"
    if shared:
        title += f" · {shared}"
    return "\n".join([title, *(_merchant_line(merchant, show_window=not shared) for merchant in merchants)])


def _merchant_line(merchant: dict, show_window: bool) -> str:
    name = _short_name(merchant["merchant_name"], width=16)
    orders = _orders(merchant)
    if show_window and merchant["order_window"]:
        orders += f"（{merchant['order_window']}）"
    prices = []
    if merchant["buy"] is not None:
        prices.append(f"买 {_fmt(merchant['buy'])}")
    if merchant["sell"] is not None:
        prices.append(f"卖 {_fmt(merchant['sell'])}")
    return f"{name} · {orders} · {' / '.join(prices) or '—'}"


def _orders(merchant: dict) -> str:
    orders = merchant["orders"]
    if orders is None:
        return "单数未知"
    if orders >= 10_000:
        wan = orders / 10_000
        text = f"{wan:.1f}".rstrip("0").rstrip(".")
        return f"{text}万单"
    return f"{orders}单"


def _filter_label() -> str:
    amount = TRADE_AMOUNT_CNY // 10_000
    payments = "/".join(TRADE_PAYMENTS)
    return f"{amount}万 · {payments}"


def _clock(collected_at: str) -> str:
    text = collected_at.replace("T", " ")
    if len(text) >= 16 and text[4] == "-" and text[7] == "-" and text[10] == " ":
        return text[5:16]
    return collected_at


def _short_name(name: str, width: int = 12) -> str:
    short = name.strip()
    for sep in ("-", "－", "—", "–", "|"):
        if sep in short:
            head = short.split(sep, 1)[0].strip()
            if head:
                short = head
            break
    if display_width(short) <= width:
        return short
    kept = []
    used = 0
    for char in short:
        size = 2 if ord(char) > 127 else 1
        if used + size > width - 2:
            break
        kept.append(char)
        used += size
    return "".join(kept) + "…"


def _price(row: dict | None) -> str:
    if not row:
        return "—"
    return _fmt(row["best"])


def _spread(buy: dict | None, sell: dict | None) -> str:
    if not buy or not sell:
        return "—"
    return _fmt(sell["best"] - buy["best"], signed=True)


def _fmt(value: float, signed: bool = False) -> str:
    number = f"{abs(value):.4f}".rstrip("0").rstrip(".")
    if "." not in number or len(number.split(".")[1]) < 2:
        number = f"{abs(value):.2f}"
    if not signed:
        return number
    if value > 0:
        return f"+{number}"
    if value < 0:
        return f"-{number}"
    return "0.00"


def _short(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= 160:
        return compact
    return compact[:160] + "…"


def _valid_webhook(url: str) -> bool:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return (
        parsed.scheme == "https"
        and parsed.hostname in _ALLOWED_HOSTS
        and parts[:4] == ["open-apis", "bot", "v2", "hook"]
        and len(parts) == 5
    )
