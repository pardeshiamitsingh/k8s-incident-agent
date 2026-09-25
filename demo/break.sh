#!/usr/bin/env bash
# Usage: demo/break.sh <scenario> | --list      (spec 011)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ "${1:-}" == "--list" || -z "${1:-}" ]]; then
  list_scenarios
  exit 0
fi

value="$(scenario_value "$1")" || { echo "unknown scenario '$1'" >&2; list_scenarios >&2; exit 1; }

run helm upgrade --install "$RELEASE" "$CHART" -n "$NAMESPACE" --create-namespace \
  --reuse-values --set "failures.$value=true"

info="$(scenario_info "$1")"
echo
echo "Injected: $1  (expected class: ${info%%|*})"
echo "Try asking the agent: ${info#*|}"
