#!/usr/bin/env bash
# Mask InfiniBand services when no Mellanox/ConnectX PCI devices are present.
# When infiniband-diags and nvlsm are installed but no IB hardware was passed
# through to the VM, these services would error. This script masks them at
# boot so the guest boots cleanly regardless of whether IB devices exist.

set -euo pipefail

LOG_TAG="infiniband-mask"

log() {
    local msg="$1"
    echo "[${LOG_TAG}] ${msg}"
    logger -t "${LOG_TAG}" "${msg}" >/dev/null 2>&1 || true
}

# Detect Mellanox/ConnectX devices via lspci (vendor 15b3)
have_infiniband_devices() {
    lspci -d 15b3: 2>/dev/null | grep -qi .
}

if have_infiniband_devices; then
    exit 0
fi

log "No InfiniBand PCI devices detected (lspci vendor 15b3); stopping and masking InfiniBand services"

# Services that may exist when infiniband-diags/rdma-core are installed.
# Stop and mask each; 2>/dev/null and || true prevent failure when unit is absent.
for svc in openibd opensmd rdma-core; do
    if systemctl list-unit-files "${svc}.service" 2>/dev/null | grep -q "${svc}.service"; then
        log "Masking ${svc}.service"
        systemctl stop "${svc}" 2>/dev/null || true
        systemctl mask --runtime "${svc}" 2>/dev/null || true
    fi
done

exit 0
