#!/bin/bash
set -e

# Log function
log() {
    echo "$1" >> /var/log/first-boot-k3s-config.log
}
# Set KUBECONFIG
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

# Step 1: Start k3s if not running and drain the current node
if ! systemctl is-active --quiet k3s; then
    log "Starting k3s service..."
    systemctl start k3s
    # Wait for k3s to be ready
    timeout 60 bash -c "until kubectl get nodes \"$CURRENT_HOSTNAME\" >/dev/null 2>&1; do sleep 2; done" || {
        log "Warning: k3s not ready after 60 seconds, proceeding anyway"
    }
fi

# Drain the current node
log "Draining node $CURRENT_HOSTNAME..."
kubectl drain "$CURRENT_HOSTNAME" --ignore-daemonsets --delete-emptydir-data --force --timeout=60s || {
    log "Warning: Failed to drain node cleanly, proceeding with forced shutdown"
}

# Step 2: Stop k3s service
log "Stopping k3s service..."
systemctl stop k3s

# Step 3: Set new hostname
log "Setting hostname to $NEW_HOSTNAME..."
hostnamectl set-hostname "$NEW_HOSTNAME"
echo "$NEW_HOSTNAME" > /etc/hostname

# Ensure preserve_hostname is set in cloud.cfg
CLOUD_CFG="/etc/cloud/cloud.cfg"
if [ -f "$CLOUD_CFG" ]; then
    if grep -q "^preserve_hostname:" "$CLOUD_CFG"; then
        sed -i "s/^preserve_hostname:.*/preserve_hostname: true/" "$CLOUD_CFG"
    else
        echo "preserve_hostname: true" >> "$CLOUD_CFG"
    fi
else
    mkdir -p /etc/cloud
    echo "preserve_hostname: true" > "$CLOUD_CFG"
fi
chmod 0644 "$CLOUD_CFG"

# Step 4: Update k3s configuration
log "Updating k3s configuration..."
CONFIG_FILE="/etc/rancher/k3s/config.yaml"
mkdir -p /etc/rancher/k3s

# Update k3s config.yaml
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << EOF
node-name: $NEW_HOSTNAME
node-ip: $NODE_IP
node-external-ip: $NODE_IP
advertise-address: $NODE_IP
EOF
else
    # Ensure config file ends with newline before appending
    [ -s "$CONFIG_FILE" ] && [ "$(tail -c1 "$CONFIG_FILE")" != "" ] && echo "" >> "$CONFIG_FILE"

    # Update existing config - check if each field exists before updating
    if grep -q '^node-name:' "$CONFIG_FILE"; then
        sed -i "s/^node-name:.*/node-name: $NEW_HOSTNAME/" "$CONFIG_FILE"
    else
        echo "node-name: $NEW_HOSTNAME" >> "$CONFIG_FILE"
    fi
    
    if grep -q '^node-ip:' "$CONFIG_FILE"; then
        sed -i "s/^node-ip:.*/node-ip: $NODE_IP/" "$CONFIG_FILE"
    else
        echo "node-ip: $NODE_IP" >> "$CONFIG_FILE"
    fi
    
    if grep -q '^node-external-ip:' "$CONFIG_FILE"; then
        sed -i "s/^node-external-ip:.*/node-external-ip: $NODE_IP/" "$CONFIG_FILE"
    else
        echo "node-external-ip: $NODE_IP" >> "$CONFIG_FILE"
    fi
    
    if grep -q '^advertise-address:' "$CONFIG_FILE"; then
        sed -i "s/^advertise-address:.*/advertise-address: $NODE_IP/" "$CONFIG_FILE"
    else
        echo "advertise-address: $NODE_IP" >> "$CONFIG_FILE"
    fi
fi

# Update k3s service with TLS SAN
K3S_SERVICE_FILE="/etc/systemd/system/k3s.service"
if [ -f "$K3S_SERVICE_FILE" ]; then
    if grep -q '^ExecStart=.*--tls-san' "$K3S_SERVICE_FILE"; then
        sed -i "s/--tls-san [^ ]*/--tls-san $NODE_IP/" "$K3S_SERVICE_FILE"
    else
        sed -i "/^ExecStart=/ s|$| --tls-san $NODE_IP|" "$K3S_SERVICE_FILE"
    fi
    systemctl daemon-reload
fi

# Step 5: Restart k3s service
log "Restarting k3s service with new configuration..."
systemctl start k3s

# Wait for new node to be ready
log "Waiting for new node $NEW_HOSTNAME to be ready..."
timeout 120 bash -c "until kubectl get nodes \"$NEW_HOSTNAME\" >/dev/null 2>&1; do sleep 2; done" || {
    log "Error: New node not ready after 120 seconds"
    exit 1
}

# Step 6: Delete old node if it exists and is different
if [ "$CURRENT_HOSTNAME" != "$NEW_HOSTNAME" ] && kubectl get node "$CURRENT_HOSTNAME" >/dev/null 2>&1; then
    log "Deleting old node $CURRENT_HOSTNAME..."
    kubectl delete node "$CURRENT_HOSTNAME" || log "Warning: Failed to delete old node"
fi

log "k3s hostname update completed successfully: $CURRENT_HOSTNAME -> $NEW_HOSTNAME"