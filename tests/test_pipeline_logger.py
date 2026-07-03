# Copyright (c) 2025 Rubeeq. All rights reserved. See LICENSE for terms.
"""
tests/test_pipeline_logger.py — Tests for PipelineLogger concurrency fix.

Verifies that:
- Each logger instance has its own callback (no shared class state)
- Concurrent loggers don't cross-wire their streams
- Callback receives correct entry dicts
- Logger works without a callback (backwards compatible)
"""

import threading
import pytest
from engine.pipeline import PipelineLogger


class TestPipelineLogger:

    def test_no_callback_works(self):
        logger = PipelineLogger()
        logger.log("test message", "info")
        assert len(logger.logs) == 1
        assert logger.logs[0]["message"] == "test message"

    def test_callback_receives_entry(self):
        received = []
        logger = PipelineLogger(log_callback=lambda e: received.append(e))
        logger.log("hello", "success")
        assert len(received) == 1
        assert received[0]["message"] == "hello"
        assert received[0]["level"] == "success"

    def test_callback_receives_all_levels(self):
        received = []
        logger = PipelineLogger(log_callback=lambda e: received.append(e))
        for level in ["info", "success", "warning", "error"]:
            logger.log(f"msg {level}", level)
        assert len(received) == 4
        assert [r["level"] for r in received] == ["info", "success", "warning", "error"]

    def test_two_loggers_independent_callbacks(self):
        """
        Core concurrency test: two logger instances with separate callbacks
        must never deliver entries to the wrong callback.
        """
        stream_a = []
        stream_b = []

        logger_a = PipelineLogger(log_callback=lambda e: stream_a.append(e))
        logger_b = PipelineLogger(log_callback=lambda e: stream_b.append(e))

        logger_a.log("job A stage 0", "info")
        logger_b.log("job B stage 0", "info")
        logger_a.log("job A stage 1", "success")
        logger_b.log("job B stage 1", "success")

        assert len(stream_a) == 2
        assert len(stream_b) == 2
        assert all("job A" in e["message"] for e in stream_a)
        assert all("job B" in e["message"] for e in stream_b)

    def test_concurrent_loggers_dont_cross_wire(self):
        """
        Simulate two concurrent pipeline jobs logging simultaneously
        from separate threads. Entries must land in the correct stream.
        """
        stream_a = []
        stream_b = []
        errors   = []

        def run_job(logger, label, stream):
            for i in range(50):
                logger.log(f"{label} message {i}", "info")
            wrong = [e for e in stream if label not in e["message"]]
            if wrong:
                errors.append(f"{label} received {len(wrong)} wrong entries")

        logger_a = PipelineLogger(log_callback=lambda e: stream_a.append(e))
        logger_b = PipelineLogger(log_callback=lambda e: stream_b.append(e))

        t1 = threading.Thread(target=run_job, args=(logger_a, "JobA", stream_a))
        t2 = threading.Thread(target=run_job, args=(logger_b, "JobB", stream_b))
        t1.start(); t2.start()
        t1.join();  t2.join()

        assert not errors, f"Cross-wire detected: {errors}"
        assert len(stream_a) == 50
        assert len(stream_b) == 50

    def test_logs_list_always_populated(self):
        """logs list must be populated regardless of whether callback is set."""
        logger = PipelineLogger()
        logger.log("no callback", "info")
        assert len(logger.logs) == 1

        logger2 = PipelineLogger(log_callback=lambda e: None)
        logger2.log("with callback", "success")
        assert len(logger2.logs) == 1

    def test_stage_method_appends_to_logs(self):
        logger = PipelineLogger()
        logger.stage("Test Stage")
        assert any(e["level"] == "stage" for e in logger.logs)
