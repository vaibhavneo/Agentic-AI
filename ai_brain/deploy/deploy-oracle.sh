#!/usr/bin/env bash
# Ship the AI Brain to an Oracle Cloud instance.
#
#   ./deploy/deploy-oracle.sh opc@<public-ip>
#
# Builds the image locally, streams it over SSH, and restarts the service.
# No registry, no Docker Hub account, no credentials on the box — the image
# goes straight down the SSH pipe. For an app this size that is simpler than
# operating a registry, and it means the thing that was tested is byte-for-byte
# the thing that runs.
set -euo pipefail

HOST="${1:-}"
IMAGE="ai-brain:latest"
[ -n "$HOST" ] || { echo "usage: $0 user@host   (e.g. opc@129.x.x.x)"; exit 1; }

cd "$(dirname "$0")/.."

# Oracle's Always Free shape is Ampere A1 — aarch64. Building on an Intel Mac
# without this produces an x86 image that dies on the box with "exec format
# error", which is a confusing way to find out.
PLATFORM="${PLATFORM:-linux/arm64}"

echo "==> building $IMAGE for $PLATFORM"
docker build --platform "$PLATFORM" -t "$IMAGE" .

echo "==> checking the image runs before shipping it"
docker rm -f ai-brain-preflight >/dev/null 2>&1 || true
docker run -d --name ai-brain-preflight -p 8098:8080 "$IMAGE" >/dev/null
for i in $(seq 1 20); do
  sleep 1
  if curl -fsS http://127.0.0.1:8098/api/status >/dev/null 2>&1; then break; fi
  [ "$i" = 20 ] && { echo "!! image does not serve /api/status — not shipping"; \
                     docker logs ai-brain-preflight | tail -20; \
                     docker rm -f ai-brain-preflight >/dev/null; exit 1; }
done
docker rm -f ai-brain-preflight >/dev/null
echo "    ok"

echo "==> streaming the image to $HOST (a few hundred MB, once)"
docker save "$IMAGE" | gzip | ssh "$HOST" 'gunzip | sudo docker load'

echo "==> restarting the service"
ssh "$HOST" 'sudo systemctl restart ai-brain && sleep 4 && systemctl is-active ai-brain'

echo "==> verifying over the public interface"
IP="${HOST#*@}"
if curl -fsS --max-time 15 "http://$IP/api/status" >/dev/null 2>&1; then
  echo "    reachable: http://$IP"
  echo
  echo "run the full check:"
  echo "  python3 tests/smoke_deployment.py http://$IP"
else
  cat <<'EOF'
    NOT reachable from outside. In order of likelihood:
      1. VCN security list has no ingress rule for 0.0.0.0/0 on the port
      2. the instance firewall is still closed — Oracle images REJECT early in
         the INPUT chain, so the console rule alone is not enough:
             sudo iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
      3. DEEPSEEK_API_KEY is empty in /etc/ai-brain.env (the page still serves;
         only "Ask" fails, so check /api/status before blaming the network)
EOF
  exit 1
fi
