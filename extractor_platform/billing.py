"""
extractor_platform/billing.py — Per-page billing metering.

Computes costs from pipeline billing snapshots, records billing events,
and manages user credit balances.

Pricing model:
    - Native pages : base rate (text-selectable PDFs, pdfplumber path)
    - Image pages  : higher rate (scanned PDFs, Claude vision path)

Rates are defined here as defaults but can be overridden per user tier
or passed explicitly for flexibility.
"""

from datetime import datetime, timezone
from typing import Optional
from extractor_platform.models import BillingEvent


# ── Default rates (USD per page) ─────────────────────────────────────────────

RATES = {
    "payg": {
        "native": 0.005,   # $0.005 per native page
        "image":  0.015,   # $0.015 per image page (3x — vision call overhead)
    },
    "bulk": {
        "native": 0.003,
        "image":  0.010,
    },
    "subscription": {
        "native": 0.002,
        "image":  0.007,
    },
}

# Minimum charge per job regardless of page count
MINIMUM_CHARGE = 0.01  # $0.01


class BillingManager:

    def __init__(self, supabase_client):
        self.db = supabase_client

    # ─────────────────────────────────────────────
    # RATE RESOLUTION
    # ─────────────────────────────────────────────

    def get_rates(self, tier: str) -> dict:
        """
        Return the native and image rates for a given user tier.
        Falls back to payg if tier is unrecognised.
        """
        return RATES.get(tier, RATES["payg"])

    def estimate_cost(
        self,
        native_pages: int,
        image_pages: int,
        tier: str = "payg",
    ) -> dict:
        """
        Estimate cost before a job runs.
        Useful for pre-flight checks and API responses.

        Returns:
        {
            "native_pages": N,
            "image_pages":  N,
            "native_rate":  0.005,
            "image_rate":   0.015,
            "native_cost":  0.05,
            "image_cost":   0.06,
            "total_cost":   0.11,
            "currency":     "USD",
        }
        """
        rates       = self.get_rates(tier)
        native_cost = round(native_pages * rates["native"], 4)
        image_cost  = round(image_pages  * rates["image"],  4)
        total_cost  = max(
            round(native_cost + image_cost, 4),
            MINIMUM_CHARGE if (native_pages + image_pages) > 0 else 0,
        )

        return {
            "native_pages": native_pages,
            "image_pages":  image_pages,
            "native_rate":  rates["native"],
            "image_rate":   rates["image"],
            "native_cost":  native_cost,
            "image_cost":   image_cost,
            "total_cost":   total_cost,
            "currency":     "USD",
        }

    # ─────────────────────────────────────────────
    # RECORDING BILLING EVENTS
    # ─────────────────────────────────────────────

    def record_billing_event(
        self,
        job_id: str,
        api_user_id: str,
        pipeline_billing: dict,
        tier: str = "payg",
    ) -> BillingEvent:
        """
        Create and persist a billing event from a pipeline billing snapshot.

        pipeline_billing is the 'billing' key from run_pipeline() result:
        {
            "total_native": N,
            "total_image":  N,
            "questions_pdf": {"native": N, "image": N},
            "schemes_pdf":   {"native": N, "image": N},
        }

        Returns the BillingEvent with computed costs.
        """
        rates        = self.get_rates(tier)
        native_pages = pipeline_billing.get("total_native", 0)
        image_pages  = pipeline_billing.get("total_image",  0)

        event = BillingEvent(
            job_id=job_id,
            api_user_id=api_user_id,
            native_pages=native_pages,
            image_pages=image_pages,
            native_rate=rates["native"],
            image_rate=rates["image"],
        )

        # Apply minimum charge
        if event.total_cost < MINIMUM_CHARGE and (native_pages + image_pages) > 0:
            # Record the minimum as a note in status rather than mutating the rates
            event.status = "pending"

        self.db.table("billing_events").insert(
            event.to_insert_dict()
        ).execute()

        return event

    def mark_charged(self, billing_event_id: str):
        """Mark a billing event as successfully charged."""
        self.db.table("billing_events").update({
            "status": "charged"
        }).eq("id", billing_event_id).execute()

    def mark_waived(self, billing_event_id: str):
        """Mark a billing event as waived (e.g. free tier, error recovery)."""
        self.db.table("billing_events").update({
            "status": "waived"
        }).eq("id", billing_event_id).execute()

    # ─────────────────────────────────────────────
    # CREDIT BALANCE
    # ─────────────────────────────────────────────

    def get_balance(self, api_user_id: str) -> float:
        """Return the current credit balance for a user."""
        result = (
            self.db.table("api_users")
            .select("credit_balance")
            .eq("id", api_user_id)
            .single()
            .execute()
        )
        return float(result.data.get("credit_balance", 0.0))

    def reserve_credits(self, api_user_id: str, amount: float) -> float:
        """
        Atomically reserve credits at job start using a Supabase RPC function
        with row-level locking. Prevents concurrent jobs from overdrawing
        the same balance (check-then-act race condition).

        Returns the new balance after reservation.
        Raises InsufficientCreditsError if balance is insufficient.
        """
        try:
            result = self.db.rpc("reserve_credits", {
                "p_user_id": api_user_id,
                "p_amount":  round(amount, 4),
            }).execute()
            return float(result.data)
        except Exception as e:
            if "Insufficient credits" in str(e):
                raise InsufficientCreditsError(
                    f"Insufficient credits to start job. Required: ${amount:.4f}"
                )
            raise

    def reconcile_credits(
        self,
        api_user_id: str,
        reserved_amount: float,
        actual_amount: float,
    ) -> float:
        """
        Reconcile reserved credits against actual cost after pipeline completes.
        Refunds the difference if actual < reserved.
        Charges the shortfall if actual > reserved.
        """
        result = self.db.rpc("reconcile_credits", {
            "p_user_id":  api_user_id,
            "p_reserved": round(reserved_amount, 4),
            "p_actual":   round(actual_amount, 4),
        }).execute()
        return float(result.data)

    def deduct_credits(self, api_user_id: str, amount: float) -> float:
        """
        Legacy direct deduction — use reserve_credits() + reconcile_credits()
        for new code. Kept for backwards compatibility with admin tooling.
        """
        current = self.get_balance(api_user_id)
        if current < amount:
            raise InsufficientCreditsError(
                f"Insufficient credits: balance ${current:.4f}, "
                f"required ${amount:.4f}"
            )
        new_balance = round(current - amount, 4)
        self.db.table("api_users").update({
            "credit_balance": new_balance,
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }).eq("id", api_user_id).execute()
        return new_balance

    def add_credits(self, api_user_id: str, amount: float) -> float:
        """
        Add credits to a user's balance (top-up or refund).
        Returns the new balance.
        """
        current     = self.get_balance(api_user_id)
        new_balance = round(current + amount, 4)
        self.db.table("api_users").update({
            "credit_balance": new_balance,
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }).eq("id", api_user_id).execute()
        return new_balance

    def has_sufficient_credits(
        self,
        api_user_id: str,
        native_pages: int,
        image_pages: int,
        tier: str = "payg",
    ) -> bool:
        """
        Pre-flight check — returns True if the user has enough credits
        to cover the estimated cost of a job.
        """
        estimate = self.estimate_cost(native_pages, image_pages, tier)
        balance  = self.get_balance(api_user_id)
        return balance >= estimate["total_cost"]

    # ─────────────────────────────────────────────
    # REPORTING
    # ─────────────────────────────────────────────

    def get_usage_summary(self, api_user_id: str) -> dict:
        """
        Return aggregate usage stats for a user across all billed jobs.
        """
        result = (
            self.db.table("billing_events")
            .select("native_pages, image_pages, total_cost, status")
            .eq("api_user_id", api_user_id)
            .execute()
        )
        rows = result.data or []

        total_native = sum(r["native_pages"] for r in rows)
        total_image  = sum(r["image_pages"]  for r in rows)
        total_spent  = sum(r["total_cost"]   for r in rows if r["status"] == "charged")
        total_jobs   = len(rows)

        return {
            "total_jobs":        total_jobs,
            "total_native_pages": total_native,
            "total_image_pages":  total_image,
            "total_pages":        total_native + total_image,
            "total_spent_usd":    round(total_spent, 4),
            "currency":           "USD",
        }


# ─────────────────────────────────────────────
# EXCEPTIONS
# ─────────────────────────────────────────────

class InsufficientCreditsError(Exception):
    """Raised when a user's credit balance cannot cover a job's cost."""
    pass