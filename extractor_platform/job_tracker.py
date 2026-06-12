"""
extractor_platform/job_tracker.py — CRUD operations for processing jobs
and output artefacts in the platform database.

Uses Supabase as the backend. All methods are synchronous — the FastAPI
server calls these via run_in_executor to avoid blocking the event loop.

JobTracker is instantiated once and shared across requests (same pattern
as the existing server.py thread pool).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from extractor_platform.models import ProcessingJob, OutputArtifact, BillingEvent


# Default TTL for output artefacts — 72 hours after generation
ARTIFACT_TTL_HOURS = 72


class JobTracker:

    def __init__(self, supabase_client):
        """
        supabase_client — initialised supabase.Client instance
        Typically imported from config.py alongside the anthropic client.
        """
        self.db = supabase_client

    # ─────────────────────────────────────────────
    # JOBS
    # ─────────────────────────────────────────────

    def create_job(self, job: ProcessingJob) -> str:
        """
        Insert a new processing job. Returns the generated job ID.
        Call this as soon as a request is received, before pipeline starts.
        """
        result = (
            self.db.table("processing_jobs")
            .insert(job.to_insert_dict())
            .execute()
        )
        job_id = result.data[0]["id"]
        return job_id

    def start_job(self, job_id: str):
        """Mark a job as running with a started_at timestamp."""
        self.db.table("processing_jobs").update({
            "status":     "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

    def complete_job(self, job_id: str, pipeline_result: dict):
        """
        Mark a job as complete/partial/failed and write final stats.
        pipeline_result is the dict returned by run_pipeline().
        """
        billing  = pipeline_result.get("billing", {})
        status   = pipeline_result.get("status", "failed")
        error    = pipeline_result.get("error")
        paper    = pipeline_result.get("paper", {})

        native_pages = billing.get("total_native", 0)
        image_pages  = billing.get("total_image", 0)

        self.db.table("processing_jobs").update({
            "status":              status,
            "exam_type":           pipeline_result.get("profile"),
            "total_pages":         native_pages + image_pages,
            "native_pages":        native_pages,
            "image_pages":         image_pages,
            "questions_extracted": len(pipeline_result.get("questions", [])),
            "schemes_extracted":   len(pipeline_result.get("schemes", [])),
            "error_message":       error,
            "completed_at":        datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

    def fail_job(self, job_id: str, error_message: str):
        """Mark a job as failed with an error message."""
        self.db.table("processing_jobs").update({
            "status":        "failed",
            "error_message": error_message,
            "completed_at":  datetime.now(timezone.utc).isoformat(),
        }).eq("id", job_id).execute()

    def get_job(self, job_id: str) -> Optional[dict]:
        """Fetch a single job row by ID. Returns None if not found."""
        result = (
            self.db.table("processing_jobs")
            .select("*")
            .eq("id", job_id)
            .single()
            .execute()
        )
        return result.data

    def list_jobs(self, api_user_id: str, limit: int = 50) -> list:
        """List recent jobs for an API user, newest first."""
        result = (
            self.db.table("processing_jobs")
            .select("*")
            .eq("api_user_id", api_user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    # ─────────────────────────────────────────────
    # OUTPUT ARTEFACTS
    # ─────────────────────────────────────────────

    def save_artifacts(
        self,
        job_id: str,
        artefacts: dict,
        supabase_storage,
        bucket_name: str,
    ) -> list:
        """
        Upload artefact content strings to Supabase storage and record
        each in the output_artifacts table.

        artefacts is the dict from OutputGenerator.generate_all():
            { "schema.sql": "...", "data.json": "...", "insert.py": "..." }

        Returns list of OutputArtifact records with storage paths.
        """
        saved    = []
        expires  = datetime.now(timezone.utc) + timedelta(hours=ARTIFACT_TTL_HOURS)

        for artifact_type, content in artefacts.items():
            storage_path = f"jobs/{job_id}/{artifact_type}"
            content_bytes = content.encode("utf-8")

            # Upload to Supabase storage
            supabase_storage.from_(bucket_name).upload(
                path=storage_path,
                file=content_bytes,
                file_options={"content-type": "text/plain", "upsert": "true"},
            )

            artifact = OutputArtifact(
                job_id=job_id,
                artifact_type=artifact_type,
                storage_path=storage_path,
                size_bytes=len(content_bytes),
                expires_at=expires,
            )

            self.db.table("output_artifacts").insert(
                artifact.to_insert_dict()
            ).execute()

            saved.append(artifact)

        return saved

    def get_artifacts(self, job_id: str) -> list:
        """Fetch all artefact records for a job."""
        result = (
            self.db.table("output_artifacts")
            .select("*")
            .eq("job_id", job_id)
            .execute()
        )
        return result.data or []

    def get_artifact_url(
        self,
        storage_path: str,
        supabase_storage,
        bucket_name: str,
        expires_in: int = 3600,
    ) -> str:
        """
        Generate a signed download URL for an artefact.
        expires_in — seconds until the URL expires (default 1 hour).
        """
        result = supabase_storage.from_(bucket_name).create_signed_url(
            path=storage_path,
            expires_in=expires_in,
        )
        return result["signedURL"]

    def purge_expired_artifacts(self, supabase_storage, bucket_name: str) -> int:
        """
        Delete artefacts past their expiry from both storage and the DB.
        Returns count of purged artefacts.
        Call this from a scheduled job or cron endpoint.
        """
        now = datetime.now(timezone.utc).isoformat()

        result = (
            self.db.table("output_artifacts")
            .select("id, storage_path")
            .lt("expires_at", now)
            .execute()
        )
        expired = result.data or []

        for row in expired:
            try:
                supabase_storage.from_(bucket_name).remove([row["storage_path"]])
            except Exception:
                pass
            self.db.table("output_artifacts").delete().eq("id", row["id"]).execute()

        return len(expired)