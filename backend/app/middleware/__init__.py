"""ASGI middleware, applied in the §6.1 order (outermost first):
request-id + access log → security headers → body cap → CORS → auth (dependency)
→ org context (dependency) → rate limit (middleware for IP, dependency for
authenticated buckets) → route handler.
"""
