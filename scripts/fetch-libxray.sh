#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:-v26.9.9}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/app/libs"

curl -fL --retry 3   "https://github.com/XTLS/libXray/releases/download/${VERSION}/libxray-android.zip"   -o /tmp/libxray-android.zip

AAR="$(unzip -Z1 /tmp/libxray-android.zip | grep -E '(^|/)libXray\.aar$' | head -n1)"
test -n "$AAR"
unzip -p /tmp/libxray-android.zip "$AAR" > "$ROOT/app/libs/libXray.aar"

echo "libXray installed: $ROOT/app/libs/libXray.aar"
