"""Ten-year history boundaries, sparse windows and non-destructive exports."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock
from scripts import export_history as eh
from scripts.lake_prune import _build_parser as prune_parser
from src.execution.broker import types as T
from src.data.lake import Lake
from src.execution.broker.errors import BrokerConnectionError
import json


def candle(year, close=1.5):
    return T.Candle(time=datetime(year, 1, 1, tzinfo=timezone.utc), open=1, high=2,
                    low=.5, close=close, tick_volume=1, spread_points=0)


class HistoryExtension(unittest.IsolatedAsyncioTestCase):
    async def test_empty_middle_window_does_not_hide_older_data(self):
        class Broker:
            calls = 0
            async def get_candles_range(self, *args):
                self.calls += 1
                return [candle(2025)] if self.calls == 1 else [candle(2023)] if self.calls == 3 else []
        broker = Broker()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = await eh.pull_history(broker, 'EURUSD', T.Timeframe.D1, now=now,
                                    max_lookback=timedelta(days=365*3+1), chunk=timedelta(days=366))
        self.assertEqual([b.time.year for b in bars], [2023, 2025])
        self.assertEqual(broker.calls, 3)

    async def test_invalid_chunk_cannot_loop_forever(self):
        with self.assertRaises(ValueError):
            await eh.pull_history(None, 'EURUSD', T.Timeframe.D1, now=datetime.now(timezone.utc),
                                  max_lookback=timedelta(days=365), chunk=timedelta(0))

    async def test_failed_batch_preserves_csv_and_reports_unattempted_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = eh.candles_to_csv([candle(2016)])
            paths = [Path(tmp)/'AUDUSD_D1.csv', Path(tmp)/'EURUSD_M5.csv']
            for path in paths:
                path.write_text(original)
            args = eh._build_parser().parse_args(['--all-history', '--history-dir', tmp])
            broker = AsyncMock()
            broker.__aenter__.return_value = broker
            broker.get_candles_range.side_effect = BrokerConnectionError('offline')
            with patch.object(eh, 'MT5HttpBroker', return_value=broker):
                self.assertEqual(await eh._run(args), 1)
            self.assertTrue(all(p.read_text() == original for p in paths))
            report = json.loads((Path(tmp)/'coverage.json').read_text())
            self.assertEqual([r['status'] for r in report['series']], ['error', 'not_attempted'])
            self.assertEqual(report['series'][0]['existing_bars'], 1)
            self.assertTrue(report['aborted'])

    def test_shorter_response_preserves_old_data_and_updates_overlap(self):
        merged = eh.merge_history([candle(2016), candle(2025)], [candle(2025, 1.75)])
        self.assertEqual([b.time.year for b in merged], [2016, 2025])
        self.assertEqual(merged[-1].close, 1.75)

    def test_atomic_failure_leaves_existing_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'EURUSD_D1.csv'
            original = eh.candles_to_csv([candle(2016)])
            path.write_text(original)
            with patch('scripts.export_history.os.replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    eh.atomic_write(path, 'replacement')
            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_batch_excludes_trade_reports_and_keeps_timeframes(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ['EURUSD_M5.csv', 'EURUSD_D1.csv', 'sb_stops_trades_H1.csv']:
                (Path(tmp)/name).touch()
            args=eh._build_parser().parse_args(['--all-history', '--history-dir', tmp])
            self.assertEqual([(s,t) for s,t,_ in eh.export_jobs(args)], [('EURUSD','D1'),('EURUSD','M5')])

    def test_calendar_year_target_and_leap_day(self):
        now=datetime(2026,9,21,tzinfo=timezone.utc)
        self.assertEqual(eh.history_floor(now,10).year,2016)
        self.assertEqual(eh.history_floor(datetime(2024,2,29,tzinfo=timezone.utc),5).day,28)
        self.assertEqual(eh._build_parser().parse_args([]).years,10)
        self.assertEqual(prune_parser().parse_args([]).active_years,10)

    def test_default_pruning_retains_ten_year_research_window(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            lake=Lake(tmp)
            lake.ingest(pd.DataFrame([{'time':'2017-01-02','open':1,'high':2,'low':.5,'close':1.5}]),
                        broker='fbs',symbol='EURUSD',tf='D1',source='test')
            self.assertEqual(lake.prune(now=datetime(2026,9,21,tzinfo=timezone.utc),unused_days=-1),[])
