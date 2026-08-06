FROM python:3.12-slim

WORKDIR /workspace

ENV PIP_DEFAULT_TIMEOUT=180
ENV PIP_RETRIES=10
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --timeout 180 --retries 10 -r /tmp/backend-requirements.txt

COPY . /workspace

CMD ["sh", "-c", "alembic -c backend/alembic.ini upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
