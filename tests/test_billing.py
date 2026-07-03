# Copyright (c) 2025 Rubeeq. All rights reserved. See LICENSE for terms.
"""
tests/test_billing.py — Unit tests for billing math and rate logic.

Tests cost estimation, rate resolution by tier, minimum charge,
and the InsufficientCreditsError. Does not test the Supabase RPC calls
(those require a live DB) — reserve_credits and reconcile_credits are
tested via mock.
"""

import pytest
from unittest.mock import MagicMock, patch
from extractor_platform.billing import BillingManager, InsufficientCreditsError, RATES, MINIMUM_CHARGE


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def bm(mock_db):
    return BillingManager(mock_db)


class TestRates:

    def test_all_tiers_present(self):
        for tier in ["payg", "bulk", "subscription"]:
            assert tier in RATES
            assert "native" in RATES[tier]
            assert "image"  in RATES[tier]

    def test_image_more_expensive_than_native(self):
        for tier in RATES:
            assert RATES[tier]["image"] > RATES[tier]["native"], \
                f"image should cost more than native for tier {tier}"

    def test_bulk_cheaper_than_payg(self):
        assert RATES["bulk"]["native"]  < RATES["payg"]["native"]
        assert RATES["bulk"]["image"]   < RATES["payg"]["image"]

    def test_subscription_cheapest(self):
        assert RATES["subscription"]["native"] < RATES["bulk"]["native"]
        assert RATES["subscription"]["image"]  < RATES["bulk"]["image"]


class TestEstimateCost:

    def test_zero_pages(self, bm):
        est = bm.estimate_cost(0, 0, tier="payg")
        assert est["total_cost"] == 0

    def test_native_only(self, bm):
        est = bm.estimate_cost(native_pages=10, image_pages=0, tier="payg")
        expected = round(10 * RATES["payg"]["native"], 4)
        assert est["native_cost"] == expected
        assert est["image_cost"]  == 0

    def test_image_only(self, bm):
        est = bm.estimate_cost(native_pages=0, image_pages=5, tier="payg")
        expected = round(5 * RATES["payg"]["image"], 4)
        assert est["image_cost"]   == expected
        assert est["native_cost"]  == 0

    def test_mixed_pages(self, bm):
        est = bm.estimate_cost(native_pages=10, image_pages=4, tier="payg")
        expected_native = round(10 * RATES["payg"]["native"], 4)
        expected_image  = round(4  * RATES["payg"]["image"],  4)
        assert est["native_cost"] == expected_native
        assert est["image_cost"]  == expected_image
        assert est["total_cost"]  == round(expected_native + expected_image, 4)

    def test_minimum_charge_applied(self, bm):
        est = bm.estimate_cost(native_pages=1, image_pages=0, tier="payg")
        assert est["total_cost"] >= MINIMUM_CHARGE

    def test_minimum_not_applied_to_zero_pages(self, bm):
        est = bm.estimate_cost(0, 0, tier="payg")
        assert est["total_cost"] == 0

    def test_bulk_tier_cheaper_than_payg(self, bm):
        payg = bm.estimate_cost(10, 5, tier="payg")
        bulk = bm.estimate_cost(10, 5, tier="bulk")
        assert bulk["total_cost"] < payg["total_cost"]

    def test_unknown_tier_falls_back_to_payg(self, bm):
        est_unknown = bm.estimate_cost(10, 5, tier="enterprise")
        est_payg    = bm.estimate_cost(10, 5, tier="payg")
        assert est_unknown["total_cost"] == est_payg["total_cost"]

    def test_returns_correct_keys(self, bm):
        est = bm.estimate_cost(5, 2, tier="payg")
        for key in ["native_pages","image_pages","native_rate","image_rate",
                    "native_cost","image_cost","total_cost","currency"]:
            assert key in est

    def test_currency_is_usd(self, bm):
        est = bm.estimate_cost(5, 2, tier="payg")
        assert est["currency"] == "USD"


class TestReserveCredits:

    def test_reserve_calls_rpc(self, bm, mock_db):
        mock_db.rpc.return_value.execute.return_value.data = 95.0
        result = bm.reserve_credits("user-123", 5.0)
        mock_db.rpc.assert_called_once_with("reserve_credits", {
            "p_user_id": "user-123",
            "p_amount":  5.0,
        })
        assert result == 95.0

    def test_insufficient_credits_raises(self, bm, mock_db):
        mock_db.rpc.return_value.execute.side_effect = Exception(
            "Insufficient credits: balance 2.0000, required 5.0000"
        )
        with pytest.raises(InsufficientCreditsError):
            bm.reserve_credits("user-123", 5.0)

    def test_other_exception_propagates(self, bm, mock_db):
        mock_db.rpc.return_value.execute.side_effect = Exception("Connection timeout")
        with pytest.raises(Exception, match="Connection timeout"):
            bm.reserve_credits("user-123", 5.0)


class TestReconcileCredits:

    def test_reconcile_calls_rpc(self, bm, mock_db):
        mock_db.rpc.return_value.execute.return_value.data = 97.5
        result = bm.reconcile_credits("user-123", reserved_amount=5.0, actual_amount=2.5)
        mock_db.rpc.assert_called_once_with("reconcile_credits", {
            "p_user_id":  "user-123",
            "p_reserved": 5.0,
            "p_actual":   2.5,
        })
        assert result == 97.5

    def test_reconcile_returns_new_balance(self, bm, mock_db):
        mock_db.rpc.return_value.execute.return_value.data = 88.25
        result = bm.reconcile_credits("user-456", 10.0, 10.0)
        assert result == 88.25


class TestGetBalance:

    def test_returns_balance(self, bm, mock_db):
        mock_db.table.return_value.select.return_value.eq.return_value \
            .single.return_value.execute.return_value.data = {"credit_balance": 42.5}
        assert bm.get_balance("user-123") == 42.5

    def test_returns_zero_if_missing(self, bm, mock_db):
        mock_db.table.return_value.select.return_value.eq.return_value \
            .single.return_value.execute.return_value.data = {}
        assert bm.get_balance("user-123") == 0.0
