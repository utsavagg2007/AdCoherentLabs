"""Prometheus metrics (§15.1)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "adcoherent_http_requests_total", "HTTP requests", ["method", "status"])
HTTP_DURATION = Histogram(
    "adcoherent_http_request_seconds", "Request duration", ["method"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))
RATE_LIMIT_HITS = Counter(
    "adcoherent_rate_limit_hits_total", "429s issued", ["bucket_kind"])
CREDITS_CHARGED = Counter(
    "adcoherent_credits_charged_total", "Credits charged", ["tier"])
CREDITS_REFUNDED = Counter(
    "adcoherent_credits_refunded_total", "Credits refunded (system failure)")
WEBHOOK_EVENTS = Counter(
    "adcoherent_stripe_webhook_events_total", "Stripe webhook events", ["type", "outcome"])
UPLOAD_REJECTS = Counter(
    "adcoherent_upload_rejects_total", "Upload pipeline rejections", ["reason"])

QUEUE_DEPTH = Gauge("adcoherent_queue_jobs", "Queue depth by status", ["status"])
QUEUE_OLDEST = Gauge("adcoherent_queue_oldest_queued_seconds",
                     "Age of the oldest queued job")


def set_queue_stats(stats: dict) -> None:
    for status in ("queued", "leased", "done", "dlq"):
        QUEUE_DEPTH.labels(status=status).set(stats.get(status, 0))
    QUEUE_OLDEST.set(stats.get("oldest_queued_seconds", 0))
