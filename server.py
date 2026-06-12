"""
server.py — FastAPI server for the Exam PDF Extraction Engine (Product A).

Endpoints:
    GET  /health                        — liveness check
    GET  /api/profiles                  — list registered exam profiles
    POST /api/upload                    — upload a PDF (namespaced to user)
    POST /api/estimate                  — estimate job cost before submitting
    POST /api/extract                   — run extraction pipeline (SSE streaming)
    GET  /api/jobs/{job_id}             — get job status and result
    GET  /api/jobs/{job_id}/artifacts   — get signed download URLs for artefacts
    GET  /api/jobs                      — list recent jobs for an API user
    GET  /api/usage                     — usage summary for an API user
    POST /api/admin/purge               — purge expired artefacts (admin only)

Auth:
    All endpoints except /health require an X-API-Key header.
    The key is looked up in the api_users table.

Storage layout:
    exam-pdfs/
        {user_id}/questions/{filename}
        {user_id}/marking_schemes/{filename}

    All paths are namespaced by user_id. The server enforces that a user
    can only submit paths that begin with their own user_id prefix.
    Supabase RLS provides a second enforcement layer at the storage level.

Streaming:
    /api/extract returns Server-Sent Events so the client can show
    live pipeline progress. Final event has level "done" and contains
    the full result payload.
"""

import asyncio
import concurrent.futures
import json
import os
from pathlib import PurePosixPath

from fastapi import FastAPI, HTTPException, Header, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import Optional

from engine.pipeline import run_pipeline
from engine.profile_registry import list_profiles
from engine.pdf_detector import detect_pdf_type
from extractor_platform.models import ProcessingJob
from extractor_platform.job_tracker import JobTracker
from extractor_platform.billing import BillingManager, InsufficientCreditsError

# ── Config ────────────────────────────────────────────────────────────────────

from decouple import config as env

SUPABASE_URL      = env("SUPABASE_URL")
SUPABASE_KEY      = env("SUPABASE_KEY")
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
PDF_BUCKET_NAME   = env("PDF_BUCKET_NAME",   default="exam-pdfs")
ARTIFACTS_BUCKET  = env("ARTIFACTS_BUCKET",  default="extraction-artifacts")
ADMIN_SECRET      = env("ADMIN_SECRET",      default="change-me")
ALLOWED_ORIGINS   = env("ALLOWED_ORIGINS",   default="http://localhost:5173").split(",")

from supabase import create_client
import anthropic as anthropic_sdk

supabase  = create_client(SUPABASE_URL, SUPABASE_KEY)
anthropic = anthropic_sdk.Anthropic(api_key=ANTHROPIC_API_KEY)

tracker = JobTracker(supabase)
billing = BillingManager(supabase)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Exam PDF Extraction Engine",
    description="Extract structured question data from any exam PDF.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)


# ── Path helpers ──────────────────────────────────────────────────────────────

def _user_path(user_id: str, folder: str, filename: str) -> str:
    """
    Build a namespaced storage path for a user's PDF.
    folder must be 'questions' or 'marking_schemes'.

    Result: {user_id}/{folder}/{filename}
    e.g.  : abc-123/questions/9EC0_01_2024.pdf
    """
    if folder not in ("questions", "marking_schemes"):
        raise ValueError(f"Invalid folder: {folder}")
    safe_filename = PurePosixPath(filename).name  # strip any path traversal
    return f"{user_id}/{folder}/{safe_filename}"


def _validate_user_path(path: str, user_id: str):
    """
    Raise 403 if path does not begin with the authenticated user's ID.
    Prevents a user from submitting another user's PDF path.
    """
    expected_prefix = f"{user_id}/"
    if not path.startswith(expected_prefix):
        raise HTTPException(
            status_code=403,
            detail="Access denied: path does not belong to your account."
        )


# ── Auth ──────────────────────────────────────────────────────────────────────

