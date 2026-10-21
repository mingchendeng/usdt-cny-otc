import statistics
from collections import defaultdict

from otc_collector.models import Quote

_SIDE_LABEL = {"buy": "买入USDT", "sell": "卖出USDT"}
_EXCHANGE_ORDER = {"binance": 0, "okx": 1, "htx": 2, "bitget": 3}
TOP_MERCHANTS = 5


def display_width(text: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def summarize(quotes: list[Quote]) -> list[dict]:
    grouped: dict[tuple[str, str], list[Quote]] = defaultdict(list)
    for quote in quotes:
        grouped[(quote.exchange, quote.side)].append(quote)
    rows = []
    for (exchange, side), items in grouped.items():
        ordered = sorted(items, key=lambda quote: quote.price, reverse=(side == "sell"))
        top = ordered[:10]
        best = ordered[0]
        rows.append(
            {
                "exchange": exchange,
                "exchange_name": best.exchange_name,
                "side": side,
                "count": len(items),
                "best": best.price,
                "median10": statistics.median(quote.price for quote in top),
                "merchant": best.merchant_name,
                "tier": best.merchant_tier,
                "payments": "、".join(best.payments),
            }
        )
    rows.sort(key=lambda row: (_EXCHANGE_ORDER.get(row["exchange"], 9), 0 if row["side"] == "buy" else 1))
    return rows


def top_merchants_by_orders(quotes: list[Quote], limit: int = TOP_MERCHANTS) -> list[dict]:
    """每个交易所按成交单数取出认证商家。报价入库前已经滤掉未认证用户。"""
    grouped: dict[tuple[str, str], dict] = {}
    for quote in quotes:
        identity = quote.merchant_id or quote.merchant_name
        key = (quote.exchange, identity)
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                "exchange": quote.exchange,
                "exchange_name": quote.exchange_name,
                "merchant_name": quote.merchant_name,
                "tier": quote.merchant_tier,
                "orders": quote.month_orders,
                "order_window": quote.order_window,
                "completion_rate": quote.completion_rate,
                "buy": None,
                "sell": None,
            }
            grouped[key] = bucket
        elif _rank_value(quote.month_orders) > _rank_value(bucket["orders"]):
            bucket["merchant_name"] = quote.merchant_name
            bucket["tier"] = quote.merchant_tier
            bucket["orders"] = quote.month_orders
            bucket["order_window"] = quote.order_window
            bucket["completion_rate"] = quote.completion_rate
        if quote.side == "buy" and (bucket["buy"] is None or quote.price < bucket["buy"]):
            bucket["buy"] = quote.price
        if quote.side == "sell" and (bucket["sell"] is None or quote.price > bucket["sell"]):
            bucket["sell"] = quote.price

    by_exchange: dict[str, list[dict]] = defaultdict(list)
    for bucket in grouped.values():
        by_exchange[bucket["exchange"]].append(bucket)
    groups = []
    for exchange in sorted(by_exchange, key=lambda code: _EXCHANGE_ORDER.get(code, 9)):
        ranked = sorted(
            by_exchange[exchange],
            key=lambda item: (
                item["orders"] is not None,
                item["orders"] or 0,
                item["completion_rate"] or 0,
            ),
            reverse=True,
        )
        groups.append(
            {
                "exchange": exchange,
                "exchange_name": ranked[0]["exchange_name"],
                "merchants": ranked[:limit],
            }
        )
    return groups


def format_top_merchants(quotes: list[Quote], limit: int = TOP_MERCHANTS) -> str:
    blocks = []
    for group in top_merchants_by_orders(quotes, limit):
        merchants = group["merchants"]
        window = merchants[0]["order_window"] if _same_window(merchants) else ""
        title = f"{group['exchange_name']} 成交单数 Top {len(merchants)}"
        if window:
            title += f"（{window}）"
        lines = [title]
        for index, merchant in enumerate(merchants, start=1):
            orders = "单数未知" if merchant["orders"] is None else f"{merchant['orders']}单"
            if merchant["order_window"] and not window:
                orders += f"({merchant['order_window']})"
            rate = "—" if merchant["completion_rate"] is None else f"{merchant['completion_rate']:.2f}%"
            lines.append(
                f"{index}. {merchant['merchant_name']}  {merchant['tier']}  {orders}"
                f"  完成率 {rate}  买 {_price_text(merchant['buy'])} / 卖 {_price_text(merchant['sell'])}"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_summary(quotes: list[Quote], collected_at: str) -> str:
    rows = summarize(quotes)
    if not rows:
        return f"{collected_at} 没有采到认证商家广告。"
    header = ("交易所", "方向", "最优价", "前10中位", "广告数", "最优商家", "等级")
    body = [
        (
            row["exchange_name"],
            _SIDE_LABEL[row["side"]],
            f"{row['best']:.4f}",
            f"{row['median10']:.4f}",
            str(row["count"]),
            row["merchant"],
            row["tier"],
        )
        for row in rows
    ]
    widths = [
        max(display_width(header[index]), *(display_width(line[index]) for line in body))
        for index in range(len(header))
    ]
    lines = [
        f"USDT/CNY 认证商家  {collected_at}",
        "买入USDT = 你付人民币、商家卖币，价格越低越好。卖出USDT = 你卖币收人民币，价格越高越好。",
        "最优价只按单价排序，不看限额和完成率。下面是各交易所成交单数最高的认证商家。",
        "  ".join(pad(title, widths[index]) for index, title in enumerate(header)),
    ]
    lines.extend("  ".join(pad(line[index], widths[index]) for index in range(len(header))) for line in body)
    merchants = format_top_merchants(quotes)
    if merchants:
        lines.extend(["", merchants])
    return "\n".join(lines)


def format_details(quotes: list[Quote], limit: int) -> str:
    grouped: dict[tuple[str, str, str], list[Quote]] = defaultdict(list)
    for quote in quotes:
        grouped[(quote.exchange, quote.exchange_name, quote.side)].append(quote)
    blocks = []
    ordered_groups = sorted(grouped.items(), key=lambda item: (_EXCHANGE_ORDER.get(item[0][0], 9), item[0][2]))
    for (_code, name, side), items in ordered_groups:
        ordered = sorted(items, key=lambda quote: quote.price, reverse=(side == "sell"))[:limit]
        blocks.append(f"\n{name} {_SIDE_LABEL[side]} 前 {len(ordered)} 条")
        for index, quote in enumerate(ordered, start=1):
            limits = _limits(quote)
            rate = "-" if quote.completion_rate is None else f"{quote.completion_rate:.2f}%"
            orders = "-" if quote.month_orders is None else f"{quote.month_orders}({quote.order_window})"
            blocks.append(
                f"{index:>2}. {quote.price:.4f}  {quote.merchant_tier} {quote.merchant_name}"
                f"  限额 {limits}  支付 {'、'.join(quote.payments) or '-'}  完成率 {rate}  单数 {orders}"
            )
    return "\n".join(blocks)


def _rank_value(orders: int | None) -> int:
    return -1 if orders is None else orders


def _same_window(merchants: list[dict]) -> bool:
    windows = {merchant["order_window"] for merchant in merchants}
    return len(windows) == 1 and bool(next(iter(windows)))


def _price_text(price: float | None) -> str:
    if price is None:
        return "—"
    return f"{price:.4f}"


def _limits(quote: Quote) -> str:
    if quote.min_cny is None and quote.max_cny is None:
        return "-"
    left = "-" if quote.min_cny is None else f"{quote.min_cny:.0f}"
    right = "-" if quote.max_cny is None else f"{quote.max_cny:.0f}"
    return f"{left}-{right} CNY"
