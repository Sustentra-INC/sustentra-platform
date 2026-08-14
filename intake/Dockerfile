# The intake API, packaged for a hosted pilot.
#
# Build from the REPOSITORY ROOT, not from intake/:
#
#     docker build -f intake/Dockerfile -t sustentra-intake .
#
# It needs two directories: intake/ for the code and config, and
# reference-data/ for the methodology libraries the app reads at runtime (the
# J2 evidence types and the emission factor library). Nothing else is copied -
# no frontend, no S1 pipeline, no local data.
#
# Serves the intake surface only, via create_intake_app. The composed app that
# also mounts S1 needs the whole S1 dependency set, which a pilot of the
# onboarding flow has no use for.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY intake/requirements-api.txt ./intake/requirements-api.txt
RUN pip install --no-cache-dir -r intake/requirements-api.txt

COPY intake/ ./intake/
COPY reference-data/ ./reference-data/

# Where answers are stored. Mount a persistent disk here or every restart
# wipes the pilot - see intake/DEPLOY.md.
ENV INTAKE_DATA_DIR=/data
RUN mkdir -p /data

# The host assigns the port; default only helps a local `docker run`.
ENV PORT=8000
EXPOSE 8000

# Single worker on purpose. Storage is append-only files, safe for one process
# and not for several writing at once (see the repositories module). More
# traffic than one worker can serve is the point at which this needs a real
# database, not more workers.
CMD ["sh", "-c", "uvicorn intake.backend.app:create_intake_app --factory --host 0.0.0.0 --port ${PORT} --workers 1"]
