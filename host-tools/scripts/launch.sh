#!/usr/bin/env bash
# run-tdx.sh — launch Intel-TDX guest, auto-passthrough NVIDIA GPUs,
#              provide virtio-net (NAT) and virtconsole.

set -x

#BIOS=/shared/edk2/OVMF.fd
#BIOS=/shared/tdx-linux/edk2/OVMF.fd
#IMG=/shared/images/chutes-tee-tdx.qcow2
IMG=/shared/tdx/guest-tools/image/tdx-guest-ubuntu-24.04-generic.qcow2
BIOS=/usr/share/ovmf/OVMF.fd
MEM=1536G
CPU_OPTS=( -cpu host -smp cores=24,threads=2,sockets=2 )

##############################################################################
# 0. detect devices
##############################################################################
# – GPUs: class 0300/0302, vendor 10de
mapfile -t GPUS < <(
  lspci -Dn | awk '$2~/^(0300|0302):/ && $3~/^10de:/{print $1}' | sort
)

# – NVSwitch bridges: class 0680, vendor 10de, device 22a3
mapfile -t NVSW < <(
  lspci -Dn | awk '$2~/^0680:/ && $3~/^10de:22a3/{print $1}' | sort
)

##############################################################################
# 1. build dynamic -device list
##############################################################################
DEV_OPTS=(
  -netdev user,id=n0,ipv6=off,hostfwd=tcp::2022-:22
  -device virtio-net-pci,netdev=n0,mac=52:54:00:12:34:56
)

# ---------- GPUs ------------------------------------------------------------
port=16 slot=0x3 func=0
for i in "${!GPUS[@]}"; do
  id="rp$((i+1))" chassis=$((i+1))

  if ((func==0)); then
    DEV_OPTS+=(
      -device pcie-root-port,port=${port},chassis=${chassis},id=${id},\
bus=pcie.0,multifunction=on,addr=$(printf 0x%x "$slot")
    )
  else
    DEV_OPTS+=(
      -device pcie-root-port,port=${port},chassis=${chassis},id=${id},\
bus=pcie.0,addr=$(printf 0x%x.0x%x "$slot" "$func")
    )
  fi

  DEV_OPTS+=( -device vfio-pci,host=${GPUS[i]},bus=${id},addr=0x0,iommufd=iommufd0 )
  DEV_OPTS+=( -fw_cfg name=opt/ovmf/X-PciMmio64Mb$((i+1)),string=262144 )

  ((port++,func++))
  if ((func==8)); then func=0; ((slot++)); fi
done

# ---------- NVSwitch bridges -------------------------------------------------
for j in "${!NVSW[@]}"; do
  id="rp_nvsw$((j+1))" chassis=$(( ${#GPUS[@]} + j + 1 ))

  if ((func==0)); then
    DEV_OPTS+=( -device pcie-root-port,port=${port},chassis=${chassis},id=${id},bus=pcie.0,multifunction=on,addr=$(printf 0x%x.0x%x "$slot" "$func") )
  else
    DEV_OPTS+=( -device pcie-root-port,port=${port},chassis=${chassis},id=${id},bus=pcie.0,addr=$(printf 0x%x.0x%x "$slot" "$func") )
  fi
  DEV_OPTS+=( -device vfio-pci,host=${NVSW[j]},bus=${id},addr=0x0,iommufd=iommufd0 )

  ((port++,func++))
  if ((func==8)); then func=0; ((slot++)); fi
done


# ---------- launch QEMU -------------------------------------------------------
#  ,hugetlb=on,hugetlbsize=1G,share=on \
#  -global q35-pcihost.pci-hole64-size=2048G \
exec /usr/bin/qemu-system-x86_64 \
  -accel kvm \
  -object '{"qom-type":"tdx-guest","id":"tdx","quote-generation-socket":{"type": "vsock", "cid":"2","port":"4050"}}' \
  -object memory-backend-memfd,id=ram0,size=$MEM \
  -machine q35,kernel-irqchip=split,confidential-guest-support=tdx,memory-backend=ram0 \
  -m "$MEM" \
  "${CPU_OPTS[@]}" \
  -bios "$BIOS" \
  -drive file="$IMG",if=virtio \
  -vga none \
  -nodefaults \
  -nographic \
  -serial mon:stdio \
  -object iommufd,id=iommufd0 \
  -d int,guest_errors \
  -D /tmp/qemu.log \
  "${DEV_OPTS[@]}"
