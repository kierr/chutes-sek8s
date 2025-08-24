#!/bin/bash
set -e

echo "Setting up test images for Cosign integration tests..."

REGISTRY_URL=${REGISTRY_URL:-"localhost:5000"}
COSIGN_PASSWORD=${COSIGN_PASSWORD:-"testpassword"}

# Wait for registry to be ready
echo "Waiting for registry at ${REGISTRY_URL} to be ready..."
timeout 60 bash -c '
    while ! curl -f http://'${REGISTRY_URL}'/v2/ >/dev/null 2>&1; do
        echo "Registry not ready, waiting..."
        sleep 2
    done
'
echo "Registry is ready!"

# Create directories
mkdir -p tests/integration/keys
mkdir -p tests/integration/test-data

# Create cosign key pair if it doesn't exist
if [ ! -f tests/integration/keys/cosign.key ] || [ ! -f tests/integration/keys/cosign.pub ]; then
    echo "Generating cosign key pair..."
    cd tests/integration/keys
    
    # Generate key pair with password
    echo "${COSIGN_PASSWORD}" | cosign generate-key-pair
    
    echo "Generated cosign key pair:"
    ls -la .
    cd ../../..
fi

# Generate a second key pair for testing wrong key scenarios
if [ ! -f tests/integration/keys/wrong.key ] || [ ! -f tests/integration/keys/wrong.pub ]; then
    echo "Generating wrong cosign key pair for testing..."
    cd tests/integration/keys
    
    # Generate second key pair
    echo "wrongpassword" | cosign generate-key-pair --output-key-prefix wrong
    
    echo "Generated wrong cosign key pair:"
    ls -la wrong*
    cd ../../..
fi

# Create simple test application Dockerfiles
cat > tests/integration/test-data/Dockerfile.signed << 'EOF'
FROM alpine:latest
RUN echo "Hello from signed image!" > /hello.txt
CMD ["cat", "/hello.txt"]
EOF

cat > tests/integration/test-data/Dockerfile.unsigned << 'EOF'
FROM alpine:latest
RUN echo "Hello from unsigned image!" > /hello.txt
CMD ["cat", "/hello.txt"]
EOF

cat > tests/integration/test-data/Dockerfile.wrongsig << 'EOF'
FROM alpine:latest
RUN echo "Hello from wrong signature image!" > /hello.txt
CMD ["cat", "/hello.txt"]
EOF

# Check if host Docker is configured for insecure registry
if ! docker info 2>/dev/null | grep -q "localhost:5000\|127.0.0.1:5000"; then
    echo "WARNING: Docker may not be configured for insecure registry localhost:5000"
    echo "If pushes fail, run: make integration-fix-docker-registry"
fi

# Build and push test images
echo "Building test images..."

# 1. Build and push signed image
echo "Building signed test image..."
docker build -f tests/integration/test-data/Dockerfile.signed -t test-app:signed tests/integration/test-data/
docker tag test-app:signed ${REGISTRY_URL}/test-app:signed

echo "Pushing signed image to registry..."
if ! docker push ${REGISTRY_URL}/test-app:signed; then
    echo "Push failed. You may need to configure Docker for insecure registry:"
    echo "Run: make integration-fix-docker-registry"
    exit 1
fi

# Sign the image with correct key
echo "Signing image with correct key..."
echo "${COSIGN_PASSWORD}" | cosign sign --key tests/integration/keys/cosign.key ${REGISTRY_URL}/test-app:signed --yes

# Verify the signature works
echo "Verifying signed image signature..."
if cosign verify --key tests/integration/keys/cosign.pub ${REGISTRY_URL}/test-app:signed; then
    echo "✓ Signature verification successful"
else
    echo "⚠ Signature verification failed"
fi

# 2. Build and push unsigned image  
echo "Building unsigned test image..."
docker build -f tests/integration/test-data/Dockerfile.unsigned -t test-app:unsigned tests/integration/test-data/
docker tag test-app:unsigned ${REGISTRY_URL}/test-app:unsigned

echo "Pushing unsigned image to registry..."
docker push ${REGISTRY_URL}/test-app:unsigned
# Note: This image is intentionally NOT signed

# 3. Build and push image signed with wrong key
echo "Building wrong signature test image..."
docker build -f tests/integration/test-data/Dockerfile.wrongsig -t test-app:wrongsig tests/integration/test-data/
docker tag test-app:wrongsig ${REGISTRY_URL}/test-app:wrongsig

echo "Pushing wrong signature image to registry..."
docker push ${REGISTRY_URL}/test-app:wrongsig

# Sign with the wrong key
echo "Signing image with wrong key..."
echo "wrongpassword" | cosign sign --key tests/integration/keys/wrong.key ${REGISTRY_URL}/test-app:wrongsig --yes

echo "Test image setup complete!"

# Verify what we created
echo "Created test images:"
echo "Registry catalog:"
curl -s http://${REGISTRY_URL}/v2/_catalog | jq '.' || curl -s http://${REGISTRY_URL}/v2/_catalog

echo "Test-app tags:"
curl -s http://${REGISTRY_URL}/v2/test-app/tags/list | jq '.' || curl -s http://${REGISTRY_URL}/v2/test-app/tags/list

echo "Local Docker images:"
docker images | grep test-app || echo "No local test-app images found"

echo "Cosign key files:"
ls -la tests/integration/keys/

echo "✅ Integration test environment setup complete!"