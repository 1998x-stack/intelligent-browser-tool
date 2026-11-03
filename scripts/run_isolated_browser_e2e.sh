#!/usr/bin/env bash
set -euo pipefail
# Test-only internal network. Neither the browser nor the fixture proxy is
# attached to an external Docker bridge.
NET=v014-browser-internal-${GITHUB_RUN_ID:-local}
PROXY=v014-proxy-${GITHUB_RUN_ID:-local}
BROWSER=v014-browser-${GITHUB_RUN_ID:-local}
cleanup() {
  docker rm -f "$BROWSER" "$PROXY" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create --internal "$NET"
docker run --pull=always -d --network "$NET" --network-alias local-proxy \
  --name "$PROXY" -p 127.0.0.1:3128:3128 \
  -v "$PWD/tests/isolated_proxy.py:/app/isolated_proxy.py:ro" \
  python:3.11-slim python /app/isolated_proxy.py

docker run --pull=always -d --network "$NET" \
  --name "$BROWSER" -p 127.0.0.1:4444:4444 --shm-size=2g \
  selenium/standalone-chrome-for-testing:4.51.0-20261010

ready=false
for i in $(seq 1 100); do
  if curl -fsS --max-time 3 http://127.0.0.1:4444/status |
      python -c 'import sys,json; sys.exit(0 if json.load(sys.stdin).get("value",{}).get("ready") else 1)' 2>/dev/null; then
    ready=true
    break
  fi
  sleep 2
done
test "$ready" = true
curl -fsS --max-time 5 http://127.0.0.1:4444/status
python tests/isolated_browser_probe.py

python - <<'PY'
import json, os, subprocess
name = "v014-browser-internal-" + os.environ.get("GITHUB_RUN_ID", "local")
output = json.loads(subprocess.check_output(["docker", "network", "inspect", name]))
assert output[0]["Internal"] is True, output[0]
containers = output[0]["Containers"]
assert len(containers) == 2, containers
print("SINGLE_INTERNAL_NETWORK_TOPOLOGY_PASS")
PY
