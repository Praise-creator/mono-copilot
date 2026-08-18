#!/usr/bin/env bash
set -euo pipefail

REPO="${MONO_COPILOT_REPO:-mosesgameli/mono-copilot}"
TAG="${MONO_COPILOT_TAG:-latest}"

usage() {
  echo "Usage: $0 --repo owner/repo [--tag vX.Y.Z|latest]"
  echo "Env alternatives:"
  echo "  MONO_COPILOT_REPO=owner/repo"
  echo "  MONO_COPILOT_TAG=vX.Y.Z|latest"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --tag)
      TAG="${2:-latest}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${REPO}" ]]; then
  echo "Error: repo is required."
  usage
  exit 1
fi

command -v curl >/dev/null 2>&1 || { echo "curl is required."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required."; exit 1; }

API_URL="https://api.github.com/repos/${REPO}/releases/latest"
if [[ "${TAG}" != "latest" ]]; then
  API_URL="https://api.github.com/repos/${REPO}/releases/tags/${TAG}"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

RELEASE_JSON="${TMP_DIR}/release.json"
curl -fsSL "${API_URL}" -o "${RELEASE_JSON}"

mapfile -t URLS < <(python3 - "${RELEASE_JSON}" <<'PY'
import json, re, sys
data = json.load(open(sys.argv[1], "r", encoding="utf-8"))
assets = data.get("assets", [])
copilot = None
runtime = None
for a in assets:
  name = a.get("name", "")
  url = a.get("browser_download_url", "")
  if re.match(r"^copilot-.*\.whl$", name):
    copilot = url
  elif re.match(r"^runtime-.*\.whl$", name):
    runtime = url
if not copilot:
  sys.exit("No copilot wheel found in release assets.")
print(copilot)
if runtime:
  print(runtime)
PY
)

COPILOT_URL="${URLS[0]}"
RUNTIME_URL="${URLS[1]:-}"

COPILOT_WHEEL="${TMP_DIR}/$(basename "${COPILOT_URL}")"
curl -fsSL "${COPILOT_URL}" -o "${COPILOT_WHEEL}"

if [[ -n "${RUNTIME_URL}" ]]; then
  RUNTIME_WHEEL="${TMP_DIR}/$(basename "${RUNTIME_URL}")"
  curl -fsSL "${RUNTIME_URL}" -o "${RUNTIME_WHEEL}"
fi

if command -v pipx >/dev/null 2>&1; then
  echo "Installing with pipx..."
  pipx install --force --pip-args "--find-links ${TMP_DIR}" "${COPILOT_WHEEL}"
else
  echo "pipx not found, falling back to python user install..."
  python3 -m pip install --user --upgrade pip
  python3 -m pip install --user --upgrade --find-links "${TMP_DIR}" "${COPILOT_WHEEL}"
fi

if command -v mono-copilot >/dev/null 2>&1; then
  mono-copilot --help >/dev/null
  echo "Installed successfully. Run: mono-copilot"
  exit 0
fi

echo "Install completed, but mono-copilot is not on PATH in this shell."
echo "If pipx was used, run: pipx ensurepath"
echo "If pip --user was used, add ~/.local/bin to PATH."
exit 1