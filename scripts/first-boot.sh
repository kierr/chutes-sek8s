#!/bin/bash
set -e

# Log function
log() {
    echo "$1" >> /var/log/first-boot.log
}

# Optional TDX attestation check (uncomment for TDX cloud deployment)
# log "Verifying TDX attestation..."
# if ! tdx-attest --verify /var/run/tdx/quote.bin; then
#     log "Attestation failed, exiting"
#     exit 1
# fi

# Set NVIDIA device permissions
log "Setting NVIDIA device permissions..."
for device in /dev/nvidia* /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools; do
    if [ -e "$device" ]; then
        chmod 0666 "$device" && log "Set permissions to 0666 for $device"
    else
        log "Device $device not found, skipping"
    fi
done

# Create NVIDIA character device symlinks
log "Creating NVIDIA character device symlinks..."
for i in /dev/nvidia[0-9]; do
    if [ -e "$i" ]; then
        N=$(basename "$i" | sed 's/nvidia//')
        MAJ=$(ls -l "$i" | awk '{print $5}' | cut -d, -f1)
        MIN=$(ls -l "$i" | awk '{print $6}')
        mkdir -p "/dev/char/$MAJ:$MIN"
        ln -sf "$i" "/dev/char/$MAJ:$MIN" && log "Created symlink /dev/char/$MAJ:$MIN -> $i"
    else
        log "No NVIDIA devices found, skipping symlink creation"
    fi
done

# Configure k3s node name and add chutes labels
log "Configuring k3s node name and adding chutes labels..."
# Set KUBECONFIG for k3s
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
# Get node name (dynamic hostname)
NODE_NAME=$(hostname)
# Set node name in k3s config.yaml
if [ ! -f /etc/rancher/k3s/config.yaml ]; then
    mkdir -p /etc/rancher/k3s
    echo "node-name: $NODE_NAME" > /etc/rancher/k3s/config.yaml
    log "Created /etc/rancher/k3s/config.yaml with node-name: $NODE_NAME"
else
    # Update or append node-name
    if grep -q '^node-name:' /etc/rancher/k3s/config.yaml; then
        sed -i "s/^node-name:.*/node-name: $NODE_NAME/" /etc/rancher/k3s/config.yaml
        log "Updated node-name to $NODE_NAME in /etc/rancher/k3s/config.yaml"
    else
        echo "node-name: $NODE_NAME" >> /etc/rancher/k3s/config.yaml
        log "Appended node-name: $NODE_NAME to /etc/rancher/k3s/config.yaml"
    fi
fi
# Restart k3s to apply node name
if systemctl is-active --quiet k3s; then
    log "Restarting k3s to apply node name..."
    systemctl restart k3s
else
    log "Starting k3s service..."
    systemctl start k3s
fi
# Get node IP (equivalent to ansible_host)
NODE_IP=$(ip -4 addr show scope global | grep inet | awk '{print $2}' | cut -d'/' -f1 | head -n 1)
if [ -z "$NODE_IP" ]; then
    log "Failed to determine node IP, falling back to localhost"
    NODE_IP="127.0.0.1"
fi
# Wait for k3s to be ready (up to 60 seconds)
timeout 60 bash -c "until kubectl get nodes \"$NODE_NAME\" >/dev/null 2>&1; do sleep 1; done" || {
    log "Error: k3s not ready or node $NODE_NAME not found"
    exit 1
}
# Apply label with overwrite to mimic strategic-merge
kubectl label node "$NODE_NAME" chutes/external-ip="$NODE_IP" --overwrite && log "Labeled node $NODE_NAME with chutes/external-ip=$NODE_IP"

log "First boot setup completed."