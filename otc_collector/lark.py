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


def build_card(quotes: list[Quote], collected_at: str, failures: list[dict] | None = None) -> dict:
    failures = failures or []
    failed_codes = {item["exchange"] for item in failures}
    summary = [row for row in summarize(quotes) if row["exchange"] not in failed_codes]
    by_exchange: dict[str, dict] = {}
    names: dict[str, str] = {}
    for row in summary:
        bucket = by_exchange.setdefault(row["exchange"], {})
        bucket[row["side"]] = row
        names[row["exchange"]] = row["exchange_name"]
    for item in failures:
        names[item["exchange"]] = item["exchange_name"]

    codes = [code for code in _ORDER if code in names]
    codes.extend(code for code in names if code not in codes)

    table_rows = []
    for code in codes:
        name = names[code]
        if code in failed_codes:
            table_rows.append(
                {"exchange": name, "buy": "—", "sell": "—", "spread": "—", "count": "失败"}
            )
            continue
        buy = by_exchange.get(code, {}).get("buy")
        sell = by_exchange.get(code, {}).get("sell")
        buy_text = _price(buy)
        sell_text = _price(sell)
        table_rows.append(
            {
                "exchange": name,
                "buy": buy_text,
                "sell": sell_text,
                "spread": _spread(buy, sell),
                "count": _count(buy, sell),
            }
        )
    if failures and not summary:
        template = "red"
    elif failures:
        template = "orange"
    else:
        template = "blue"

    elements: list[dict] = [
        {
            "tag": "markdown",
            "content": (
                "买入是付人民币买 USDT，卖出是卖 USDT 收人民币。价差 = 卖出 − 买入。"
                f"下面每个交易所列出成交单数最高的 {TOP_MERCHANTS} 个认证商家。"
            ),
        },
        _table(table_rows),
    ]
    visible = [quote for quote in quotes if quote.exchange not in failed_codes]
    for block in _merchant_blocks(visible):
        elements.append({"tag": "markdown", "content": block})
    if failures:
        lines = [f"- {item['exchange_name']}：{_short(item.get('error') or '未知错误')}" for item in failures]
        elements.append({"tag": "markdown", "content": "**本轮失败**\n" + "\n".join(lines)})

    preview = _preview(table_rows)
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "summary": {"content": preview}},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": "USDT/CNY 认证商家"},
            "subtitle": {"tag": "plain_text", "content": collected_at},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
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


def _table(rows: list[dict]) -> dict:
    return {
        "tag": "table",
        "element_id": "otc_prices",
        "page_size": max(1, min(len(rows), 10)) if rows else 1,
        "row_height": "low",
        "header_style": {
            "text_align": "left",
            "text_size": "normal",
            "background_style": "grey",
            "bold": True,
            "lines": 1,
        },
        "columns": [
            {"name": "exchange", "display_name": "交易所", "data_type": "text", "width": "18%"},
            {"name": "buy", "display_name": "买入", "data_type": "text", "width": "20%", "horizontal_align": "right"},
            {"name": "sell", "display_name": "卖出", "data_type": "text", "width": "20%", "horizontal_align": "right"},
            {"name": "spread", "display_name": "价差", "data_type": "text", "width": "20%", "horizontal_align": "right"},
            {"name": "count", "display_name": "广告数", "data_type": "text", "width": "22%"},
        ],
        "rows": rows or [{"exchange": "—", "buy": "—", "sell": "—", "spread": "—", "count": "0"}],
    }


def _merchant_blocks(quotes: list[Quote]) -> list[str]:
    blocks = []
    for group in top_merchants_by_orders(quotes, TOP_MERCHANTS):
        merchants = group["merchants"]
        windows = {merchant["order_window"] for merchant in merchants if merchant["order_window"]}
        window = next(iter(windows)) if len(windows) == 1 else ""
        title = f"**{group['exchange_name']} · 成交单数 Top {len(merchants)}**"
        if window:
            title += f"（{window}）"
        lines = [title]
        for index, merchant in enumerate(merchants, start=1):
            if merchant["orders"] is None:
                orders = "单数未知"
            else:
                orders = f"{merchant['orders']}单"
            if merchant["order_window"] and not window:
                orders += f"({merchant['order_window']})"
            rate = "—" if merchant["completion_rate"] is None else f"{merchant['completion_rate']:.2f}%"
            buy = "—" if merchant["buy"] is None else f"{merchant['buy']:.4f}"
            sell = "—" if merchant["sell"] is None else f"{merchant['sell']:.4f}"
            lines.append(
                f"{index}. {merchant['merchant_name']} · {merchant['tier']} · {orders}"
                f" · 完成率 {rate} · 买 {buy} / 卖 {sell}"
            )
        blocks.append("\n".join(lines))
    return blocks


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


def _preview(rows: list[dict]) -> str:
    parts = []
    for row in rows:
        if row["count"] == "失败":
            parts.append(f"{row['exchange']}失败")
        else:
            parts.append(f"{row['exchange']} 买{row['buy']} 卖{row['sell']}")
    return " ".join(parts)[:120] or "USDT/CNY 本轮没有报价"


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
