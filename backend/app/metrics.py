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
# 0012: what is escrowed at enqueue, before the run establishes its real cost.
# reserved - charged is what comes back at settle; the ratio between these two
# is how you tune app.credit_forecast. A ratio near 1.0 means the forecast is
# tight (and users are close to spurious budget stops); a ratio near 3.0 means
# credits are being frozen for no reason.
CREDITS_RESERVED = Counter(
    "adcoherent_credits_reserved_total", "Credits escrowed at enqueue", ["tier"])
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
