"""Run with: python3.12 -m unittest discover -s . -p 'test_*.py' -v"""

import csv
import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from generate_flights import dt, generate, next_month, validate, write_data


class GeneratorTests(unittest.TestCase):
    def test_randomized_operational_consistency(self):
        # Multiple seeds exercise delay propagation, maintenance, cancellations and changes.
        totals = Counter()
        for seed in range(30):
            with self.subTest(seed=seed):
                meta, data = generate(datetime(2026, 11, 12, 18, tzinfo=timezone.utc), 10, 5, seed, 2)
                validate(meta, data)
                totals.update(f['status'] for f in data['flights'])
                totals['changes'] += len(data['flight_changes'])
                for f in data['flights']:
                    if f['actual_arrival_utc']:
                        self.assertGreater(dt(f['actual_arrival_utc']), dt(f['actual_departure_utc']))
        self.assertGreater(totals['canceled'], 0)
        self.assertGreater(totals['arrived'], 0)
        self.assertGreater(totals['changes'], 0)

    def test_month_and_year_boundaries(self):
        for stamp in ('2024-01-31T12:00:00Z', '2026-01-31T12:00:00Z',
                      '2026-12-31T12:00:00Z', '2026-03-08T07:00:00Z',
                      '2026-11-01T06:00:00Z'):
            with self.subTest(stamp=stamp):
                snapshot = dt(stamp)
                future = min(28, (next_month(snapshot.date()) - snapshot.date()).days)
                meta, data = generate(snapshot, 3, future, 123, 1)
                validate(meta, data)
        self.assertEqual(next_month(dt('2024-01-31T00:00:00Z').date()).isoformat(), '2024-02-29')
        self.assertEqual(next_month(dt('2026-01-31T00:00:00Z').date()).isoformat(), '2026-02-28')

    def test_single_day_empty_optional_tables(self):
        meta, data = generate(dt('2026-11-12T00:00:00Z'), 0, 0, 1, 1, 0)
        validate(meta, data)
        self.assertEqual(len(data['flights']), 2)
        self.assertFalse(data['flight_changes'])
        with tempfile.TemporaryDirectory() as folder:
            write_data(Path(folder), meta, data)
            header = (Path(folder) / 'csv' / 'flight_changes.csv').read_text()
            self.assertTrue(header.startswith('change_id,booking_id,'))

    def test_reproducibility(self):
        args = (dt('2026-11-12T18:00:00Z'), 2, 2, 42, 1)
        self.assertEqual(generate(*args), generate(*args))

    def test_exports_match(self):
        meta, data = generate(dt('2026-11-12T18:00:00Z'), 1, 1, 42, 1)
        validate(meta, data)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_data(root, meta, data)
            exported = json.loads((root / 'dataset.json').read_text())
            self.assertEqual(exported, {'metadata': meta, **data})
            for name, rows in data.items():
                with (root / 'csv' / f'{name}.csv').open(newline='') as handle:
                    records = list(csv.DictReader(handle))
                self.assertEqual(len(records), len(rows), name)
                for record, row in zip(records, rows):
                    for key, value in row.items():
                        expected = '' if value is None else str(value).lower() if isinstance(value, bool) else str(value)
                        self.assertEqual(record[key], expected, f'{name}.{key}')

    def test_validation_rejects_overbooking(self):
        meta, data = generate(dt('2026-11-12T18:00:00Z'), 0, 1, 42, 1)
        data['flights'][0]['seat_capacity'] = 59
        with self.assertRaisesRegex(ValueError, 'flight load'):
            validate(meta, data)

    def test_maximum_window(self):
        meta, data = generate(dt('2026-11-12T18:00:00Z'), 31, 28, 42, 1)
        validate(meta, data)
        self.assertEqual(meta['calendar_days'], 60)

    def test_changes_reconcile_with_original_inventory(self):
        meta, data = generate(dt('2026-11-12T18:00:00Z'), 2, 7, 42, 2, 1.0)
        validate(meta, data)
        self.assertTrue(data['flight_changes'])
        bookings = {b['booking_id']: b for b in data['bookings']}
        for change in data['flight_changes']:
            booking = bookings[change['booking_id']]
            self.assertEqual(booking['flight_id'], change['to_flight_id'])
            self.assertEqual(booking['original_flight_id'], change['from_flight_id'])
            self.assertAlmostEqual(change['total_adjustment_usd'], change['change_fee_usd'] + change['fare_difference_usd'], places=2)


if __name__ == '__main__':
    unittest.main()
