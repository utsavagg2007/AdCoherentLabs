# AdCoherent backend — ONE image, three entrypoints: api / worker / scheduler (D2).
#
# Build from the REPO ROOT (the worker imports the two sibling layer repos):
#   docker compose build                      # dev  target (default)
#   docker build -t adcoherent-backend:prod --target runtime -f backend/Dockerfile .
#
# TWO TARGETS, and the difference matters:
#
#   dev      dependencies + entrypoint ONLY. Source arrives through the compose
#            bind mount (`..:/repo:ro`), so edits to engine/ or rag-engine/ take
#            effect on container restart with no rebuild. This is the fast local
#            loop and it is why the image historically carried no source.
#
#   runtime  self-contained: the source is COPYed in. Required for ANY deploy —
#            the production VM or a plain `docker run` on a co-developer's
#            machine — because none of those have the bind mount. Without this
#            target the image starts and then dies on `ModuleNotFoundError:
#            engine`, since PYTHONPATH points at an empty /repo.

# =============================================================================
# base — system libraries and Python dependencies. Shared by both targets.
# =============================================================================
FROM python:3.11-slim AS base

# libgomp1: paddle. libmagic1: MIME sniffing. libgl1/libglib2.0-0: opencv (PaddleOCR).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libmagic1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/backend

# Layer-repo deps first (large, change rarely), then backend deps.
COPY CV-RULE_ENG-NLP/requirements.txt /tmp/req-cv.txt
COPY rag-engine/requirements.txt /tmp/req-rag.txt
RUN pip install --no-cache-dir -r /tmp/req-cv.txt -r /tmp/req-rag.txt

COPY backend/requirements.txt /tmp/req-backend.txt
RUN pip install --no-cache-dir -r /tmp/req-backend.txt

ENV PYTHONPATH=/repo:/repo/backend \
    PYTHONUNBUFFERED=1

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]

# =============================================================================
# dev — the local compose target. Deliberately empty: the bind mount supplies
# /repo. Keep it as a named stage so compose never silently builds `runtime`
# and shadows the mount with stale baked-in source.
# =============================================================================
FROM base AS dev

# =============================================================================
# runtime — deployable. Everything engine/_paths.py resolves relative to
# PROJECT_ROOT must be present, or the import bootstrap raises at start:
#   "engine package expects the layer repos next to it; missing: ..."
# =============================================================================
FROM base AS runtime

# Ordered least- to most-frequently-changed so a backend edit does not
# invalidate the (much larger) layer-repo copies.
COPY CV-RULE_ENG-NLP/ /repo/CV-RULE_ENG-NLP/
COPY rag-engine/      /repo/rag-engine/
COPY engine/          /repo/engine/
COPY supabase/        /repo/supabase/
COPY backend/         /repo/backend/

# No .env is baked in — .dockerignore excludes it and the platform injects the
# environment at run time. engine/_paths.py calls load_dotenv(..., override=False)
# on a path that simply will not exist here, which is a no-op, and pydantic's
# Settings tolerates a missing env_file. Process env is the only source.

# Fail at BUILD time, not on a 3am cold start, if a COPY above was dropped or
# .dockerignore grew a pattern that ate one of the layer repos. This resolves
# modules WITHOUT importing them: `import engine` would drag in torch and
# PaddleOCR, adding minutes and gigabytes of RAM to every build to prove
# something find_spec proves for free.
RUN python -c "import sys, pathlib, importlib.util as u; \
r = pathlib.Path('/repo'); \
missing = [d for d in ('CV-RULE_ENG-NLP','rag-engine','engine','backend') if not (r/d).is_dir()]; \
assert not missing, f'missing {missing} in the image - a COPY was dropped or .dockerignore is too broad'; \
sys.path[:0] = [str(r/'rag-engine'), str(r/'CV-RULE_ENG-NLP')]; \
bad = [m for m in ('adcoherent_rag','rule_engine','cv','nlp','schema','pipeline') if not u.find_spec(m)]; \
assert not bad, f'layer modules unresolvable: {bad}'; \
print('layer repos resolved OK')"

# NOTE — still runs as root, matching the dev target exactly. Dropping to a
# non-root user is worth doing, but PaddleOCR caches models under $HOME/.paddlex
# (the compose volume mounts /root/.paddlex), so changing the user silently
# relocates that cache and re-downloads models on every cold start. Do it as its
# own change, with the OCR path actually exercised.
