# AI Brain — portable container.
#
# Build context is ai_brain/ itself, so this image is the same wherever it
# runs: Oracle Cloud, Fly, Cloud Run, Render, a laptop. Nothing in it is
# Railway-specific.
#
#   docker build -t ai-brain .
#   docker run --rm -p 8080:8080 -e DEEPSEEK_API_KEY=sk-... ai-brain
#
# Oracle's Always Free tier is Ampere A1, which is aarch64. An image built on
# an Apple Silicon Mac is already the right architecture; from an x86 machine
# add --platform linux/arm64.

FROM python:3.11-slim

# PYTHONUNBUFFERED matters more than it looks: the pipeline streams progress
# as Server-Sent Events, and a buffered stdout also hides the startup banner
# and any traceback from `docker logs` until the process dies.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, in their own layer. They change far less often than the
# code, and numpy/sympy are the slow part of the build — copying the source
# first would rebuild them on every edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create the unprivileged user the app actually runs as (entrypoint.sh,
# already brought in by COPY . . above, drops to it after fixing up
# /app/memory's ownership — see that file for why this can no longer be a
# plain `USER brain` here now that a real volume gets mounted at that path
# at container start, not just baked into the image).
RUN useradd --create-home --shell /usr/sbin/nologin brain \
    && mkdir -p /app/memory \
    && chown -R brain:brain /app \
    && chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]

# server.py binds 0.0.0.0 when PORT is set and 127.0.0.1 otherwise — inside a
# container the loopback default would be unreachable from outside, so PORT is
# set here rather than left to the host.
ENV PORT=8080
EXPOSE 8080

# Hit a keyless endpoint: /api/status needs no API key and no book indexes, so
# a red health check means the process is genuinely wrong rather than
# unconfigured. urllib avoids installing curl just for this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import urllib.request,sys; \
      sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/status',timeout=4).status==200 else 1)"

# No CMD: entrypoint.sh runs `python3 server.py` itself once it has dropped
# to the unprivileged user, so there is no argument for a CMD to supply.
