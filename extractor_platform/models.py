"""
platform/models.py — Platform database schema definitions.

These are the PLATFORM tables — they track jobs, billing, users, and
output artefacts. They are entirely separate from content tables
(exam_papers, questions etc.) which live in each profile's schema_sql().

Two ways to use this module:
    1. generate_platform_schema() — returns the SQL as a string to run
       once on your platform database
    2. The dataclass definitions — used by job_tracker.py and billing.py
       as typed containers when reading/writing platform DB rows
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json


# ─────────────────────────────────────────────
# SQL SCHEMA
# ─────────────────────────────────────────────

def generate_platform_schema() -> str:
    return """
-- ── Platform DB — Product A (Extraction Engine) ─────────────────────────────
-- Tracks API users, jobs, output artefacts, and billing.
-- Entirely separate from content tables (questions, schemes etc.)
-- Run once on your platform database. Safe to re-run (IF NOT EXISTS).

-- API users and access keys
CREATE TABLE IF NOT EXISTS api_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    api_key         TEXT NOT NULL UNIQUE,
    tier            TEXT NOT NULL DEFAULT 'payg'
                    CHECK (tier IN ('payg', 'bulk', 'subscription')),
    credit_balance  NUMERIC(10, 4) DEFAULT 0.0,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per extraction job (one PDF pair = one job)
CREATE TABLE IF NOT EXISTS processing_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_user_id         UUID REFERENCES api_users(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','running','complete','partial','failed')),
    exam_type           TEXT,
    questions_pdf_path  TEXT,
    scheme_pdf_path     TEXT,
    total_pages         INTEGER DEFAULT 0,
    native_pages        INTEGER DEFAULT 0,
    image_pages         INTEGER DEFAULT 0,
    questions_extracted INTEGER DEFAULT 0,
    schemes_extracted   INTEGER DEFAULT 0,
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now()
);

-- Output artefacts produced per job, with expiry
CREATE TABLE IF NOT EXISTS output_artifacts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      UUID REFERENCES processing_jobs(id) ON DELETE CASCADE,
    artifact_type   TEXT NOT NULL
                    CHECK (artifact_type IN ('schema.sql','data.json','insert.py')),
    storage_path    TEXT NOT NULL,
    size_bytes      INTEGER,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per billable event (one job typically produces one billing event)
CREATE TABLE IF NOT EXISTS billing_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID REFERENCES processing_jobs(id) ON DELETE SET NULL,
    api_user_id     UUID REFERENCES api_users(id) ON DELETE SET NULL,
    native_pages    INTEGER DEFAULT 0,
    image_pages     INTEGER DEFAULT 0,
    native_rate     NUMERIC(10, 6) NOT NULL,
    image_rate      NUMERIC(10, 6) NOT NULL,
    native_cost     NUMERIC(10, 4) NOT NULL,
    image_cost      NUMERIC(10, 4) NOT NULL,
    total_cost      NUMERIC(10, 4) NOT NULL,
    currency        TEXT DEFAULT 'USD',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','charged','refunded','waived')),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_processing_jobs_user
    ON processing_jobs(api_user_id);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_status
    ON processing_jobs(status);

CREATE INDEX IF NOT EXISTS idx_output_artifacts_job
    ON output_artifacts(job_id);

CREATE INDEX IF NOT EXISTS idx_billing_events_user
    ON billing_events(api_user_id);

CREATE INDEX IF NOT EXISTS idx_billing_events_job
    ON billing_events(job_id);
"""


# ─────────────────────────────────────────────
# DATACLASSES — typed containers for platform rows
# ─────────────────────────────────────────────

@dataclass
class APIUser:
    email:          str
    api_key:        str
    tier:           str = "payg"
    credit_balance: float = 0.0
    is_active:      bool = True
    id:             Optional[str] = None
    created_at:     Optional[datetime] = None
    updated_at:     Optional[datetime] = None


@dataclass
class ProcessingJob:
    api_user_id:         Optional[str]
    questions_pdf_path:  str
    scheme_pdf_path:     Optional[str] = None
    status:              str = "pending"
    exam_type:           Optional[str] = None
    total_pages:         int = 0
    native_pages:        int = 0
    image_pages:         int = 0
    questions_extracted: int = 0
    schemes_extracted:   int = 0
    error_message:       Optional[str] = None
    started_at:          Optional[datetime] = None
    completed_at:        Optional[datetime] = None
    id:                  Optional[str] = None
    created_at:          Optional[datetime] = None

    def to_insert_dict(self) -> dict:
        return {
            "api_user_id":        self.api_user_id,
            "status":             self.status,
            "questions_pdf_path": self.questions_pdf_path,
            "scheme_pdf_path":    self.scheme_pdf_path,
        }

    def to_update_dict(self) -> dict:
        return {
            "status":              self.status,
            "exam_type":           self.exam_type,
            "total_pages":         self.total_pages,
            "native_pages":        self.native_pages,
            "image_pages":         self.image_pages,
            "questions_extracted": self.questions_extracted,
            "schemes_extracted":   self.schemes_extracted,
            "error_message":       self.error_message,
            "started_at":          self.started_at.isoformat() if self.started_at else None,
            "completed_at":        self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class OutputArtifact:
    job_id:        str
    artifact_type: str
    storage_path:  str
    size_bytes:    Optional[int] = None
    expires_at:    Optional[datetime] = None
    id:            Optional[str] = None
    created_at:    Optional[datetime] = None

    def to_insert_dict(self) -> dict:
        return {
            "job_id":        self.job_id,
            "artifact_type": self.artifact_type,
            "storage_path":  self.storage_path,
            "size_bytes":    self.size_bytes,
            "expires_at":    self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class BillingEvent:
    job_id:       Optional[str]
    api_user_id:  Optional[str]
    native_pages: int
    image_pages:  int
    native_rate:  float
    image_rate:   float
    currency:     str = "USD"
    status:       str = "pending"
    id:           Optional[str] = None
    created_at:   Optional[datetime] = None

    @property
    def native_cost(self) -> float:
        return round(self.native_pages * self.native_rate, 4)

    @property
    def image_cost(self) -> float:
        return round(self.image_pages * self.image_rate, 4)

    @property
    def total_cost(self) -> float:
        return round(self.native_cost + self.image_cost, 4)

    def to_insert_dict(self) -> dict:
        return {
            "job_id":       self.job_id,
            "api_user_id":  self.api_user_id,
            "native_pages": self.native_pages,
            "image_pages":  self.image_pages,
            "native_rate":  self.native_rate,
            "image_rate":   self.image_rate,
            "native_cost":  self.native_cost,
            "image_cost":   self.image_cost,
            "total_cost":   self.total_cost,
            "currency":     self.currency,
            "status":       self.status,
        }

    def summary(self) -> str:
        return (
            f"Pages: {self.native_pages} native @ ${self.native_rate} + "
            f"{self.image_pages} image @ ${self.image_rate} = "
            f"${self.total_cost} {self.currency}"
        )