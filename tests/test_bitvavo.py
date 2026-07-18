"""Read-only Bitvavo integration tests without network access."""
from cryptography.fernet import Fernet
from starlette.requests import Request

from app.helpers import templates
from app.services.bitvavo import create_signature, crypto_overview, sync_bitvavo
from app.services.credentials import decrypt_value, encrypt_value


def test_signature_matches_official_bitvavo_example():
    body = '{"market":"BTC-EUR","side":"buy","price":"5000","amount":"1.23","orderType":"limit"}'
    assert create_signature("bitvavo", 1548172481125, "POST", "/v2/order", body) == (
        "44d022723a20973a18f7ee97398b9fdd405d2d019c8d39e24b8cc0dcb39ca016"
    )


def test_credentials_are_encrypted_at_rest():
    key = Fernet.generate_key()
    encrypted = encrypt_value("private-secret", key)
    assert encrypted != "private-secret"
    assert decrypt_value(encrypted, key) == "private-secret"


class FakeBitvavoClient:
    def private_get(self, endpoint, params=None):
        if endpoint == "/balance":
            return [
                {"symbol": "BTC", "available": "0.25", "inOrder": "0"},
                {"symbol": "EUR", "available": "100", "inOrder": "0"},
            ]
        if endpoint == "/stakingBalance":
            return [{"symbol": "ETH", "amount": "2"}]
        if endpoint == "/account/history":
            return {
                "items": [
                    {
                        "transactionId": "buy-btc",
                        "executedAt": "2026-01-01T10:00:00.000Z",
                        "type": "buy",
                        "sentCurrency": "EUR",
                        "sentAmount": "10000",
                        "receivedCurrency": "BTC",
                        "receivedAmount": "0.25",
                        "feesCurrency": "EUR",
                        "feesAmount": "0",
                    },
                    {
                        "transactionId": "stake-eth",
                        "executedAt": "2026-01-02T10:00:00.000Z",
                        "type": "fixed_staking",
                        "receivedCurrency": "ETH",
                        "receivedAmount": "2",
                    },
                ],
                "currentPage": 1,
                "totalPages": 1,
            }
        raise AssertionError(endpoint)

    def public_get(self, endpoint, params=None):
        if endpoint == "/assets":
            return [
                {"symbol": "BTC", "name": "Bitcoin", "decimals": 8},
                {"symbol": "ETH", "name": "Ethereum", "decimals": 8},
                {"symbol": "EUR", "name": "Euro", "decimals": 2},
            ]
        if endpoint == "/ticker/price":
            return [
                {"market": "BTC-EUR", "price": "40000"},
                {"market": "ETH-EUR", "price": "2000"},
            ]
        if endpoint == "/BTC-EUR/candles":
            return [
                [1767225600000, "39000", "40500", "38500", "40000", "10"],
                [1767312000000, "40000", "41000", "39500", "40500", "12"],
            ]
        if endpoint == "/ETH-EUR/candles":
            return [
                [1767225600000, "1900", "2050", "1850", "2000", "20"],
                [1767312000000, "2000", "2100", "1950", "2050", "22"],
            ]
        raise AssertionError(endpoint)


def test_sync_stores_balances_staking_prices_and_history(mem_db):
    result = sync_bitvavo(mem_db, "key", "secret", client=FakeBitvavoClient())
    assert result["balances"] == 3
    assert result["transactions"] == 2
    assert result["total_eur"] == 14100
    eth = mem_db.execute("SELECT * FROM crypto_balances WHERE symbol='ETH'").fetchone()
    assert eth["staked"] == "2"
    assert eth["value_eur"] == "4000"
    assert mem_db.execute("SELECT COUNT(*) FROM crypto_transactions").fetchone()[0] == 2

    overview = crypto_overview(mem_db)
    assert overview["total"] == 14100
    assert overview["crypto_total"] == 14000
    assert {row["symbol"] for row in overview["holdings"]} == {"BTC", "ETH"}
    assert len(overview["activity"]) == 2
    assert len(overview["value_series"]) >= 2

    request = Request({
        "type": "http", "method": "GET", "path": "/crypto", "raw_path": b"/crypto",
        "query_string": b"", "headers": [], "scheme": "http",
        "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
    })
    html = templates.env.get_template("crypto.html").render(
        request=request, crypto=overview, bitvavo_configured=True,
    )
    assert "Bitcoin" in html
    assert "cryptoValueChart" in html
