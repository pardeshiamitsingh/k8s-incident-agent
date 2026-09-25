#!/usr/bin/env bash
# Shared by break.sh / heal.sh. Fixed namespace and release: these scripts
# refuse to touch anything else.
NAMESPACE="ecommerce"
RELEASE="ecommerce"
CHART="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ecommerce"

# scenario -> chart value, expected class, sample query
SCENARIOS="oom-payment bad-image-catalog missing-secret-cart unschedulable-frontend bad-probe-frontend bad-db-password-orders pvc-unbound-postgres"

scenario_value() {
  case "$1" in
    oom-payment) echo oomPayment ;;
    bad-image-catalog) echo badImageCatalog ;;
    missing-secret-cart) echo missingSecretCart ;;
    unschedulable-frontend) echo unschedulableFrontend ;;
    bad-probe-frontend) echo badProbeFrontend ;;
    bad-db-password-orders) echo badDbPasswordOrders ;;
    pvc-unbound-postgres) echo pvcUnboundPostgres ;;
    *) return 1 ;;
  esac
}

scenario_info() {
  case "$1" in
    oom-payment) echo "OOMKilled|The payment service in ecommerce keeps getting killed" ;;
    bad-image-catalog) echo "ImagePullBackOff|The catalog service in ecommerce won't start" ;;
    missing-secret-cart) echo "CreateContainerConfigError|The cart service in ecommerce is stuck and never starts" ;;
    unschedulable-frontend) echo "Pending|The frontend in ecommerce is stuck pending" ;;
    bad-probe-frontend) echo "ProbeFailure|The frontend in ecommerce is running but not receiving traffic" ;;
    bad-db-password-orders) echo "CrashLoopBackOff|The orders service in ecommerce keeps crashing" ;;
    pvc-unbound-postgres) echo "Pending|The postgres database in ecommerce is stuck pending" ;;
  esac
}

list_scenarios() {
  printf '%-26s %-28s %s\n' SCENARIO "EXPECTED CLASS" "SAMPLE QUERY"
  for s in $SCENARIOS; do
    info="$(scenario_info "$s")"
    printf '%-26s %-28s %s\n' "$s" "${info%%|*}" "${info#*|}"
  done
}

run() { echo "+ $*"; "$@"; }
