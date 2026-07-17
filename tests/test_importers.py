"""Tests for DeGiro CSV importers."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.importers import degiro_transactions as txn_parser
from app.importers import degiro_account as acc_parser
from app.importers import generic as gen_parser


# ── Transactions.csv ──────────────────────────────────────────────────────────

class TestTransactionsParser:
    def test_detects_transactions_csv(self, transactions_csv):
        assert txn_parser.is_transactions_csv(transactions_csv)

    def test_does_not_detect_account_csv(self, account_csv):
        assert not txn_parser.is_transactions_csv(account_csv)

    def test_parses_correct_row_count(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        assert len(result.rows) == 3
        assert result.errors == []

    def test_buy_row_positive_quantity(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        buys = [r for r in result.rows if r.quantity > 0]
        assert len(buys) == 2

    def test_sell_row_negative_quantity(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        sells = [r for r in result.rows if r.quantity < 0]
        assert len(sells) == 1
        assert sells[0].quantity == Decimal("-2")

    def test_dutch_decimal_price(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        vwrl = next(r for r in result.rows if r.isin == "IE00B3RBWM25" and r.quantity > 0)
        assert vwrl.price == Decimal("112.45")

    def test_fx_rate_parsed(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        aapl = next(r for r in result.rows if r.isin == "US0378331005")
        assert aapl.fx_rate == Decimal("1.0837")

    def test_fees_parsed(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        vwrl = next(r for r in result.rows if r.isin == "IE00B3RBWM25" and r.quantity > 0)
        assert vwrl.fees_eur == Decimal("-1.00")

    def test_order_id_preserved(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        vwrl = next(r for r in result.rows if r.isin == "IE00B3RBWM25" and r.quantity > 0)
        assert vwrl.order_id == "5c7e9a1b-33d5-4f6e-9b8c-0d1e2f3a4b05"

    def test_date_converted_to_iso(self, transactions_csv):
        result = txn_parser.parse(transactions_csv)
        assert result.rows[0].ts.startswith("2025-01-16")

    def test_bom_handling(self, transactions_csv):
        bom_content = "\ufeff" + transactions_csv
        result = txn_parser.parse(bom_content)
        assert len(result.rows) == 3

    def test_empty_rows_ignored(self):
        content = (
            "Datum,Tijd,Product,ISIN,Beurs,Uitvoeringsplaats,Aantal,Koers,,Lokale waarde,,Waarde,,Wisselkoers,Transactiekosten en/of,,Totaal,,Order ID\n"
            "\n"
            ",,,,,,,,,,,,,,,,,,\n"
        )
        result = txn_parser.parse(content)
        assert len(result.rows) == 0

    def test_commit_no_duplicates(self, transactions_csv, mem_db):
        result = txn_parser.parse(transactions_csv)
        imp, skip, errors = txn_parser.commit_transactions(mem_db, result, account_id=1)
        mem_db.commit()
        assert imp == 3
        assert skip == 0
        assert errors == []

    def test_reimport_idempotent(self, transactions_csv, mem_db):
        result = txn_parser.parse(transactions_csv)
        txn_parser.commit_transactions(mem_db, result, account_id=1)
        mem_db.commit()
        # Import again — all should be duplicates
        imp2, skip2, _ = txn_parser.commit_transactions(mem_db, result, account_id=1)
        assert imp2 == 0
        assert skip2 == 3

    def test_malformed_price_defaults_to_zero(self):
        content = (
            "Datum,Tijd,Product,ISIN,Beurs,Uitvoeringsplaats,Aantal,Koers,,Lokale waarde,,Waarde,,Wisselkoers,Transactiekosten en/of,,Totaal,,Order ID\n"
            "16-01-2025,10:04,Test Product,NL0000000001,,,,NOT_A_NUMBER,EUR,0,EUR,0,EUR,,0,EUR,0,EUR,ORDER1\n"
        )
        result = txn_parser.parse(content)
        # Should not raise; price should parse to 0
        assert result.rows[0].price == Decimal("0")


# ── Account.csv ──────────────────────────────────────────────────────────────

class TestAccountParser:
    def test_detects_account_csv(self, account_csv):
        assert acc_parser.is_account_csv(account_csv)

    def test_does_not_detect_transactions_csv(self, transactions_csv):
        assert not acc_parser.is_account_csv(transactions_csv)

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

    def test_reimport_idempotent(self, account_csv, mem_db):
        result = acc_parser.parse(account_csv)
        acc_parser.commit_account_events(mem_db, result, account_id=1)
        mem_db.commit()
        imp2, skip2, _ = acc_parser.commit_account_events(mem_db, result, account_id=1)
        # All previously imported rows should be skipped
        assert imp2 == 0

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
