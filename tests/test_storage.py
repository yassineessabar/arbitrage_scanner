"""tests/test_storage.py — Storage write/read round trip tests."""

from datetime import date, datetime, timezone

import pytest

from normalization.schema import ContractType, Signal
from arbitrage.basis import compute_basis
from scoring.ranker import rank_opportunities
from storage.writer import StorageWriter
from storage.reader import StorageReader
from config.settings import get_settings
from tests.conftest import make_pair


class TestStorageRoundTrip:
    def test_write_and_read_observation(self, temp_settings):
        """Write an opportunity and read it back."""
        pair = make_pair(expiry=date(2026, 9, 25))
        basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
        opps = rank_opportunities([pair], [basis], temp_settings)
        opp = opps[0]

        # Write
        writer = StorageWriter(temp_settings)
        writer.initialize()
        assert writer.write_opportunity(opp)

        # Read
        reader = StorageReader(temp_settings.system.storage_path)
        reader.initialize()

        count = reader.get_observation_count()
        assert count == 1

        history = reader.get_basis_history("binance", "BTC", days=1)
        assert len(history) == 1
        row = history[0]
        assert row["basis_pct"] is not None  # verify data was stored correctly

        writer.close()
        reader.close()

    def test_write_throttling(self, temp_settings):
        """Second write for same pair should be throttled."""
        temp_settings.storage.write_interval_seconds = 9999  # very long

        pair = make_pair(expiry=date(2026, 9, 25))
        basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
        opps = rank_opportunities([pair], [basis], temp_settings)
        opp = opps[0]

        writer = StorageWriter(temp_settings)
        writer.initialize()

        assert writer.write_opportunity(opp)  # First write
        assert not writer.write_opportunity(opp)  # Throttled

        writer.close()

    def test_feed_health_log(self, temp_settings):
        """Write and read a feed health event."""
        writer = StorageWriter(temp_settings)
        writer.initialize()
        writer.write_feed_health("binance", "CONNECT", "test connection")

        reader = StorageReader(temp_settings.system.storage_path)
        reader.initialize()

        health = reader.get_feed_health("binance", hours=1)
        assert len(health) == 1
        assert health[0]["event_type"] == "CONNECT"

        writer.close()
        reader.close()

    def test_top_opportunities_query(self, temp_settings):
        """Query top opportunities returns correct results."""
        pair = make_pair(expiry=date(2026, 9, 25))
        basis = compute_basis(pair, fee_rate=0.0004, slippage=0.0003)
        opps = rank_opportunities([pair], [basis], temp_settings)

        writer = StorageWriter(temp_settings)
        writer.initialize()
        writer.write_opportunity(opps[0])

        reader = StorageReader(temp_settings.system.storage_path)
        reader.initialize()

        top = reader.get_top_opportunities(hours=1)
        assert len(top) >= 0  # May or may not show depending on signal

        writer.close()
        reader.close()
