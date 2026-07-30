"""Read-only Bitvavo synchronization and crypto portfolio calculations."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_right
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from ..db import get_setting, set_setting

BASE_URL = "https://api.bitvavo.com/v2"
ZERO = Decimal("0")


class BitvavoError(RuntimeError):
    """A Bitvavo request failed without exposing credential material."""


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError):
        return ZERO


def create_signature(secret: str, timestamp: int | str, method: str, path: str, body: str = "") -> str:
    payload = f"{timestamp}{method.upper()}{path}{body}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class BitvavoClient:
    """Minimal GET-only client; no write endpoint is implemented by design."""

    def __init__(self, api_key: str, api_secret: str, timeout: int = 15):
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout

    def _get(self, endpoint: str, params: dict | None = None, private: bool = False):
        query = urllib.parse.urlencode(params or {})
        path = f"/v2{endpoint}" + (f"?{query}" if query else "")
        url = BASE_URL + endpoint + (f"?{query}" if query else "")
        headers = {"Accept": "application/json", "User-Agent": "PortfolioManager/Bitvavo-read-only"}
        if private:
            timestamp = int(time.time() * 1000)
            headers.update({
                "Bitvavo-Access-Key": self.api_key,
                "Bitvavo-Access-Timestamp": str(timestamp),
                "Bitvavo-Access-Signature": create_signature(self.api_secret, timestamp, "GET", path),
                "Bitvavo-Access-Window": "10000",
            })
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = payload.get("error") or payload.get("message") or f"HTTP {exc.code}"
                code = payload.get("errorCode")
            except Exception:
                message, code = f"HTTP {exc.code}", None
            suffix = f" ({code})" if code is not None else ""
            raise BitvavoError(f"Bitvavo: {message}{suffix}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise BitvavoError("Bitvavo is momenteel niet bereikbaar") from exc
        if isinstance(payload, dict) and ("error" in payload or "errorCode" in payload):
            raise BitvavoError(f"Bitvavo: {payload.get('error') or payload.get('message') or 'API-fout'}")
        return payload

    def private_get(self, endpoint: str, params: dict | None = None):
        return self._get(endpoint, params, private=True)

    def public_get(self, endpoint: str, params: dict | None = None):
        return self._get(endpoint, params, private=False)


def _history(client: BitvavoClient) -> list[dict]:
    result: list[dict] = []
    page = 1
    while page <= 1000:
        payload = client.private_get("/account/history", {"page": page, "maxItems": 100})
        items = payload.get("items", []) if isinstance(payload, dict) else []
        result.extend(items)
        total_pages = int(payload.get("totalPages", page)) if isinstance(payload, dict) else page
        if page >= total_pages or not items:
            break
        page += 1
    return result


def _transfer_history(client: BitvavoClient, endpoint: str, kind: str) -> list[dict]:
    """Load the complete transfer history and map it to account-history rows."""
    result: list[dict] = []
    end: int | None = None
    seen: set[str] = set()
    while True:
        params = {"limit": 1000}
        if end is not None:
            params["end"] = end
        payload = client.private_get(endpoint, params)
        rows = payload if isinstance(payload, list) else []
        for row in rows:
            status = str(row.get("status") or "").lower()
            if kind == "deposit" and status and status != "completed":
                continue
            if kind == "withdrawal" and status and status not in {"completed", "processed"}:
                continue
            timestamp = int(row.get("timestamp") or 0)
            if timestamp <= 0:
                continue
            symbol = row.get("symbol")
            amount = row.get("amount")
            fingerprint = "|".join(str(value or "") for value in (
                kind, timestamp, symbol, amount, row.get("txId"),
                row.get("paymentId"), row.get("address"),
            ))
            transaction_id = f"transfer-{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()}"
            if transaction_id in seen:
                continue
            seen.add(transaction_id)
            normalized = {
                "transactionId": transaction_id,
                "executedAt": datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat(),
                "type": kind,
                "feesCurrency": symbol,
                "feesAmount": row.get("fee"),
                "address": row.get("address"),
            }
            if kind == "deposit":
                normalized.update({"receivedCurrency": symbol, "receivedAmount": amount})
            else:
                normalized.update({"sentCurrency": symbol, "sentAmount": amount})
            result.append(normalized)
        if len(rows) < 1000:
            break
        timestamps = [int(row.get("timestamp") or 0) for row in rows if row.get("timestamp") is not None]
        if not timestamps:
            break
        next_end = min(timestamps) - 1
        if end is not None and next_end >= end:
            break
        end = next_end
    return result


def _euro_price(symbol: str, prices: dict[str, Decimal]) -> Decimal | None:
    if symbol == "EUR":
        return Decimal("1")
    direct = prices.get(f"{symbol}-EUR")
    if direct is not None:
        return direct
    for quote in ("USDC", "USDT"):
        cross = prices.get(f"{symbol}-{quote}")
        quote_eur = prices.get(f"{quote}-EUR")
        if cross is not None and quote_eur is not None:
            return cross * quote_eur
    return None


def sync_bitvavo(conn, api_key: str, api_secret: str, client: BitvavoClient | None = None) -> dict:
    client = client or BitvavoClient(api_key, api_secret)
    balances = client.private_get("/balance")
    staking = client.private_get("/stakingBalance")
    transactions = [
        row for row in _history(client)
        if row.get("type") not in {"deposit", "withdrawal", "withdrawal_cancelled"}
    ]
    transactions.extend(_transfer_history(client, "/depositHistory", "deposit"))
    transactions.extend(_transfer_history(client, "/withdrawalHistory", "withdrawal"))
    assets = client.public_get("/assets")
    ticker_rows = client.public_get("/ticker/price")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    asset_map = {row.get("symbol"): row for row in assets if row.get("symbol")}
    prices = {
        row["market"]: _decimal(row.get("price"))
        for row in ticker_rows
        if row.get("market") and row.get("price") is not None
    }
    balance_map = {row["symbol"]: row for row in balances if row.get("symbol")}
    staking_map = {row["symbol"]: _decimal(row.get("amount")) for row in staking if row.get("symbol")}
    symbols = set(balance_map) | set(staking_map)
    history_symbols = {
        currency
        for row in transactions
        for currency in (row.get("sentCurrency"), row.get("receivedCurrency"))
        if currency and currency != "EUR"
    }

    conn.execute("DELETE FROM crypto_balances")
    total_eur = crypto_eur = cash_eur = ZERO
    for symbol in sorted(symbols):
        row = balance_map.get(symbol, {})
        available = _decimal(row.get("available"))
        in_order = _decimal(row.get("inOrder"))
        staked = staking_map.get(symbol, ZERO)
        quantity = available + in_order + staked
        price = _euro_price(symbol, prices)
        value = quantity * price if price is not None else ZERO
        conn.execute(
            "INSERT INTO crypto_balances(symbol,available,in_order,staked,price_eur,value_eur,updated_at) VALUES(?,?,?,?,?,?,?)",
            (symbol, str(available), str(in_order), str(staked), str(price) if price is not None else None, str(value), now),
        )
        total_eur += value
        if symbol == "EUR":
            cash_eur += value
        else:
            crypto_eur += value
        asset = asset_map.get(symbol)
        conn.execute(
            "INSERT INTO crypto_assets(symbol,name,decimals) VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET name=excluded.name,decimals=excluded.decimals",
            (symbol, (asset or {}).get("name") or symbol, (asset or {}).get("decimals")),
        )

    conn.execute("DELETE FROM crypto_transactions WHERE type IN ('deposit','withdrawal','withdrawal_cancelled')")
    for row in transactions:
        transaction_id = row.get("transactionId")
        if not transaction_id:
            continue
        conn.execute(
            "INSERT INTO crypto_transactions(transaction_id,executed_at,type,price_currency,price_amount,sent_currency,sent_amount,received_currency,received_amount,fees_currency,fees_amount,address) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(transaction_id) DO UPDATE SET executed_at=excluded.executed_at,type=excluded.type,price_currency=excluded.price_currency,price_amount=excluded.price_amount,sent_currency=excluded.sent_currency,sent_amount=excluded.sent_amount,received_currency=excluded.received_currency,received_amount=excluded.received_amount,fees_currency=excluded.fees_currency,fees_amount=excluded.fees_amount,address=excluded.address",
            (transaction_id, row.get("executedAt") or now, row.get("type") or "other", row.get("priceCurrency"), row.get("priceAmount"), row.get("sentCurrency"), row.get("sentAmount"), row.get("receivedCurrency"), row.get("receivedAmount"), row.get("feesCurrency"), row.get("feesAmount"), row.get("address")),
        )

    direct_eur_markets = {market for market in prices if market.endswith("-EUR")}
    for symbol in sorted((symbols | history_symbols) - {"EUR"}):
        if f"{symbol}-EUR" not in direct_eur_markets:
            continue
        try:
            candles = client.public_get(f"/{symbol}-EUR/candles", {"interval": "1d", "limit": 1440})
        except BitvavoError:
            continue
        for candle in candles:
            if not isinstance(candle, (list, tuple)) or len(candle) < 5:
                continue
            day = datetime.fromtimestamp(int(candle[0]) / 1000, timezone.utc).date().isoformat()
            conn.execute(
                "INSERT INTO crypto_prices(symbol,date,close_eur) VALUES(?,?,?) "
                "ON CONFLICT(symbol,date) DO UPDATE SET close_eur=excluded.close_eur",
                (symbol, day, str(candle[4])),
            )

    conn.execute(
        "INSERT OR REPLACE INTO crypto_portfolio_snapshots(captured_at,total_eur,crypto_eur,cash_eur) VALUES(?,?,?,?)",
        (now, str(total_eur), str(crypto_eur), str(cash_eur)),
    )
    set_setting(conn, "bitvavo_last_sync", now)
    set_setting(conn, "bitvavo_last_error", "")
    return {"balances": len(symbols), "transactions": len(transactions), "total_eur": total_eur}


def crypto_overview(conn, activity_page: int = 1, activity_page_size: int = 100) -> dict:
    transaction_rows = [dict(row) for row in conn.execute("SELECT * FROM crypto_transactions ORDER BY executed_at")]
    ledger: dict[str, dict[str, Decimal | bool]] = {}

    def position(symbol: str) -> dict[str, Decimal | bool]:
        return ledger.setdefault(symbol, {"quantity": ZERO, "cost": ZERO, "complete": True})

    realized = ZERO
    net_deposits = ZERO
    for row in transaction_rows:
        kind = row["type"]
        sent_symbol, received_symbol = row.get("sent_currency"), row.get("received_currency")
        sent_amount, received_amount = _decimal(row.get("sent_amount")), _decimal(row.get("received_amount"))
        fee_eur = _decimal(row.get("fees_amount")) if row.get("fees_currency") == "EUR" else ZERO
        if kind == "deposit" and received_symbol == "EUR":
            net_deposits += received_amount
        elif kind == "withdrawal" and sent_symbol == "EUR":
            net_deposits -= sent_amount
        if kind == "buy" and received_symbol and received_symbol != "EUR":
            item = position(received_symbol)
            spent = sent_amount if sent_symbol == "EUR" else ZERO
            item["quantity"] += received_amount
            item["cost"] += spent + fee_eur
        elif kind == "sell" and sent_symbol and sent_symbol != "EUR":
            item = position(sent_symbol)
            quantity_before = item["quantity"]
            removed_cost = item["cost"] * min(sent_amount / quantity_before, Decimal("1")) if quantity_before > 0 else ZERO
            proceeds = received_amount if received_symbol == "EUR" else ZERO
            item["quantity"] = max(ZERO, quantity_before - sent_amount)
            item["cost"] = max(ZERO, item["cost"] - removed_cost)
            realized += proceeds - removed_cost - fee_eur
        elif kind == "deposit" and received_symbol and received_symbol != "EUR":
            item = position(received_symbol)
            item["quantity"] += received_amount
            item["complete"] = False
        elif kind == "withdrawal" and sent_symbol and sent_symbol != "EUR":
            item = position(sent_symbol)
            quantity_before = item["quantity"]
            removed_cost = item["cost"] * min(sent_amount / quantity_before, Decimal("1")) if quantity_before > 0 else ZERO
            item["quantity"] = max(ZERO, quantity_before - sent_amount)
            item["cost"] = max(ZERO, item["cost"] - removed_cost)
        elif kind in {"staking", "fixed_staking", "distribution", "rebate", "affiliate"} and received_symbol and received_symbol != "EUR":
            position(received_symbol)["quantity"] += received_amount

    balances = [dict(row) for row in conn.execute(
        "SELECT b.*, COALESCE(a.name,b.symbol) AS name FROM crypto_balances b LEFT JOIN crypto_assets a USING(symbol) ORDER BY CAST(b.value_eur AS REAL) DESC"
    )]
    holdings = []
    crypto_total = cash_total = known_unrealized = ZERO
    for row in balances:
        symbol = row["symbol"]
        quantity = _decimal(row["available"]) + _decimal(row["in_order"]) + _decimal(row["staked"])
        value = _decimal(row["value_eur"])
        if symbol == "EUR":
            cash_total += value
            continue
        crypto_total += value
        tracked = ledger.get(symbol)
        complete = bool(tracked and tracked["complete"] and abs(tracked["quantity"] - quantity) <= Decimal("0.00000001"))
        cost = tracked["cost"] if complete else None
        result = value - cost if cost is not None else None
        if result is not None:
            known_unrealized += result
        holdings.append({
            **row, "quantity": quantity, "value_eur": value,
            "cost_basis": cost,
            "average_cost": cost / quantity if cost is not None and quantity else None,
            "result": result,
            "result_pct": result / cost * Decimal("100") if result is not None and cost else None,
        })
    for holding in holdings:
        holding["weight"] = holding["value_eur"] / crypto_total * Decimal("100") if crypto_total else ZERO

    activity_total = len(transaction_rows)
    activity_pages = max(1, (activity_total + activity_page_size - 1) // activity_page_size)
    activity_page = min(max(1, activity_page), activity_pages)
    activity_desc = list(reversed(transaction_rows))
    activity_start = (activity_page - 1) * activity_page_size
    activity = activity_desc[activity_start:activity_start + activity_page_size]
    snapshots = [dict(row) for row in conn.execute("SELECT * FROM crypto_portfolio_snapshots ORDER BY captured_at")]
    price_rows = [dict(row) for row in conn.execute("SELECT symbol,date,close_eur FROM crypto_prices ORDER BY date,symbol")]
    price_history: dict[str, list[tuple[str, Decimal]]] = {}
    for row in price_rows:
        price_history.setdefault(row["symbol"], []).append((row["date"], _decimal(row["close_eur"])))
    price_dates = {symbol: [entry[0] for entry in history] for symbol, history in price_history.items()}

    def historical_eur_value(symbol: str | None, amount: Decimal, day: str) -> Decimal | None:
        if not symbol or amount <= 0:
            return None
        if symbol == "EUR":
            return amount
        history = price_history.get(symbol, [])
        price_index = bisect_right(price_dates.get(symbol, []), day) - 1
        return amount * history[price_index][1] if price_index >= 0 else None

    for row in activity:
        row["received_eur"] = historical_eur_value(
            row.get("received_currency"),
            _decimal(row.get("received_amount")),
            row["executed_at"][:10],
        )

    earn_rewards = ZERO
    period_events = []
    for row in transaction_rows:
        day = row["executed_at"][:10]
        cash_flow = ZERO
        if row["type"] == "deposit" and row.get("received_currency") == "EUR":
            cash_flow = _decimal(row.get("received_amount"))
        elif row["type"] == "withdrawal" and row.get("sent_currency") == "EUR":
            cash_flow = -_decimal(row.get("sent_amount"))

        reward = ZERO
        if row["type"] not in {"staking", "fixed_staking", "loan"}:
            period_events.append({"date": day, "cash_flow": str(cash_flow), "reward": "0"})
            continue
        if row.get("price_currency") == "EUR" and _decimal(row.get("price_amount")) > 0:
            reward = _decimal(row["price_amount"])
        else:
            symbol = row.get("received_currency")
            amount = _decimal(row.get("received_amount"))
            reward = amount if symbol == "EUR" else (historical_eur_value(symbol, amount, day) or ZERO)
        earn_rewards += reward
        period_events.append({"date": day, "cash_flow": str(cash_flow), "reward": str(reward)})
    quantity_events: list[tuple[str, str, Decimal]] = []
    for row in transaction_rows:
        day = row["executed_at"][:10]
        if row.get("received_currency"):
            quantity_events.append((day, row["received_currency"], _decimal(row.get("received_amount"))))
        if row.get("sent_currency"):
            quantity_events.append((day, row["sent_currency"], -_decimal(row.get("sent_amount"))))
    quantity_events.sort(key=lambda event: event[0])
    current_quantities = {
        row["symbol"]: _decimal(row["available"]) + _decimal(row["in_order"]) + _decimal(row["staked"])
        for row in balances
    }
    prices_by_day: dict[str, list[dict]] = {}
    for row in price_rows:
        prices_by_day.setdefault(row["date"], []).append(row)
    today = datetime.now(timezone.utc).date().isoformat()
    series_days = set(prices_by_day) | {event[0] for event in quantity_events} | {today}
    quantities = dict(current_quantities)
    quantities_by_day: dict[str, dict[str, Decimal]] = {}
    event_index = len(quantity_events) - 1
    for day in sorted(series_days, reverse=True):
        while event_index >= 0 and quantity_events[event_index][0] > day:
            _event_day, symbol, delta = quantity_events[event_index]
            quantities[symbol] = quantities.get(symbol, ZERO) - delta
            event_index -= 1
        quantities_by_day[day] = dict(quantities)

    latest_prices: dict[str, Decimal] = {"EUR": Decimal("1")}
    snapshot_by_day = {row["captured_at"][:10]: _decimal(row["total_eur"]) for row in snapshots}
    value_series = []
    for day in sorted(series_days):
        daily_prices = prices_by_day.get(day, [])
        for row in daily_prices:
            latest_prices[row["symbol"]] = _decimal(row["close_eur"])
        value = sum(
            max(ZERO, quantity) * latest_prices.get(symbol, ZERO)
            for symbol, quantity in quantities_by_day[day].items()
        )
        if day in snapshot_by_day:
            value = snapshot_by_day[day]
        value_series.append({"date": day, "value": str(value)})
    if value_series and value_series[-1]["date"] == today:
        value_series[-1]["value"] = str(crypto_total + cash_total)
    else:
        value_series.append({"date": today, "value": str(crypto_total + cash_total)})
    if len(value_series) < 2 and snapshots:
        value_series = [{"date": row["captured_at"][:10], "value": row["total_eur"]} for row in snapshots]
    total = crypto_total + cash_total
    unrealized_result = total - net_deposits
    return {
        "holdings": holdings,
        "chart_holdings": [{"symbol": row["symbol"], "value_eur": str(row["value_eur"])} for row in holdings],
        "activity": activity,
        "activity_total": activity_total,
        "activity_page": activity_page,
        "activity_pages": activity_pages,
        "snapshots": snapshots,
        "value_series": value_series,
        "period_events": period_events,
        "crypto_total": crypto_total,
        "cash_total": cash_total,
        "total": total,
        "net_deposits": net_deposits,
        "unrealized_result": unrealized_result,
        "unrealized_pct": unrealized_result / net_deposits * Decimal("100") if net_deposits > 0 else None,
        "known_unrealized": known_unrealized,
        "realized": realized,
        "earn_rewards": earn_rewards,
        "last_sync": get_setting(conn, "bitvavo_last_sync"),
    }
