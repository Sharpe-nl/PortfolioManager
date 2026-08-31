"""Tests for DeGiro CSV importers."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from app.importers import degiro_account as acc_parser
from app.importers import generic as gen_parser
from app.routers import imports as imports_router


class _UploadRequest:
    """Minimal request object needed by the upload route in these unit tests."""
    def __init__(self):
        self.session = {}
        self.cookies = {}


class _UploadFile:
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self, _size: int = -1) -> bytes:
        return self._content if _size < 0 else self._content[:_size]


def test_upload_stages_account_csv_and_redirects_to_preview(mem_db, account_csv):
    request = _UploadRequest()
    upload = _UploadFile("Account.csv", account_csv.encode("utf-8"))

    response = asyncio.run(imports_router.upload(request, mem_db, None, 1, upload))

    assert response.status_code == 303
    assert response.headers["location"] == "/import/preview"
    assert request.session["import_file_type"] == "degiro_account"
    assert mem_db.execute("SELECT COUNT(*) FROM import_staging").fetchone()[0] > 0
    assert not mem_db.in_transaction


def test_upload_empty_csv_returns_visible_error(mem_db):
    request = _UploadRequest()
    upload = _UploadFile("Account.csv", b"")

    response = asyncio.run(imports_router.upload(request, mem_db, None, 1, upload))

    assert response.status_code == 303
    assert response.headers["location"] == "/import?result=1"
    assert request.session["import_result"]["errors"] == 1


def test_account_csv_upload_is_rejected_for_non_broker_account(mem_db, account_csv):
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Savings','savings','EUR')")
    mem_db.commit()
    request = _UploadRequest()
    upload = _UploadFile("Account.csv", account_csv.encode("utf-8"))

    response = asyncio.run(imports_router.upload(request, mem_db, None, 2, upload))

    assert response.headers["location"] == "/import?result=1"
    assert request.session["import_result"]["errors"] == 1
    assert mem_db.execute("SELECT COUNT(*) FROM import_staging").fetchone()[0] == 0


def test_account_csv_upload_is_accepted_for_pension_account(mem_db, account_csv):
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Pension','pension','EUR')")
    mem_db.commit()
    request = _UploadRequest()
    upload = _UploadFile("Account.csv", account_csv.encode("utf-8"))

    response = asyncio.run(imports_router.upload(request, mem_db, None, 2, upload))

    assert response.headers["location"] == "/import/preview"
    assert mem_db.execute("SELECT COUNT(*) FROM import_staging").fetchone()[0] > 0


def _seed_history_for_replacement(mem_db):
    mem_db.execute(
        """INSERT INTO instruments(
               id,isin,name,symbol,currency,trading_currency,asset_type,sector,region
           ) VALUES(1,'IE00B3RBWM25','Vanguard FTSE All-World','VWRL.AS','EUR','EUR',
                    'etf','Global equity','Global')"""
    )
    mem_db.execute(
        """INSERT INTO transactions(
               account_id,instrument_id,ts,quantity,price,local_currency,
               value_eur,fees_eur,source
           ) VALUES(1,1,'2020-01-01T10:00:00','1','80','EUR','-80','0','old')"""
    )
    mem_db.execute(
        "INSERT INTO cash_events(account_id,ts,type,amount_eur) "
        "VALUES(1,'2020-01-01T09:00:00','deposit','100')"
    )
    mem_db.execute(
        "INSERT INTO balance_snapshots(account_id,date,balance_eur) "
        "VALUES(1,'2020-01-01','20')"
    )
    mem_db.execute(
        "INSERT INTO prices(instrument_id,date,close,currency,fetched_at) "
        "VALUES(1,'2026-01-01','140','EUR','2026-01-01T12:00:00')"
    )
    mem_db.execute(
        """INSERT INTO import_log(
               account_id,filename,file_type,imported_at,rows_imported
           ) VALUES(1,'old.csv','degiro_account','2020-01-01',1)"""
    )
    mem_db.commit()


def test_replace_history_preserves_ticker_metadata_and_prices(mem_db, account_csv):
    _seed_history_for_replacement(mem_db)
    mem_db.execute("INSERT INTO accounts(id,name,type,currency) VALUES(2,'Other','broker','EUR')")
    mem_db.execute(
        """INSERT INTO transactions(
               account_id,instrument_id,ts,quantity,price,local_currency,
               value_eur,fees_eur,source
           ) VALUES(2,1,'2024-01-01T10:00:00','1','100','EUR','-100','0','other')"""
    )
    mem_db.commit()
    request = _UploadRequest()

    response = asyncio.run(imports_router.upload(
        request, mem_db, None, 1,
        _UploadFile("Account.csv", account_csv.encode("utf-8")),
        replace_history=True,
    ))

    assert response.headers["location"] == "/import/preview"
    assert request.session["import_replace_history"] is True
    assert mem_db.execute(
        "SELECT COUNT(*) FROM import_staging WHERE status='duplicate'"
    ).fetchone()[0] == 0

    response = asyncio.run(imports_router.confirm(request, mem_db, None))

    assert response.headers["location"] == "/import?result=1"
    assert request.session["import_result"]["replaced"] is True
    assert mem_db.execute(
        "SELECT COUNT(*) FROM transactions WHERE account_id=1 AND ts LIKE '2020-%'"
    ).fetchone()[0] == 0
    assert mem_db.execute(
        "SELECT COUNT(*) FROM transactions WHERE account_id=1"
    ).fetchone()[0] > 0
    assert mem_db.execute(
        "SELECT COUNT(*) FROM transactions WHERE account_id=2"
    ).fetchone()[0] == 1
    instrument = mem_db.execute(
        "SELECT symbol,sector,region FROM instruments WHERE id=1"
    ).fetchone()
    assert tuple(instrument) == ("VWRL.AS", "Global equity", "Global")
    assert mem_db.execute(
        "SELECT COUNT(*) FROM prices WHERE instrument_id=1"
    ).fetchone()[0] == 1
    assert mem_db.execute(
        "SELECT COUNT(*) FROM import_log WHERE account_id=1"
    ).fetchone()[0] == 1


def test_replace_history_rolls_back_when_commit_fails(mem_db, account_csv):
    _seed_history_for_replacement(mem_db)
    request = _UploadRequest()
    asyncio.run(imports_router.upload(
        request, mem_db, None, 1,
        _UploadFile("Account.csv", account_csv.encode("utf-8")),
        replace_history=True,
    ))
    transaction_id = mem_db.execute(
        "SELECT id FROM import_staging WHERE row_type='transaction' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    mem_db.execute(
        "UPDATE import_staging SET row_json='{}' WHERE id=?", (transaction_id,)
    )
    mem_db.commit()

    asyncio.run(imports_router.confirm(request, mem_db, None))

    assert request.session["import_result"]["replaced"] is False
    assert request.session["import_result"]["errors"] == 1
    assert mem_db.execute(
        "SELECT COUNT(*) FROM transactions WHERE account_id=1 AND ts='2020-01-01T10:00:00'"
    ).fetchone()[0] == 1
    assert mem_db.execute(
        "SELECT COUNT(*) FROM cash_events WHERE account_id=1 AND ts='2020-01-01T09:00:00'"
    ).fetchone()[0] == 1


def test_replace_history_rejects_generic_csv(mem_db):
    request = _UploadRequest()
    content = b"date,type,isin_or_name,quantity,price,amount_eur,description\n2025-01-01,deposit,,,,100,Deposit\n"

    response = asyncio.run(imports_router.upload(
        request, mem_db, None, 1, _UploadFile("generic.csv", content),
        replace_history=True,
    ))

    assert response.headers["location"] == "/import?result=1"
    assert request.session["import_result"]["errors"] == 1

# ── Account.csv ──────────────────────────────────────────────────────────────

class TestAccountParser:
    def test_detects_account_csv(self, account_csv):
        assert acc_parser.is_account_csv(account_csv)

    def test_parses_english_account_csv(self, account_en_csv):
        result = acc_parser.parse(account_en_csv)
        assert acc_parser.is_account_csv(account_en_csv)
        assert len(result.txn_rows) == 3
        assert result.txn_rows[0].quantity == Decimal("8")
        assert result.txn_rows[1].quantity == Decimal("-2")
        assert any(row.event_type == "deposit" for row in result.rows)

    def test_parses_semicolon_separated_account_csv(self):
        content = (
            "Datum;Tijd;Valutadatum;Product;ISIN;Omschrijving;FX;Mutatie;;Saldo;;Order Id\n"
            "16-01-2025;04:51;16-01-2025;;;iDEAL storting;;EUR;\"2500,00\";EUR;\"2500,00\";\n"
        )

        result = acc_parser.parse(content)

        assert acc_parser.is_account_csv(content)
        assert len(result.rows) == 1
        assert result.rows[0].event_type == "deposit"
        assert result.rows[0].amount_eur == Decimal("2500.00")

    @pytest.mark.parametrize("fixture_name", ["account_csv", "account_en_csv"])
    def test_spin_off_and_split_adjustments(self, request, fixture_name):
        result = acc_parser.parse(request.getfixturevalue(fixture_name))
        spin_off = next(row for row in result.txn_rows if row.isin == "IE00SPINOFF01")
        assert (spin_off.quantity, spin_off.price) == (Decimal("2"), Decimal("0"))
        assert [(action.isin, action.quantity, action.price) for action in result.corporate_actions] == [
            ("GB00B10RZP78", Decimal("10"), Decimal("47.73")),
            ("GB00BVZK7T90", Decimal("8"), Decimal("53.6962")),
        ]

    def test_skips_koop_verkoop_valuta_rows(self, account_csv):
        result = acc_parser.parse(account_csv)
        types = [r.event_type for r in result.rows]
        assert "None" not in types  # skipped rows not in rows list

    def test_deposit_classified(self, account_csv):
        result = acc_parser.parse(account_csv)
        deposits = [r for r in result.rows if r.event_type == "deposit"]
        assert len(deposits) == 1
        assert deposits[0].amount_eur == Decimal("2500.00")

    def test_withdrawal_classified(self, account_csv):
        result = acc_parser.parse(account_csv)
        withdrawals = [r for r in result.rows if r.event_type == "withdrawal"]
        assert len(withdrawals) == 1
        assert withdrawals[0].amount_eur == Decimal("-500.00")

    def test_dividend_classified(self, account_csv):
        result = acc_parser.parse(account_csv)
        divs = [r for r in result.rows if r.event_type == "dividend"]
        assert len(divs) >= 2  # VWRL EUR div + Apple USD div

    def test_dividend_tax_classified(self, account_csv):
        result = acc_parser.parse(account_csv)
        taxes = [r for r in result.rows if r.event_type == "dividend_tax"]
        assert len(taxes) == 1

    def test_fee_classified(self, account_csv):
        result = acc_parser.parse(account_csv)
        fees = [r for r in result.rows if r.event_type == "fee"]
        assert len(fees) >= 2  # trade fees + platform fee

    def test_interest_classified(self, account_csv):
        result = acc_parser.parse(account_csv)
        interest = [r for r in result.rows if r.event_type == "interest"]
        assert len(interest) == 1

    def test_promotion_credit_is_classified_as_bonus(self):
        assert acc_parser.classify_row("DEGIRO Verrekening Promotie") == "bonus"

    def test_eur_dividend_amount_correct(self, account_csv):
        result = acc_parser.parse(account_csv)
        eur_div = next(
            r for r in result.rows
            if r.event_type == "dividend" and r.amount_currency == "EUR"
        )
        assert eur_div.amount_eur == Decimal("4.72")

    def test_usd_dividend_converted_via_fx(self, account_csv):
        """USD dividend should be converted to EUR using collected FX rates."""
        result = acc_parser.parse(account_csv)
        usd_div = next(
            (r for r in result.rows
             if r.event_type == "dividend" and r.amount_currency == "USD"),
            None,
        )
        if usd_div:
            # 0.50 USD / 1.0791 ≈ 0.4634 EUR
            assert usd_div.amount_eur > Decimal("0.40")
            assert usd_div.amount_eur < Decimal("0.55")

    def test_dedup_hash_unique_per_row(self, account_csv):
        result = acc_parser.parse(account_csv)
        hashes = [r.dedup_hash for r in result.rows]
        assert len(hashes) == len(set(hashes))

    def test_commit_no_duplicates(self, account_csv, mem_db):
        result = acc_parser.parse(account_csv)
        imp, skip, errors = acc_parser.commit_account_events(mem_db, result, account_id=1)
        mem_db.commit()
        assert imp > 0
        assert errors == []

    def test_same_isin_in_two_currencies_creates_separate_trade_lines(self, mem_db):
        content = (
            "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
            "01-01-2025,10:00,01-01-2025,Example ETF,IE00TEST0001,Koop 1 @ 100 EUR,,EUR,-100,EUR,900,order-eur\n"
            "02-01-2025,10:00,02-01-2025,Example ETF,IE00TEST0001,Koop 1 @ 100 USD,1.1,USD,-100,EUR,800,order-usd\n"
        )
        result = acc_parser.parse(content)
        imported, _, errors = acc_parser.commit_account_events(mem_db, result, account_id=1)
        mem_db.commit()

        assert imported == 2
        assert errors == []
        lines = mem_db.execute(
            "SELECT trading_currency FROM instruments WHERE isin='IE00TEST0001' ORDER BY trading_currency"
        ).fetchall()
        assert [row["trading_currency"] for row in lines] == ["EUR", "USD"]

    def test_existing_stock_is_reused_when_import_currency_differs(self, mem_db):
        mem_db.execute(
            "INSERT INTO instruments(isin,name,trading_currency,asset_type) "
            "VALUES('NL0011872643','ASR Nederland','EUR','stock')"
        )

        eur_id = acc_parser._get_instrument_id(
            mem_db, "NL0011872643", "ASR Nederland", "EUR"
        )
        usd_id = acc_parser._get_instrument_id(
            mem_db, "NL0011872643", "ASR Nederland", "USD"
        )

        assert usd_id == eur_id
        assert mem_db.execute(
            "SELECT COUNT(*) FROM instruments WHERE isin='NL0011872643'"
        ).fetchone()[0] == 1

    def test_import_claims_legacy_instrument_without_currency(self, mem_db):
        cur = mem_db.execute(
            "INSERT INTO instruments(isin,name,asset_type) "
            "VALUES('NL0011872643','ASR Nederland','other')"
        )

        instrument_id = acc_parser._get_instrument_id(
            mem_db, "NL0011872643", "ASR Nederland", "EUR"
        )

        assert instrument_id == cur.lastrowid
        row = mem_db.execute(
            "SELECT trading_currency FROM instruments WHERE id=?", (instrument_id,)
        ).fetchone()
        assert row["trading_currency"] == "EUR"
        assert mem_db.execute(
            "SELECT COUNT(*) FROM instruments WHERE isin='NL0011872643'"
        ).fetchone()[0] == 1

    def test_reimport_idempotent(self, account_csv, mem_db):
        result = acc_parser.parse(account_csv)
        acc_parser.commit_account_events(mem_db, result, account_id=1)
        mem_db.commit()
        imp2, skip2, _ = acc_parser.commit_account_events(mem_db, result, account_id=1)
        # All previously imported rows should be skipped
        assert imp2 == 0

    def test_reimport_with_changed_csv_representation_is_deduplicated(self, mem_db):
        dutch = (
            "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
            "01-01-2025,10:00,01-01-2025,ASR Nederland,NL0011872643,"
            "Koop 1 @ 40 EUR,,EUR,-40,EUR,960,order-asr\n"
        )
        changed = dutch.replace("Koop 1", "Buy 1").replace(",960,", ",920,")
        first = acc_parser.parse(dutch)
        second = acc_parser.parse(changed)

        imported, _, _ = acc_parser.commit_account_events(mem_db, first, account_id=1)
        imported_again, skipped, errors = acc_parser.commit_account_events(
            mem_db, second, account_id=1
        )

        assert imported == 1
        assert imported_again == 0
        assert skipped == 1
        assert errors == []
        assert first.txn_rows[0].dedup_hash != second.txn_rows[0].dedup_hash

    def test_repeated_identical_fills_keep_their_occurrence_count(self, mem_db):
        content = (
            "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
            "01-01-2025,10:00,01-01-2025,ASR Nederland,NL0011872643,Koop 1 @ 40 EUR,,EUR,-40,EUR,960,order-asr\n"
            "01-01-2025,10:00,01-01-2025,ASR Nederland,NL0011872643,Koop 1 @ 40 EUR,,EUR,-40,EUR,920,order-asr\n"
        )
        result = acc_parser.parse(content)

        imported, _, _ = acc_parser.commit_account_events(mem_db, result, account_id=1)
        imported_again, skipped, errors = acc_parser.commit_account_events(
            mem_db, result, account_id=1
        )

        assert imported == 2
        assert imported_again == 0
        assert skipped == 2
        assert errors == []

    def test_overlapping_export_safe(self, account_csv, mem_db):
        """Uploading a file that overlaps with a previous upload should produce zero new rows."""
        result = acc_parser.parse(account_csv)
        acc_parser.commit_account_events(mem_db, result, account_id=1)
        mem_db.commit()
        # Re-parse and import the same file
        result2 = acc_parser.parse(account_csv)
        imp, skip, _ = acc_parser.commit_account_events(mem_db, result2, account_id=1)
        assert imp == 0

    def test_bom_handling(self, account_csv):
        bom_content = "\ufeff" + account_csv
        result = acc_parser.parse(bom_content)
        assert len(result.rows) > 0

    def test_empty_order_id_rows_handled(self):
        content = (
            "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
            "16-01-2025,04:51,16-01-2025,,,iDEAL storting,,EUR,\"2500,00\",EUR,\"2500,00\",\n"
        )
        result = acc_parser.parse(content)
        assert len(result.rows) == 1
        assert result.rows[0].order_id is None

    def test_pending_ideal_reservation_does_not_inflate_cash_snapshot(self):
        content = (
            "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
            "16-01-2025,04:51,16-01-2025,,,iDEAL storting,,EUR,\"100,00\",EUR,\"100,00\",\n"
            "17-01-2025,04:51,17-01-2025,,,Reservation iDEAL,,EUR,\"100,00\",EUR,\"200,00\",\n"
        )

        result = acc_parser.parse(content)

        assert len(result.rows) == 1
        assert result.rows[0].event_type == "deposit"
        # The reservation has not settled yet, so its cash must not be shown
        # as portfolio value before its matching iDEAL deposit exists.
        assert result.cash_balances_raw == {"EUR": Decimal("100.00")}

    def test_cash_sweep_rows_keep_the_final_balance_when_timestamps_match(self):
        """A cash sweep's intermediate €1,000 must not replace €106.79 cash."""
        content = (
            "Datum,Tijd,Valutadatum,Product,ISIN,Omschrijving,FX,Mutatie,,Saldo,,Order Id\n"
            "23-07-2026,03:21,23-07-2026,,,Overboeking van uw geldrekening bij flatexDEGIRO Bank 893,21 EUR,,,EUR,\"106,79\",\n"
            "23-07-2026,03:21,23-07-2026,,,Degiro Cash Sweep Transfer,,EUR,\"893,21\",EUR,\"1000,00\",\n"
            "23-07-2026,02:40,22-07-2026,,,iDEAL Deposit,,EUR,\"1000,00\",EUR,\"106,79\",\n"
            "23-07-2026,02:40,22-07-2026,,,Reservation iDEAL,,EUR,\"-1000,00\",EUR,\"-893,21\",\n"
        )

        result = acc_parser.parse(content)

        assert result.cash_balances_raw == {"EUR": Decimal("106.79")}
        assert result.cash_balance_eur == Decimal("106.79")


