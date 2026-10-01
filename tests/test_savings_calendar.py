"""Regression checks for calendar-month interest and delayed crediting."""
import sqlite3
import unittest
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from app.services.savings import account_interest


class CalendarInterestTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        for path in sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql")):
            self.conn.executescript(path.read_text())
        self.conn.execute("INSERT INTO accounts(id,name,type,currency) VALUES(1,'Test','savings','EUR')")
        self.conn.execute("INSERT INTO balance_snapshots(account_id,date,balance_eur) VALUES(1,'2026-07-01','11973.07')")
        self.conn.execute("INSERT INTO savings_interest_rates(account_id,annual_rate,payout_frequency,starts_on,payout_on) VALUES(1,'1.3','monthly','2026-07-01','2026-07-05')")

    def tearDown(self):
        self.conn.close()

    def test_payout_date_month_does_not_discard_interest(self):
        for configured in ('2026-07-05', '2026-08-05', '2026-09-05'):
            with self.subTest(configured=configured):
                self.conn.execute("UPDATE savings_interest_rates SET payout_on=?", (configured,))
                self.assertEqual(account_interest(self.conn, 1, date(2026, 8, 4))["interest"], Decimal('0'))
                result = account_interest(self.conn, 1, date(2026, 8, 5))
                self.assertEqual(result['interest'], Decimal('13.22'))
                self.assertEqual(result['events'][0]['date'], '2026-08-05')

    def test_compounding_starts_on_credit_date(self):
        result = account_interest(self.conn, 1, date(2026, 9, 5))
        expected = ((Decimal('11973.07') * 4 + Decimal('11986.29') * 27) * Decimal('.013') / 365).quantize(Decimal('.01'), ROUND_HALF_UP)
        self.assertEqual(result['events'][0]['amount'], expected)

    def test_last_day_deposit_counts_one_day(self):
        self.conn.execute("INSERT INTO cash_events(account_id,ts,type,amount_eur) VALUES(1,'2026-07-31','deposit','1000')")
        expected = ((Decimal('11973.07') * 31 + 1000) * Decimal('.013') / 365).quantize(Decimal('.01'), ROUND_HALF_UP)
        self.assertEqual(account_interest(self.conn, 1, date(2026, 8, 5))['interest'], expected)

    def test_ended_rate_still_pays_next_month(self):
        self.conn.execute("UPDATE savings_interest_rates SET ends_on='2026-07-31'")
        self.assertEqual(account_interest(self.conn, 1, date(2026, 8, 4))['next_payout'], '2026-08-05')
        self.assertEqual(account_interest(self.conn, 1, date(2026, 9, 5))['interest'], Decimal('13.22'))

    def test_payment_day_31_is_clamped_without_drift(self):
        self.conn.execute("UPDATE savings_interest_rates SET payout_on='2026-01-31', starts_on='2026-01-01'")
        self.conn.execute("UPDATE balance_snapshots SET date='2026-01-01'")
        result = account_interest(self.conn, 1, date(2026, 3, 31))
        self.assertEqual([event['date'] for event in result['events']], ['2026-03-31', '2026-02-28'])

    def test_midmonth_snapshot_does_not_shift_calendar(self):
        self.conn.execute("UPDATE balance_snapshots SET date='2026-07-15'")
        result = account_interest(self.conn, 1, date(2026, 8, 5))
        self.assertEqual(result['interest'], Decimal('7.25'))


if __name__ == '__main__':
    unittest.main()