def _lookup_user(api_key: str) -> dict:
    result = (
        supabase.table("api_users")
        .select("id, email, tier, credit_balance, is_active")
        .eq("api_key", api_key)
        .single()
        .execute()
    )
    return result.data


async def get_current_user(x_api_key: str = Header(...)) -> dict:
    loop = asyncio.get_event_loop()
    try:
        user = await loop.run_in_executor(_executor, _lookup_user, x_api_key)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not user.get("is_active"):
        raise HTTPException(status_code=403, detail="Account inactive")
    return user


# ── Request / Response models ─────────────────────────────────────────────────

class EstimateRequest(BaseModel):
    questions_path: str
    scheme_path:    Optional[str] = None


class ExtractRequest(BaseModel):
    questions_path: str
    scheme_path:    Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/profiles")
def get_profiles():
    """List all registered exam profiles."""
    return {"profiles": list_profiles()}


@app.post("/api/upload")
async def upload_pdf(
    file:   UploadFile = File(...),
    folder: str        = Form(...),
    user:   dict       = Depends(get_current_user),
):
    """
    Upload a PDF to the user's namespaced folder in Supabase storage.

    folder must be 'questions' or 'marking_schemes'.

    Returns the storage path to pass to /api/estimate and /api/extract.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    if folder not in ("questions", "marking_schemes"):
        raise HTTPException(
            status_code=400,
            detail="folder must be 'questions' or 'marking_schemes'."
        )

    storage_path = _user_path(user["id"], folder, file.filename)
    contents     = await file.read()

    loop = asyncio.get_event_loop()

    def _upload():
        supabase.storage.from_(PDF_BUCKET_NAME).upload(
            path=storage_path,
            file=contents,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )

    await loop.run_in_executor(_executor, _upload)

    return {
        "storage_path": storage_path,
        "filename":     file.filename,
        "folder":       folder,
        "size_bytes":   len(contents),
    }


@app.post("/api/estimate")
async def estimate(
    req:  EstimateRequest,
    user: dict = Depends(get_current_user),
):
    """
    Estimate cost before submitting a job.
    Validates that both paths belong to the authenticated user.
    """
    _validate_user_path(req.questions_path, user["id"])
    if req.scheme_path:
        _validate_user_path(req.scheme_path, user["id"])

    loop = asyncio.get_event_loop()

    def _detect():
        # Download PDFs from storage to detect page types
        q_bytes = supabase.storage.from_(PDF_BUCKET_NAME).download(req.questions_path)
        s_bytes = (
            supabase.storage.from_(PDF_BUCKET_NAME).download(req.scheme_path)
            if req.scheme_path else None
        )
        return q_bytes, s_bytes

    q_bytes, s_bytes = await loop.run_in_executor(_executor, _detect)

    # Write to temp files for pdfplumber
    import tempfile
    def _write_and_detect(pdf_bytes, suffix):
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(pdf_bytes)
            return detect_pdf_type(f.name), f.name

    q_det, q_tmp = await loop.run_in_executor(
        _executor, lambda: _write_and_detect(q_bytes, ".pdf")
    )
    s_det, s_tmp = (
        await loop.run_in_executor(
            _executor, lambda: _write_and_detect(s_bytes, ".pdf")
        )
        if s_bytes else (None, None)
    )

    # Clean up temp files
    os.unlink(q_tmp)
    if s_tmp:
        os.unlink(s_tmp)

    def count(det):
        if not det:
            return {"native": 0, "image": 0}
        pages = det.get("pages", {})
        return {
            "native": sum(1 for t in pages.values() if t == "native"),
            "image":  sum(1 for t in pages.values() if t == "image"),
        }

    q_counts     = count(q_det)
    s_counts     = count(s_det)
    total_native = q_counts["native"] + s_counts["native"]
    total_image  = q_counts["image"]  + s_counts["image"]

    est     = billing.estimate_cost(total_native, total_image, tier=user["tier"])
    balance = billing.get_balance(user["id"])

    return {
        "questions_pdf": {**q_counts, "pdf_type": q_det["pdf_type"]},
        "scheme_pdf":    {**s_counts, "pdf_type": s_det["pdf_type"]} if s_det else None,
        "estimate":      est,
        "balance":       balance,
        "can_afford":    balance >= est["total_cost"],
    }


@app.post("/api/extract")
async def extract(
    req:  ExtractRequest,
    user: dict = Depends(get_current_user),
):
    """
    Run the full extraction pipeline. Returns Server-Sent Events.

    Both paths must belong to the authenticated user.
    PDFs are downloaded from storage to temp files, pipeline runs,
    temp files are cleaned up after.

    Event stream:
        data: {"message": "...", "level": "info|success|warning|error|stage"}
        ...
        data: {"message": "__done__", "level": "done", "job_id": "...", "result": {...}}
    """
    # Validate ownership before anything runs
    _validate_user_path(req.questions_path, user["id"])
    if req.scheme_path:
        _validate_user_path(req.scheme_path, user["id"])

    async def event_stream():
        loop      = asyncio.get_event_loop()
        log_queue = asyncio.Queue()
        tmp_files = []

        # Create job record
        job = ProcessingJob(
            api_user_id=user["id"],
            questions_pdf_path=req.questions_path,
            scheme_pdf_path=req.scheme_path,
        )
        job_id = await loop.run_in_executor(_executor, tracker.create_job, job)
        await loop.run_in_executor(_executor, tracker.start_job, job_id)

        yield {"data": json.dumps({
            "message": f"Job created: {job_id}",
            "level":   "info",
            "job_id":  job_id,
        })}

        def _download_to_tmp():
            """Download PDFs from Supabase storage to local temp files."""
            import tempfile

            q_bytes = supabase.storage.from_(PDF_BUCKET_NAME).download(
                req.questions_path
            )
            q_tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            q_tmp.write(q_bytes)
            q_tmp.close()
            tmp_files.append(q_tmp.name)

            s_tmp_path = None
            if req.scheme_path:
                s_bytes = supabase.storage.from_(PDF_BUCKET_NAME).download(
                    req.scheme_path
                )
                s_tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                s_tmp.write(s_bytes)
                s_tmp.close()
                tmp_files.append(s_tmp.name)
                s_tmp_path = s_tmp.name

            return q_tmp.name, s_tmp_path

        q_local, s_local = await loop.run_in_executor(_executor, _download_to_tmp)

        yield {"data": json.dumps({
            "message": "PDFs downloaded — starting pipeline",
            "level":   "info",
        })}

        pipeline_result = {}

        def _run():
            import engine.pipeline as ep
            original_log = ep.PipelineLogger.log

            def patched_log(self_inner, message, level="info"):
                original_log(self_inner, message, level)
                loop.call_soon_threadsafe(
                    log_queue.put_nowait,
                    {"message": message, "level": level}
                )

            ep.PipelineLogger.log = patched_log
            try:
                result = run_pipeline(
                    questions_path=q_local,
                    scheme_path=s_local,
                    anthropic_client=anthropic,
                )
                pipeline_result.update(result)
                return result
            finally:
                ep.PipelineLogger.log = original_log

        future = loop.run_in_executor(_executor, _run)

        while not future.done():
            try:
                entry = await asyncio.wait_for(log_queue.get(), timeout=0.2)
                yield {"data": json.dumps(entry)}
            except asyncio.TimeoutError:
                continue

        while not log_queue.empty():
            entry = log_queue.get_nowait()
            yield {"data": json.dumps(entry)}

        result = await future

        # Clean up temp files
        for tmp in tmp_files:
            try:
                os.unlink(tmp)
            except Exception:
                pass

        # Save artefacts, record billing, deduct credits
        try:
            await loop.run_in_executor(
                _executor, lambda: tracker.complete_job(job_id, result)
            )

            if result.get("artefacts"):
                await loop.run_in_executor(
                    _executor,
                    lambda: tracker.save_artifacts(
                        job_id=job_id,
                        artefacts=result["artefacts"],
                        supabase_storage=supabase.storage,
                        bucket_name=ARTIFACTS_BUCKET,
                    )
                )

            billing_event = await loop.run_in_executor(
                _executor,
                lambda: billing.record_billing_event(
                    job_id=job_id,
                    api_user_id=user["id"],
                    pipeline_billing=result.get("billing", {}),
                    tier=user["tier"],
                )
            )

            await loop.run_in_executor(
                _executor,
                lambda: billing.deduct_credits(user["id"], billing_event.total_cost)
            )

        except InsufficientCreditsError as e:
            yield {"data": json.dumps({"message": str(e), "level": "error"})}
        except Exception as e:
            yield {"data": json.dumps({
                "message": f"Post-pipeline error: {e}",
                "level":   "error",
            })}

        yield {"data": json.dumps({
            "message": "__done__",
            "level":   "done",
            "job_id":  job_id,
            "result":  {
                "status":  result.get("status"),
                "profile": result.get("profile"),
                "paper":   result.get("paper"),
                "summary": {
                    "questions": len(result.get("questions", [])),
                    "schemes":   len(result.get("schemes",   [])),
                },
                "billing": result.get("billing"),
            }
        })}

    return EventSourceResponse(event_stream())


@app.get("/api/jobs/{job_id}")
async def get_job(
    job_id: str,
    user:   dict = Depends(get_current_user),
):
    loop = asyncio.get_event_loop()
    job  = await loop.run_in_executor(_executor, tracker.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("api_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    return job


@app.get("/api/jobs/{job_id}/artifacts")
async def get_job_artifacts(
    job_id: str,
    user:   dict = Depends(get_current_user),
):
    loop = asyncio.get_event_loop()
    job  = await loop.run_in_executor(_executor, tracker.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("api_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    artifacts = await loop.run_in_executor(_executor, tracker.get_artifacts, job_id)

    urls = []
    for artifact in artifacts:
        url = await loop.run_in_executor(
            _executor,
            lambda a=artifact: tracker.get_artifact_url(
                storage_path=a["storage_path"],
                supabase_storage=supabase.storage,
                bucket_name=ARTIFACTS_BUCKET,
            )
        )
        urls.append({
            "type":       artifact["artifact_type"],
            "url":        url,
            "size_bytes": artifact.get("size_bytes"),
            "expires_at": artifact.get("expires_at"),
        })

    return {"job_id": job_id, "artifacts": urls}


@app.get("/api/jobs")
async def list_jobs(
    user:  dict = Depends(get_current_user),
    limit: int  = 50,
):
    loop = asyncio.get_event_loop()
    jobs = await loop.run_in_executor(
        _executor,
        lambda: tracker.list_jobs(user["id"], limit=limit)
    )
    return {"jobs": jobs}


@app.get("/api/usage")
async def get_usage(user: dict = Depends(get_current_user)):
    loop    = asyncio.get_event_loop()
    summary = await loop.run_in_executor(
        _executor, lambda: billing.get_usage_summary(user["id"])
    )
    balance = await loop.run_in_executor(
        _executor, lambda: billing.get_balance(user["id"])
    )
    return {**summary, "credit_balance": balance, "tier": user["tier"]}


@app.post("/api/admin/purge")
async def purge_artifacts(x_admin_secret: str = Header(...)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
    loop   = asyncio.get_event_loop()
    purged = await loop.run_in_executor(
        _executor,
        lambda: tracker.purge_expired_artifacts(
            supabase_storage=supabase.storage,
            bucket_name=ARTIFACTS_BUCKET,
        )
    )
    return {"purged": purged}