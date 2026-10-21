"""把最近一轮报价写成 GitHub Pages 能直接托管的静态页。"""

import html
import json
from pathlib import Path

from otc_collector.models import Quote
from otc_collector.report import TOP_MERCHANTS, summarize, top_merchants_by_orders

_ORDER = ("binance", "okx", "htx", "bitget")


def write_site(directory: Path, quotes: list[Quote], collected_at: str, failures: list[dict] | None = None) -> None:
    payload = build_payload(quotes, collected_at, failures)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(render_page(payload), encoding="utf-8")
    (directory / "quotes.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_payload(quotes: list[Quote], collected_at: str, failures: list[dict] | None = None) -> dict:
    failures = failures or []
    failed_codes = {item["exchange"] for item in failures}
    summary = [row for row in summarize(quotes) if row["exchange"] not in failed_codes]
    by_exchange: dict[str, dict] = {}
    names: dict[str, str] = {}
    for row in summary:
        by_exchange.setdefault(row["exchange"], {})[row["side"]] = row
        names[row["exchange"]] = row["exchange_name"]
    for item in failures:
        names[item["exchange"]] = item["exchange_name"]

    codes = [code for code in _ORDER if code in names]
    codes.extend(code for code in names if code not in codes)
    error_by_code = {item["exchange"]: item.get("error") or "" for item in failures}

    exchanges = []
    for code in codes:
        if code in failed_codes:
            exchanges.append(
                {
                    "exchange": code,
                    "exchange_name": names[code],
                    "ok": False,
                    "error": error_by_code.get(code, ""),
                    "buy": None,
                    "sell": None,
                    "spread": None,
                    "buy_count": 0,
                    "sell_count": 0,
                    "buy_merchant": None,
                    "sell_merchant": None,
                }
            )
            continue
        buy = by_exchange.get(code, {}).get("buy")
        sell = by_exchange.get(code, {}).get("sell")
        exchanges.append(
            {
                "exchange": code,
                "exchange_name": names[code],
                "ok": True,
                "error": None,
                "buy": None if buy is None else buy["best"],
                "sell": None if sell is None else sell["best"],
                "spread": None if buy is None or sell is None else round(sell["best"] - buy["best"], 4),
                "buy_count": 0 if buy is None else buy["count"],
                "sell_count": 0 if sell is None else sell["count"],
                "buy_merchant": None if buy is None else buy["merchant"],
                "sell_merchant": None if sell is None else sell["merchant"],
            }
        )

    return {
        "collected_at": collected_at,
        "note": "广告报价，不是已经成交的价格。最优价只按单价排序。",
        "exchanges": exchanges,
        "merchants": top_merchants_by_orders(quotes, TOP_MERCHANTS),
    }


def render_page(payload: dict) -> str:
    rows = "\n".join(_exchange_row(item) for item in payload["exchanges"])
    if not rows:
        rows = '<tr><td colspan="6">这一轮没有采到认证商家广告。</td></tr>'
    merchant_blocks = "\n".join(_merchant_block(group) for group in payload["merchants"])
    if not merchant_blocks:
        merchant_blocks = "<p class=\"empty\">没有可列出的认证商家。</p>"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>USDT/CNY 认证商家</title>
<style>
:root {{
  color-scheme: light;
  --ink: #1c1915;
  --muted: #6b645b;
  --line: #e4ddd2;
  --paper: #f7f4ee;
  --card: #fffdf9;
  --buy: #0c6b45;
  --sell: #9a3d12;
  --bad: #8d2f2f;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font: 16px/1.5 "Noto Sans SC", "Source Han Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
}}
main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }}
h1 {{ font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin: 0 0 8px; }}
h2 {{ font-size: 18px; margin: 36px 0 12px; }}
.meta, .note {{ color: var(--muted); margin: 0; }}
.note {{ margin-top: 8px; }}
table {{
  width: 100%;
  border-collapse: collapse;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}}
