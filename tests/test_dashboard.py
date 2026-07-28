"""Main dashboard composition and category visibility tests."""
import asyncio

from starlette.requests import Request

from app.db import get_setting
from app.routers.crypto import set_crypto_visibility
from app.routers.portfolio import dashboard, set_stocks_visibility, stocks_dashboard


def _request(path: str) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": [], "scheme": "http",
        "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
    })


def test_main_and_stocks_dashboards_are_separate(mem_db):
    main_response = asyncio.run(dashboard(_request("/"), conn=mem_db, _=None))
    assert main_response.template.name == "overview_dashboard.html"

    stocks_response = asyncio.run(stocks_dashboard(_request("/stocks"), account=None, conn=mem_db, _=None))
    assert stocks_response.template.name == "dashboard.html"
    assert "dashboard_savings" not in stocks_response.context


def test_stock_and_crypto_dashboard_visibility_is_saved(mem_db):
    asyncio.run(set_stocks_visibility(include_in_dashboard=0, account=None, conn=mem_db, _=None))
    asyncio.run(set_crypto_visibility(include_in_dashboard=0, conn=mem_db, _=None))
    assert get_setting(mem_db, "include_stocks_in_dashboard") == "0"
    assert get_setting(mem_db, "include_crypto_in_dashboard") == "0"

    asyncio.run(set_stocks_visibility(include_in_dashboard=1, account=None, conn=mem_db, _=None))
    asyncio.run(set_crypto_visibility(include_in_dashboard=1, conn=mem_db, _=None))
    assert get_setting(mem_db, "include_stocks_in_dashboard") == "1"
    assert get_setting(mem_db, "include_crypto_in_dashboard") == "1"


def test_stock_dashboard_account_filter_excludes_savings(mem_db):
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Savings','savings','EUR')")
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(3,'Pension','pension','EUR')")
    mem_db.commit()

    response = asyncio.run(stocks_dashboard(_request("/stocks"), account=3, conn=mem_db, _=None))

    assert response.context["selected_account"] == 3
    assert [(account.id, account.name) for account in response.context["accounts"]] == [
        (1, "DeGiro"), (3, "Pension"),
    ]


def test_main_dashboard_chart_has_ranges_and_total_toggle(mem_db):
    mem_db.execute("INSERT INTO crypto_prices(symbol,date,close_eur) VALUES('BTC','2026-01-01','40000')")
    mem_db.execute("INSERT INTO crypto_balances(symbol,available,in_order,staked,price_eur,value_eur,updated_at) VALUES('BTC','1','0','0','40000','40000','2026-01-01')")
    response = asyncio.run(dashboard(_request("/"), conn=mem_db, _=None))
    html = response.body.decode()
    assert 'data-series="total"' in html
    assert 'data-range="YTD"' in html
    assert "dashboardOverviewChart" in html
    assert 'data-series="savings"' not in html
    assert html.index("dashboard-chart-ranges") < html.index("portfolio-hero")
