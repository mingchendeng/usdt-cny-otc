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
from otc_collector.report import TOP_MERCHANTS, summarize, top_merchants_by_orders

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
    """每个交易所一张卡片。失败的交易所单独一张红卡片。"""
    failures = failures or []
    failed = {item["exchange"]: item for item in failures}
    summary = [row for row in summarize(quotes) if row["exchange"] not in failed]
    by_exchange: dict[str, dict] = {}
    names: dict[str, str] = {}
    for row in summary:
        by_exchange.setdefault(row["exchange"], {})[row["side"]] = row
        names[row["exchange"]] = row["exchange_name"]
    for item in failures:
        names[item["exchange"]] = item["exchange_name"]

    codes = [code for code in _ORDER if code in names]
    codes.extend(code for code in names if code not in codes)
    if not codes:
        return [_shell("USDT/CNY", collected_at, "grey", "本轮没有报价", [{"tag": "markdown", "content": "这一轮没有采到认证商家广告。"}])]

    merchants = {
        group["exchange"]: group["merchants"]
        for group in top_merchants_by_orders(
            [quote for quote in quotes if quote.exchange not in failed],
            TOP_MERCHANTS,
        )
    }
    cards = []
    for code in codes:
        name = names[code]
        if code in failed:
            error = _short(failed[code].get("error") or "未知错误")
            cards.append(
                _shell(
                    name,
                    collected_at,
                    "red",
                    f"{name}失败",
                    [{"tag": "markdown", "content": f"这一轮没有采到。\n\n{error}", "text_size": "normal"}],
                )
            )
            continue
        buy = by_exchange.get(code, {}).get("buy")
        sell = by_exchange.get(code, {}).get("sell")
        buy_text = _price(buy)
        sell_text = _price(sell)
        spread = _spread(buy, sell)
        elements: list[dict] = [
            {
                "tag": "column_set",
                "flex_mode": "trisect",
                "horizontal_spacing": "large",
                "columns": [
                    _stat_column("买入", buy_text),
                    _stat_column("卖出", sell_text),
                    _stat_column("价差", spread),
                ],
            },
            {
                "tag": "markdown",
                "content": _price_note(buy, sell),
                "text_align": "center",
                "text_size": "notation",
            },
        ]
        merchant_text = _merchant_block(merchants.get(code, []))
        if merchant_text:
            elements.append({"tag": "hr"})
            elements.append({"tag": "markdown", "content": merchant_text, "text_size": "normal"})
        cards.append(
            _shell(name, collected_at, "blue", f"{name} 买{buy_text} 卖{sell_text}", elements)
        )
    return cards


def _shell(title: str, collected_at: str, template: str, summary: str, elements: list[dict]) -> dict:
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "summary": {"content": summary[:120]}},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": collected_at},
        },
        "body": {
            "direction": "vertical",
            "padding": "16px 20px 20px 20px",
            "elements": elements,
        },
    }


def _stat_column(label: str, value: str) -> dict:
    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "vertical_align": "top",
        "elements": [
            {"tag": "markdown", "content": label, "text_align": "center", "text_size": "notation"},
            {"tag": "markdown", "content": value, "text_align": "center", "text_size": "heading"},
        ],
    }


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


def _price_note(buy: dict | None, sell: dict | None) -> str:
    parts = [f"广告 {_count(buy, sell)}"]
    best = []
    if buy and buy.get("merchant"):
        best.append(f"买 {buy['merchant']}")
    if sell and sell.get("merchant"):
        best.append(f"卖 {sell['merchant']}")
    if best:
        parts.append("最优价 " + " · ".join(best))
    return "\n".join(parts)


def _merchant_block(merchants: list[dict]) -> str:
    if not merchants:
        return ""
    windows = {merchant["order_window"] for merchant in merchants if merchant["order_window"]}
    window = next(iter(windows)) if len(windows) == 1 else ""
    title = f"**成交单数靠前 · {len(merchants)} 家**"
    if window:
        title += f"（{window}）"
    lines = [title, ""]
    for index, merchant in enumerate(merchants, start=1):
        if merchant["orders"] is None:
            orders = "单数未知"
        else:
            orders = f"{merchant['orders']} 单"
        if merchant["order_window"] and not window:
            orders += f"（{merchant['order_window']}）"
        rate = "—" if merchant["completion_rate"] is None else f"{merchant['completion_rate']:.2f}%"
        buy = "—" if merchant["buy"] is None else f"{merchant['buy']:.4f}"
        sell = "—" if merchant["sell"] is None else f"{merchant['sell']:.4f}"
        lines.append(f"**{index}. {merchant['merchant_name']}**")
        lines.append(f"{merchant['tier']} · {orders} · 完成率 {rate}")
        lines.append(f"买 {buy}")
        lines.append(f"卖 {sell}")
        lines.append("")
    return "\n".join(lines).strip()


def _price(row: dict | None) -> str:
    if not row:
        return "—"
    return f"{row['best']:.4f}"


def _spread(buy: dict | None, sell: dict | None) -> str:
    if not buy or not sell:
        return "—"
    return f"{sell['best'] - buy['best']:+.4f}"


def _count(buy: dict | None, sell: dict | None) -> str:
    buy_count = 0 if buy is None else buy["count"]
    sell_count = 0 if sell is None else sell["count"]
    return f"买{buy_count}/卖{sell_count}"


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
