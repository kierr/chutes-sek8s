#!/usr/bin/env bash
# When no Mellanox/ConnectX PCI devices are present: mask InfiniBand services,
# unload ib_umad, and remove ib_umad from /etc/modules.
# With IB devices present, services run normally. Same VM image for all topologies.

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

log "No InfiniBand PCI devices detected (lspci vendor 15b3); masking services and disabling ib_umad"

# Services that may exist when infiniband-diags/rdma-core/nvlsm are installed.
# Without IB hardware they fail or hang at boot. Stop and mask each.
for svc in openibd opensmd rdma-core rdma ibacm rdma-ndd iwpmd nvlsm; do
    if systemctl list-unit-files "${svc}.service" 2>/dev/null | grep -q "${svc}.service"; then
        log "Masking ${svc}.service"
        systemctl stop "${svc}" 2>/dev/null || true
        systemctl mask --runtime "${svc}" 2>/dev/null || true
    fi
done

# ib_umad: loading without IB hardware can cause ibacm and other services to fail
# (they expect /sys/class/infiniband_mad/abi_version). Unload and remove from /etc/modules.
if grep -q '^ib_umad$' /etc/modules 2>/dev/null; then
    log "Removing ib_umad from /etc/modules"
    sed -i '/^ib_umad$/d' /etc/modules
fi
if lsmod 2>/dev/null | grep -q '^ib_umad '; then
    log "Unloading ib_umad kernel module"
    modprobe -r ib_umad 2>/dev/null || true
fi

exit 0
