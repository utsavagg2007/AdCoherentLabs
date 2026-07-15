# AdCoherent backend — ONE image, three entrypoints: api / worker / scheduler (D2).
# Build from the REPO ROOT (the worker imports the engine repos):
#   docker compose -f backend/docker-compose.backend.yml build
# Dev containers import code from the read-only repo mount; this image carries
# dependencies + entrypoint only (spec §5 Windows dev note).

FROM python:3.11-slim

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
