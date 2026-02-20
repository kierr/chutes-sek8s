"""VFIO device binding, virsh helpers, and udev rule installation."""

import os
import subprocess


def load_vfio_modules():
    """Load VFIO kernel modules required for PCI passthrough."""
    modules = ['vfio_pci', 'vfio_iommu_type1', 'vfio_virqfd']
    for module in modules:
        try:
            subprocess.run(['modprobe', module], check=False, capture_output=True)
        except Exception:
            pass


def bind_device_to_vfio(device_bdf: str):
    """Bind a single device to vfio-pci using driver_override method."""
    driver_override_path = f'/sys/bus/pci/devices/{device_bdf}/driver_override'
    try:
        with open(driver_override_path, 'w') as f:
            f.write('vfio-pci')
        with open('/sys/bus/pci/drivers_probe', 'w') as f:
            f.write(device_bdf)
    except Exception as e:
        print(f'  Warning: Failed to bind {device_bdf} to vfio-pci: {e}')


def bind_explicit_devices_to_vfio(devices: list[str]):
    """Bind only the given BDFs to vfio-pci (no IOMMU group binding).

    Matches setup-gpus.sh semantics: explicit device list only, no bridges
    or unrelated fabric endpoints.
    """
    load_vfio_modules()
    for device in devices:
        bind_device_to_vfio(device)
        print(f'    {device} → vfio-pci')


def virsh_bind_device(device_bdf: str):
    """Reattach then detach a PCI device via virsh (matches setup-gpus.sh behavior)."""
    virsh_bdf = device_bdf.replace(':', '_').replace('.', '_')
    print(f'  Binding {device_bdf} to vfio-pci via virsh')
    subprocess.check_call(
        ['sudo', 'virsh', 'nodedev-reattach', f'pci_{virsh_bdf}'],
        stderr=subprocess.DEVNULL,
    )
    subprocess.check_call(
        ['sudo', 'virsh', 'nodedev-detach', f'pci_{virsh_bdf}'],
        stderr=subprocess.STDOUT,
    )


def install_udev_rules(scripts_dir: str):
    """Install vfio-passthrough udev rules if not already present."""
    udev_rules_src = os.path.join(scripts_dir, 'vfio-passthrough.rules')
    udev_rules_dst = '/etc/udev/rules.d/vfio-passthrough.rules'
    if not os.path.exists(udev_rules_src):
        raise FileNotFoundError(
            f"Udev rules file not found: {udev_rules_src}. "
            "This file should be in the scripts directory."
        )
    if not os.path.exists(udev_rules_dst):
        print('  Installing udev rules...')
        subprocess.check_call(
            ['sudo', 'cp', udev_rules_src, '/etc/udev/rules.d/'],
            stderr=subprocess.STDOUT,
        )
        subprocess.check_call(
            ['sudo', 'udevadm', 'control', '--reload-rules'],
            stderr=subprocess.STDOUT,
        )
        subprocess.check_call(
            ['sudo', 'udevadm', 'trigger'],
            stderr=subprocess.STDOUT,
        )
    else:
        print('  Udev rules already present (skipping install)')
