import csv
import sqlite3
from pathlib import Path

from otc_collector.models import Quote

_COLUMNS = (
    "collected_at",
    "exchange",
    "exchange_name",
    "side",
    "price",
    "available_usdt",
    "min_cny",
    "max_cny",
    "payments",
    "merchant_name",
    "merchant_id",
    "merchant_tier",
    "month_orders",
    "order_window",
    "completion_rate",
    "positive_rate",
    "ad_id",
    "online",
)

_CSV_HEADERS = {
    "collected_at": "采集时间",
    "exchange": "交易所代码",
    "exchange_name": "交易所",
    "side": "方向",
    "price": "价格CNY",
    "available_usdt": "可交易USDT",
    "min_cny": "最低CNY",
    "max_cny": "最高CNY",
    "payments": "支付方式",
    "merchant_name": "商家",
    "merchant_id": "商家编号",
    "merchant_tier": "商家等级",
    "month_orders": "成交单数",
    "order_window": "单数口径",
    "completion_rate": "完成率",
    "positive_rate": "好评率",
    "ad_id": "广告编号",
    "online": "在线",
}


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quotes (
                id INTEGER PRIMARY KEY,
                collected_at TEXT NOT NULL,
                exchange TEXT NOT NULL,
                exchange_name TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                available_usdt REAL,
                min_cny REAL,
                max_cny REAL,
                payments TEXT NOT NULL,
                merchant_name TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                merchant_tier TEXT NOT NULL,
                month_orders INTEGER,
                order_window TEXT NOT NULL,
                completion_rate REAL,
                positive_rate REAL,
                ad_id TEXT NOT NULL,
                online INTEGER
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                collected_at TEXT NOT NULL,
                exchange TEXT NOT NULL,
                ok INTEGER NOT NULL,
                quote_count INTEGER NOT NULL,
                error TEXT
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quotes_time ON quotes (collected_at, exchange, side)"
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def save_run(self, collected_at: str, exchange: str, quotes: list[Quote], error: str | None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs (collected_at, exchange, ok, quote_count, error) VALUES (?, ?, ?, ?, ?)",
                (collected_at, exchange, 0 if error else 1, len(quotes), error),
            )
            self.conn.executemany(
                f"INSERT INTO quotes ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
                [_row(collected_at, quote) for quote in quotes],
            )

    def latest_time(self) -> str | None:
        row = self.conn.execute("SELECT MAX(collected_at) FROM quotes").fetchone()
        return row[0] if row else None

    def latest_run_time(self) -> str | None:
        row = self.conn.execute("SELECT MAX(collected_at) FROM runs").fetchone()
        return row[0] if row else None

    def load_runs(self, collected_at: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT exchange, ok, quote_count, error FROM runs WHERE collected_at = ? ORDER BY id",
            (collected_at,),
        ).fetchall()

    def load(self, collected_at: str | None = None) -> list[sqlite3.Row]:
        when = collected_at or self.latest_time()
        if when is None:
            return []
        return self.conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM quotes WHERE collected_at = ? ORDER BY exchange, side, price",
            (when,),
        ).fetchall()

    def export_csv(self, path: Path, collected_at: str | None = None, all_rows: bool = False):
        if all_rows:
            rows = self.conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM quotes ORDER BY collected_at, exchange, side, price"
            ).fetchall()
        else:
            rows = self.load(collected_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow([_CSV_HEADERS[column] for column in _COLUMNS])
            for row in rows:
                record = dict(row)
                record["side"] = "买入USDT" if record["side"] == "buy" else "卖出USDT"
                record["payments"] = record["payments"]
                record["online"] = {1: "是", 0: "否"}.get(record["online"], "")
                writer.writerow([record[column] for column in _COLUMNS])
        return len(rows)


def _row(collected_at: str, quote: Quote) -> tuple:
    online = None if quote.online is None else int(quote.online)
    return (
        collected_at,
        quote.exchange,
        quote.exchange_name,
        quote.side,
        quote.price,
        quote.available_usdt,
        quote.min_cny,
        quote.max_cny,
        "、".join(quote.payments),
        quote.merchant_name,
        quote.merchant_id,
        quote.merchant_tier,
        quote.month_orders,
        quote.order_window,
        quote.completion_rate,
        quote.positive_rate,
        quote.ad_id,
        online,
    )
