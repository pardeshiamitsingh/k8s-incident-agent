#!/usr/bin/env bash
# Usage: demo/heal.sh      Resets every failure toggle and waits for Ready.  (spec 011)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

run helm upgrade --install "$RELEASE" "$CHART" -n "$NAMESPACE" --create-namespace \
  --reset-values --wait --timeout 5m
echo "Healed: all failure toggles reset."
