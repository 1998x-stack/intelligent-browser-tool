#!/usr/bin/env bash
set -euo pipefail
# No browser/WebDriver ports are exposed to the host. All three test
# containers share an internal-only Docker network; external egress is denied
# by topology even if Chrome ignores the proxy.
NET=v014-browser-internal-${GITHUB_RUN_ID:-local}
PROXY=v014-proxy-${GITHUB_RUN_ID:-local}
BROWSER=v014-browser-${GITHUB_RUN_ID:-local}
CLIENT_IMAGE=v014-isolated-test-client
cleanup() {
  docker rm -f "$BROWSER" "$PROXY" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Fetch dependencies at build time, BEFORE the test network exists.
docker build -q -t "$CLIENT_IMAGE" -f scripts/Dockerfile.v014-client .
docker network create --internal "$NET"

docker run --pull=always -d --network "$NET" --network-alias local-proxy \
  --name "$PROXY" -v "$PWD/tests/isolated_proxy.py:/app/isolated_proxy.py:ro" \
  python:3.11-slim python /app/isolated_proxy.py

docker run --pull=always -d --network "$NET" --network-alias isolated-browser \
  --name "$BROWSER" --shm-size=2g \
  selenium/standalone-chrome-for-testing:4.51.0-20261010

# The test controller also runs inside the internal-only network.
docker run --rm --network "$NET" \
  -e E2E_SELENIUM_URL=http://isolated-browser:4444 \
  -e E2E_PROXY_URL=http://local-proxy:3128 \
  -v "$PWD/tests:/app/tests:ro" \
  "$CLIENT_IMAGE" python tests/isolated_browser_probe.py

python - <<'PY'
import json, os, subprocess
name = "v014-browser-internal-" + os.environ.get("GITHUB_RUN_ID", "local")
output = json.loads(subprocess.check_output(["docker", "network", "inspect", name]))
assert output[0]["Internal"] is True, output[0]
containers = output[0]["Containers"]
# The short-lived test controller has already exited.
assert len(containers) == 2, containers
print("SINGLE_INTERNAL_NETWORK_TOPOLOGY_PASS")
PY
