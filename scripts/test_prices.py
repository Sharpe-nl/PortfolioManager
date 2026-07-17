#!/usr/bin/env python3
"""Quick test to verify yfinance can fetch prices from this server.

Usage (on the LXC server):
    sudo -u service_portfolio_manager /opt/portfoliomanager/.venv/bin/python \
        /opt/portfoliomanager/scripts/test_prices.py [TICKER1 TICKER2 ...]

Default tickers: VUSA.AS VEUR.AS TSM
"""
import sys


def test_batch(tickers: list[str], period: str = "5d") -> None:
    """Test batch download (the method now used by refresh_all_prices)."""
    try:
        import yfinance as yf
        import pandas as pd
        print(f"  yfinance version: {yf.__version__}")
        print(f"  batch downloading {len(tickers)} tickers with period={period}…")
        df = yf.download(tickers, period=period, auto_adjust=True, progress=False, threads=False)
        if df is None or df.empty:
            print("  ✗ lege dataframe — mogelijk geblokkeerd door Yahoo Finance")
            return
        for ticker in tickers:
            try:
                if isinstance(df.columns, pd.MultiIndex):
                    close_series = df["Close"][ticker].dropna()
                else:
                    close_series = df["Close"].dropna()
                if close_series.empty:
                    print(f"  ✗ {ticker}: lege series")
                else:
                    latest = close_series.index[-1].date()
                    close = close_series.iloc[-1]
                    print(f"  ✓ {ticker}: {len(close_series)} rijen, nieuwste={latest}, koers={close:.2f}")
            except Exception as exc:
                print(f"  ✗ {ticker}: parse fout: {exc}")
    except Exception as exc:
        print(f"  ✗ batch download fout: {exc}")


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["VUSA.AS", "VEUR.AS", "TSM"]
    print(f"\nBatch prijstest voor {len(tickers)} ticker(s):\n")
    test_batch(tickers)
    print()