# ── Generic CSV ───────────────────────────────────────────────────────────────

class TestGenericParser:
    def test_transaction_row(self):
        content = "date,type,isin_or_name,quantity,price,amount_eur,description\n2025-01-01,transaction,IE00B3RBWM25,10,100.00,-1000.00,Buy VWRL\n"
        result = gen_parser.parse(content)
        assert len(result.rows) == 1
        assert result.rows[0].quantity == Decimal("10")
        assert result.rows[0].price == Decimal("100.00")

    def test_deposit_row(self):
        content = "date,type,isin_or_name,quantity,price,amount_eur,description\n2025-01-01,deposit,,,,2500.00,iDEAL\n"
        result = gen_parser.parse(content)
        assert result.rows[0].row_type == "deposit"
        assert result.rows[0].amount_eur == Decimal("2500.00")

    def test_balance_row(self):
        content = "date,type,isin_or_name,quantity,price,amount_eur,description\n2025-06-01,balance,savings account,,,5000.00,\n"
        result = gen_parser.parse(content)
        assert result.rows[0].row_type == "balance"

    def test_no_errors_on_valid_input(self):
        content = "date,type,isin_or_name,quantity,price,amount_eur,description\n2025-01-01,dividend,US0378331005,,,1.50,Q1 dividend\n"
        result = gen_parser.parse(content)
        assert result.errors == []
