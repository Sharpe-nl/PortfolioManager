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

    stocks_response = asyncio.run(stocks_dashboard(_request("/stocks"), conn=mem_db, _=None))
    assert stocks_response.template.name == "dashboard.html"
    assert "dashboard_savings" not in stocks_response.context


def test_stock_and_crypto_dashboard_visibility_is_saved(mem_db):
    asyncio.run(set_stocks_visibility(include_in_dashboard=0, conn=mem_db, _=None))
    asyncio.run(set_crypto_visibility(include_in_dashboard=0, conn=mem_db, _=None))
    assert get_setting(mem_db, "include_stocks_in_dashboard") == "0"
    assert get_setting(mem_db, "include_crypto_in_dashboard") == "0"

    asyncio.run(set_stocks_visibility(include_in_dashboard=1, conn=mem_db, _=None))
    asyncio.run(set_crypto_visibility(include_in_dashboard=1, conn=mem_db, _=None))
    assert get_setting(mem_db, "include_stocks_in_dashboard") == "1"
    assert get_setting(mem_db, "include_crypto_in_dashboard") == "1"


def test_main_dashboard_chart_has_ranges_and_total_toggle(mem_db):
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Savings','savings','EUR')")
    mem_db.execute("INSERT INTO balance_snapshots(account_id,date,balance_eur) VALUES(2,'2026-01-01','1000')")
    response = asyncio.run(dashboard(_request("/"), conn=mem_db, _=None))
    html = response.body.decode()
    assert 'data-series="total"' in html
    assert 'data-range="YTD"' in html
    assert "dashboardOverviewChart" in html
