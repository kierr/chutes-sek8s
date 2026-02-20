"""PCI device discovery for GPU, NVSwitch, and InfiniBand devices.

All functions are side-effect-free: they read lspci / nvidia-gpu-tools output
and return BDF lists or model mappings without modifying system state.
"""

import re
import subprocess

from chutes_host.gpu.profiles import GPU_PROFILES
from chutes_host.gpu.tools import ensure_gpu_tools_available

_NVIDIA_VENDOR = '10de'
_MELLANOX_VENDOR = '15b3'


def _lspci_lines(vendor: str) -> list[str]:
    """Return lspci -Dnn lines matching the given PCI vendor ID.

    -D ensures BDFs are always in full domain form (0000:bb:dd.f),
    matching nvidia-gpu-tools output and sysfs/virsh expectations.
    """
    output = subprocess.check_output(["lspci", "-Dnn"], stderr=subprocess.STDOUT)
    return [line for line in output.decode().splitlines() if vendor in line]


def _match_gpu_model(lspci_line: str) -> str | None:
    """Return the GPU_PROFILES key that appears in an lspci line, or None."""
    for model_name in GPU_PROFILES:
        if model_name in lspci_line:
            return model_name
    return None


def detect_nvidia_gpus() -> list[str]:
    """Detect NVIDIA GPU BDFs via lspci (vendor 10de, known GPU_PROFILES model in description)."""
    devices = []
    for line in _lspci_lines(_NVIDIA_VENDOR):
        parts = line.strip().split()
        if not parts:
            continue
        if _match_gpu_model(line) is not None:
            devices.append(parts[0])
    return sorted(devices)


def get_gpu_bdfs() -> list[str] | None:
    """Get GPU BDFs from nvidia-gpu-tools --query-cc-mode.

    Returns None if the tool is unavailable or returns no GPUs.
    """
    try:
        cmd = ensure_gpu_tools_available()
        out = subprocess.run(
            [cmd, '--query-cc-mode'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return None
        bdf_re = re.compile(
            r'\s+\d+\s+GPU\s+([0-9a-f]{4}:[0-9a-f]{2,4}:[0-9a-f]{2}\.[0-9])',
            re.IGNORECASE,
        )
        bdfs = []
        for line in (out.stdout or '').splitlines():
            m = bdf_re.search(line)
            if m:
                bdfs.append(m.group(1))
        return sorted(bdfs) if bdfs else None
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, RuntimeError):
        return None


def detect_nvswitches() -> list[str]:
    """Detect NVSwitch BDFs via lspci (vendor 10de, description contains NVSwitch)."""
    devices = []
    for line in _lspci_lines(_NVIDIA_VENDOR):
        parts = line.strip().split()
        if not parts:
            continue
        if 'NVSwitch' in line:
            devices.append(parts[0])
    return sorted(devices)


def get_gpu_models_from_lspci(bdfs: list[str]) -> dict[str, str]:
    """Map each GPU BDF to its GPU_PROFILES key (or 'default') via lspci."""
    bdf_set = set(bdfs)
    result = {}
    for line in _lspci_lines(_NVIDIA_VENDOR):
        parts = line.strip().split()
        if not parts:
            continue
        bdf = parts[0]
        if bdf not in bdf_set:
            continue
        result[bdf] = _match_gpu_model(line) or 'default'
    return result


def detect_infiniband_devices() -> list[str]:
    """Detect Mellanox/NVIDIA InfiniBand/ConnectX BDFs via lspci (vendor 15b3)."""
    devices = []
    for line in _lspci_lines(_MELLANOX_VENDOR):
        parts = line.strip().split()
        if parts:
            devices.append(parts[0])
    return sorted(devices)