th, td {{ padding: 12px 14px; text-align: right; border-bottom: 1px solid var(--line); }}
th:first-child, td:first-child, td.merchant {{ text-align: left; }}
th {{ font-size: 13px; color: var(--muted); font-weight: 600; background: #fbf9f5; }}
tr:last-child td {{ border-bottom: 0; }}
.num {{ font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }}
.buy {{ color: var(--buy); }}
.sell {{ color: var(--sell); }}
.bad {{ color: var(--bad); }}
.board {{ margin-top: 28px; }}
.group {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 4px 16px 8px;
  margin: 0 0 12px;
}}
.group h3 {{ margin: 12px 0 4px; font-size: 16px; }}
ol {{ margin: 8px 0 12px; padding-left: 1.2em; }}
li {{ margin: 6px 0; }}
.tier {{ color: var(--muted); }}
footer {{ margin-top: 36px; color: var(--muted); font-size: 13px; }}
</style>
</head>
<body>
<main>
  <h1>USDT/CNY 认证商家</h1>
  <p class="meta">采集时间 {_esc(payload["collected_at"])}</p>
  <p class="note">{_esc(payload["note"])} 买入是付人民币买 USDT，价格越低越好。卖出是卖 USDT 收人民币，价格越高越好。价差 = 卖出 − 买入。</p>
  <table class="board">
    <thead>
      <tr>
        <th>交易所</th>
        <th>买入</th>
        <th>卖出</th>
        <th>价差</th>
        <th>广告数</th>
        <th>最优商家</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
  <h2>成交单数靠前的认证商家</h2>
  {merchant_blocks}
  <footer>页面是静态文件，由 GitHub Actions 采集后发布到 GitHub Pages。报价来自各交易所公开盘口。</footer>
</main>
</body>
</html>
"""


def _exchange_row(item: dict) -> str:
    name = _esc(item["exchange_name"])
    if not item["ok"]:
        error = _esc(item["error"] or "采集失败")
        return (
            f'<tr><td>{name}</td><td colspan="5" class="bad">{error}</td></tr>'
        )
    buy_merchant = item["buy_merchant"] or "—"
    sell_merchant = item["sell_merchant"] or "—"
    merchants = _esc(f"买 {buy_merchant} / 卖 {sell_merchant}")
    return (
        "<tr>"
        f"<td>{name}</td>"
        f'<td class="num buy">{_money(item["buy"])}</td>'
        f'<td class="num sell">{_money(item["sell"])}</td>'
        f'<td class="num">{_spread(item["spread"])}</td>'
        f'<td class="num">买{item["buy_count"]}/卖{item["sell_count"]}</td>'
        f'<td class="merchant">{merchants}</td>'
        "</tr>"
    )


def _merchant_block(group: dict) -> str:
    merchants = group["merchants"]
    window = merchants[0]["order_window"] if _same_window(merchants) else ""
    title = f"{group['exchange_name']} Top {len(merchants)}"
    if window:
        title += f"（{window}）"
    items = "\n".join(_merchant_item(merchant, bool(window)) for merchant in merchants)
    return f'<section class="group"><h3>{_esc(title)}</h3><ol>\n{items}\n</ol></section>'


def _merchant_item(merchant: dict, window_in_title: bool) -> str:
    orders = "单数未知" if merchant["orders"] is None else f"{merchant['orders']}单"
    if merchant["order_window"] and not window_in_title:
        orders += f"({merchant['order_window']})"
    rate = "—" if merchant["completion_rate"] is None else f"{merchant['completion_rate']:.2f}%"
    return (
        "<li>"
        f"{_esc(merchant['merchant_name'])} "
        f'<span class="tier">{_esc(merchant["tier"])}</span> '
        f'<span class="num">{_esc(orders)} · 完成率 {_esc(rate)}'
        f" · 买 {_money(merchant['buy'])} / 卖 {_money(merchant['sell'])}</span>"
        "</li>"
    )


def _same_window(merchants: list[dict]) -> bool:
    windows = {merchant["order_window"] for merchant in merchants}
    return len(windows) == 1 and bool(next(iter(windows)))


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.4f}"


def _spread(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.4f}"


def _esc(value) -> str:
    return html.escape(str(value), quote=True)
