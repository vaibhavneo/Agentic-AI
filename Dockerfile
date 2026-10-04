# Container image for hosts without Railway's buildpack — Hugging Face Spaces
# (deploy/huggingface_space.py), Render, Koyeb, Cloud Run. Same server command
# as the Procfile; Python 3.9 to match runtime.txt.
FROM python:3.9-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=7860

# Hugging Face Spaces run the container as uid 1000. The app writes its SQLite
# ledger, state store and market-data cache under /app (data/, financial_data/),
# so /app must belong to that user. Without a mounted volume those writes are
# ephemeral; LEDGER_ROLE=secondary marks this deployment's ledger as non-canonical.
RUN useradd --create-home --uid 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=user:user . .
USER user

EXPOSE 7860
CMD exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 600 --graceful-timeout 30 web.app:app
