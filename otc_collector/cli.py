import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from otc_collector.exchanges import EXCHANGES, resolve_exchanges
from otc_collector.http_client import HttpClient
from otc_collector.lark import LarkError, build_cards, load_dotenv, send_card, webhook_settings
from otc_collector.models import Quote
from otc_collector.report import format_details, format_summary
from otc_collector.site import write_site
from otc_collector.storage import Storage

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "otc.sqlite"
SHANGHAI = ZoneInfo("Asia/Shanghai")
MIN_LOOP_SECONDS = 30


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="采集币安、欧易、HTX、Bitget 的 USDT/人民币 OTC 认证商家广告")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 路径")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="采集一轮并写入数据库")
    collect.add_argument("--exchanges", default="", help="逗号分隔，例如 binance,okx 或 币安,欧易。默认四家都采")
    collect.add_argument("--pages", type=int, default=3, help="每个方向最多翻几页。0 表示尽量翻完，上限见 --max-pages")
    collect.add_argument("--max-pages", type=int, default=40, help="--pages 0 时的页数上限")
    collect.add_argument("--delay", type=float, default=0.6, help="两次请求之间的间隔秒数")
    collect.add_argument("--loop", type=int, default=0, help="每隔多少秒再采一轮。0 表示只采一次")
    collect.add_argument("--lark", action="store_true", help="采完后把摘要推送到飞书卡片")

    show = sub.add_parser("show", help="看最近一轮的价格摘要")
    show.add_argument("--detail", type=int, default=0, help="每个方向再列出前 N 条广告")

    export = sub.add_parser("export", help="把报价导出成 CSV")
    export.add_argument("path", type=Path)
    export.add_argument("--all", action="store_true", help="导出全部历史，默认只导出最近一轮")

    site = sub.add_parser("site", help="把最近一轮写成 GitHub Pages 静态页")
    site.add_argument("path", type=Path, nargs="?", default=ROOT / "site", help="输出目录，默认 site/")

    sub.add_parser("notify", help="把最近一轮报价推送到飞书卡片")

    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    if args.command == "collect":
        return _collect(args)
    if args.command == "notify":
        return _notify(args.db)
    storage = Storage(args.db)
    try:
        if args.command == "show":
            return _show(storage, args.detail)
        if args.command == "site":
            return _site(storage, args.path)
        return _export(storage, args.path, args.all)
    finally:
        storage.close()


def _collect(args) -> int:
    names = [part for part in args.exchanges.split(",") if part.strip()]
    exchanges = resolve_exchanges(names or None)
    pages = args.max_pages if args.pages == 0 else args.pages
    if pages < 1:
        raise SystemExit("--pages 不能是负数")
    interval = args.loop
    if 0 < interval < MIN_LOOP_SECONDS:
        print(f"轮询间隔已提到 {MIN_LOOP_SECONDS} 秒，避免打太频繁。", file=sys.stderr)
        interval = MIN_LOOP_SECONDS
    while True:
        exit_code = _collect_once(exchanges, pages, args.delay, args.db, args.lark)
        if interval <= 0:
            return exit_code
        time.sleep(interval)


def _collect_once(exchanges, pages: int, delay: float, db_path: Path, push_lark: bool) -> int:
    collected_at = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    client = HttpClient(delay=delay)
    storage = Storage(db_path)
    print(f"开始采集 USDT/CNY 认证商家  {collected_at}")
    failed = 0
    collected: list[Quote] = []
    failures: list[dict] = []
    try:
        for exchange in exchanges:
            try:
                quotes = _dedupe(exchange.fetch(client, pages))
            except Exception as exc:
                failed += 1
                storage.save_run(collected_at, exchange.code, [], str(exc))
                failures.append(
                    {"exchange": exchange.code, "exchange_name": exchange.name, "error": str(exc)}
                )
                print(f"  {exchange.name} 失败: {exc}")
                continue
            buys = sum(1 for quote in quotes if quote.side == "buy")
            sells = sum(1 for quote in quotes if quote.side == "sell")
            storage.save_run(collected_at, exchange.code, quotes, None)
            collected.extend(quotes)
            print(f"  {exchange.name} 买入 {buys} 条，卖出 {sells} 条")
        print(f"已写入 {db_path}")
        lark_failed = False
        if push_lark:
            lark_failed = not _push_card(collected, collected_at, failures)
    finally:
        storage.close()
    if failed == len(exchanges) or lark_failed:
        return 1
    return 0


def _dedupe(quotes: list[Quote]) -> list[Quote]:
    seen = set()
    unique = []
    for quote in quotes:
        key = (quote.exchange, quote.side, quote.ad_id)
        if quote.ad_id and key in seen:
            continue
        seen.add(key)
        unique.append(quote)
    return unique


def _show(storage: Storage, detail: int) -> int:
    collected_at = storage.latest_time()
    if collected_at is None:
        print("还没有数据。先运行: python -m otc_collector collect")
        return 1
    quotes = [_quote_from_row(row) for row in storage.load(collected_at)]
    print(format_summary(quotes, collected_at))
    if detail > 0:
        print(format_details(quotes, detail))
    return 0


def _notify(db_path: Path) -> int:
    storage = Storage(db_path)
    try:
        collected_at = storage.latest_run_time()
        if collected_at is None:
            print("还没有数据。先运行: python -m otc_collector collect")
            return 1
        quotes = [_quote_from_row(row) for row in storage.load(collected_at)]
        failures = []
        for run in storage.load_runs(collected_at):
            if run["ok"]:
                continue
            exchange = EXCHANGES.get(run["exchange"])
            failures.append(
                {
                    "exchange": run["exchange"],
                    "exchange_name": exchange.name if exchange else run["exchange"],
                    "error": run["error"] or "",
                }
            )
    finally:
        storage.close()
    return 0 if _push_card(quotes, collected_at, failures) else 1


def _push_card(quotes: list[Quote], collected_at: str, failures: list[dict]) -> bool:
    try:
        url, secret = webhook_settings()
        cards = build_cards(quotes, collected_at, failures)
    except LarkError as exc:
        print(f"飞书推送失败: {exc}", file=sys.stderr)
        return False
    ok = True
    for index, card in enumerate(cards):
        if index:
            time.sleep(0.4)
        title = card["header"]["title"]["content"]
        try:
            send_card(url, card, secret)
        except LarkError as exc:
            print(f"飞书推送失败 {title}: {exc}", file=sys.stderr)
            ok = False
            continue
        except Exception as exc:
            print(f"飞书推送失败 {title}: {exc}", file=sys.stderr)
            ok = False
            continue
        print(f"已推送 {title}")
    return ok


def _site(storage: Storage, path: Path) -> int:
    collected_at = storage.latest_run_time()
    if collected_at is None:
        print("还没有数据。先运行: python -m otc_collector collect")
        return 1
    quotes = [_quote_from_row(row) for row in storage.load(collected_at)]
    failures = []
    for run in storage.load_runs(collected_at):
        if run["ok"]:
            continue
        exchange = EXCHANGES.get(run["exchange"])
        failures.append(
            {
                "exchange": run["exchange"],
                "exchange_name": exchange.name if exchange else run["exchange"],
                "error": run["error"] or "",
            }
        )
    write_site(path, quotes, collected_at, failures)
    print(f"已写入 {path / 'index.html'}")
    return 0


def _export(storage: Storage, path: Path, all_rows: bool) -> int:
    count = storage.export_csv(path, all_rows=all_rows)
    print(f"已导出 {count} 条到 {path}")
    return 0


def _quote_from_row(row) -> Quote:
    payments = tuple(part for part in (row["payments"] or "").split("、") if part)
    online = None if row["online"] is None else bool(row["online"])
    return Quote(
        exchange=row["exchange"],
        exchange_name=row["exchange_name"],
        side=row["side"],
        price=row["price"],
        available_usdt=row["available_usdt"],
        min_cny=row["min_cny"],
        max_cny=row["max_cny"],
        payments=payments,
        merchant_name=row["merchant_name"],
        merchant_id=row["merchant_id"],
        merchant_tier=row["merchant_tier"],
        month_orders=row["month_orders"],
        order_window=row["order_window"],
        completion_rate=row["completion_rate"],
        positive_rate=row["positive_rate"],
        ad_id=row["ad_id"],
        online=online,
    )
