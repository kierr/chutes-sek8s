"""
Integration tests for CosignValidator with real local registry and signed images.

Prerequisites:
- Registry running at localhost:5000 with test images
- OPA running at localhost:8181
- Test images already built and signed
"""

import asyncio
import json
import subprocess
import pytest
from pathlib import Path

from sek8s.config import AdmissionConfig
from sek8s.validators.cosign import CosignValidator
from sek8s.validators.base import ValidationResult


# Test configuration
REGISTRY_URL = "localhost:5000"
COSIGN_KEY_PATH = Path("tests/integration/keys/cosign.pub")
WRONG_KEY_PATH = Path("tests/integration/keys/wrong.pub") 
NONEXISTENT_KEY_PATH = Path("tests/integration/keys/nonexistent.pub")


def check_prerequisites():
    """Check that required services and test images are available."""
    # Check registry
    try:
        result = subprocess.run([
            "curl", "-f", f"http://{REGISTRY_URL}/v2/"
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pytest.skip(f"Registry not available at {REGISTRY_URL}. Run 'make integration-setup' first.")
    
    # Check OPA
    try:
        result = subprocess.run([
            "curl", "-f", "http://localhost:8181/health"
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pytest.skip("OPA not available at localhost:8181. Run 'make integration-setup' first.")
    
    # Check test images exist
    try:
        result = subprocess.run([
            "curl", "-s", f"http://{REGISTRY_URL}/v2/test-app/tags/list"
        ], check=True, capture_output=True, text=True)
        
        tags_info = json.loads(result.stdout)
        tags = tags_info.get("tags", [])
        
        expected_tags = ["signed", "unsigned", "wrongsig"]
        missing_tags = [tag for tag in expected_tags if tag not in tags]
        
        if missing_tags:
            pytest.skip(f"Missing test images: {missing_tags}. Run 'make integration-setup' first.")
            
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        pytest.skip("Test images not available. Run 'make integration-setup' first.")
    
    # Check cosign keys
    if not COSIGN_KEY_PATH.exists():
        pytest.skip(f"Cosign public key not found at {COSIGN_KEY_PATH}. Run 'make integration-setup' first.")


@pytest.fixture(scope="session", autouse=True)
def verify_test_environment():
    """Verify test environment is properly set up."""
    check_prerequisites()
    print("✓ Integration test prerequisites verified")


@pytest.fixture
def config():
    """Create test configuration."""
    return AdmissionConfig(
        cosign_public_key=str(COSIGN_KEY_PATH),
        allowed_registries=[REGISTRY_URL, "docker.io"],
        enforcement_mode="enforce"
    )


@pytest.fixture
def cosign_validator(config):
    """Create CosignValidator instance."""
    return CosignValidator(config)


def create_admission_review(image_name: str, namespace: str = "default") -> dict:
    """Create an admission review for testing."""
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": f"test-{image_name.replace(':', '-').replace('/', '-')}",
            "operation": "CREATE",
            "namespace": namespace,
            "name": "test-pod",
            "kind": {
                "kind": "Pod",
                "version": "v1",
                "group": ""
            },
            "object": {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": "test-pod",
                    "namespace": namespace
                },
                "spec": {
                    "containers": [
                        {
                            "name": "test-container",
                            "image": image_name,
                            "resources": {
                                "limits": {
                                    "memory": "256Mi",
                                    "cpu": "500m"
                                }
                            }
                        }
                    ]
                }
            }
        }
    }


@pytest.mark.asyncio
async def test_signed_image_validation_success(cosign_validator):
    """Test that properly signed images are allowed."""
    image_name = f"{REGISTRY_URL}/test-app:signed"
    admission_review = create_admission_review(image_name)
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is True, f"Expected signed image to be allowed, but got: {result.messages}"


@pytest.mark.asyncio
async def test_unsigned_image_validation_failure(cosign_validator):
    """Test that unsigned images are rejected."""
    image_name = f"{REGISTRY_URL}/test-app:unsigned"
    admission_review = create_admission_review(image_name)
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is False, "Expected unsigned image to be rejected"
    assert len(result.messages) > 0
    assert any("invalid or missing signature" in msg.lower() 
             for msg in result.messages), f"Expected verification failure message, got: {result.messages}"


@pytest.mark.asyncio 
async def test_wrong_signature_validation_failure(cosign_validator):
    """Test that images signed with wrong key are rejected."""
    image_name = f"{REGISTRY_URL}/test-app:wrongsig"
    admission_review = create_admission_review(image_name)
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is False, "Expected image with wrong signature to be rejected"
    assert len(result.messages) > 0
    assert any("invalid or missing signature" in msg.lower() 
             for msg in result.messages), f"Expected signature verification failure, got: {result.messages}"


@pytest.mark.asyncio
async def test_invalid_public_key_path(config):
    """Test handling of invalid public key path."""
    # Create config with non-existent key
    config.cosign_public_key = str(NONEXISTENT_KEY_PATH)
    validator = CosignValidator(config)
    
    image_name = f"{REGISTRY_URL}/test-app:signed"
    admission_review = create_admission_review(image_name)
    
    result = await validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is False, "Expected invalid key path to cause rejection"
    assert len(result.messages) > 0


@pytest.mark.asyncio
async def test_non_existent_image(cosign_validator):
    """Test handling of non-existent images."""
    image_name = f"{REGISTRY_URL}/non-existent:latest"
    admission_review = create_admission_review(image_name)
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is False, "Expected non-existent image to be rejected"
    assert len(result.messages) > 0


@pytest.mark.asyncio
async def test_deployment_with_signed_image(cosign_validator):
    """Test validation of deployment with signed image."""
    image_name = f"{REGISTRY_URL}/test-app:signed"
    admission_review = create_admission_review(image_name)
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is True, f"Expected deployment with signed image to be allowed, got: {result.messages}"


@pytest.mark.asyncio
async def test_mixed_containers_signed_and_unsigned(cosign_validator):
    """Test pod with both signed and unsigned containers."""
    admission_review = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview", 
        "request": {
            "uid": "test-mixed-containers",
            "operation": "CREATE",
            "namespace": "default",
            "name": "mixed-pod",
            "kind": {
                "kind": "Pod",
                "version": "v1",
                "group": ""
            },
            "object": {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": "mixed-pod",
                    "namespace": "default"
                },
                "spec": {
                    "containers": [
                        {
                            "name": "signed-container",
                            "image": f"{REGISTRY_URL}/test-app:signed",
                            "resources": {"limits": {"memory": "256Mi"}}
                        },
                        {
                            "name": "unsigned-container", 
                            "image": f"{REGISTRY_URL}/test-app:unsigned",
                            "resources": {"limits": {"memory": "256Mi"}}
                        }
                    ]
                }
            }
        }
    }
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is False, "Expected pod with unsigned container to be rejected"
    assert len(result.messages) > 0


@pytest.mark.asyncio
async def test_service_resource_skipped(cosign_validator):
    """Test that non-pod resources are skipped."""
    admission_review = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "test-service",
            "operation": "CREATE",
            "namespace": "default",
            "kind": {
                "kind": "Service",
                "version": "v1",
                "group": ""
            },
            "object": {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "test-service"},
                "spec": {
                    "selector": {"app": "test"},
                    "ports": [{"port": 80}]
                }
            }
        }
    }
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is True, "Expected Service to be allowed (skipped)"
    assert len(result.messages) == 0


@pytest.mark.asyncio
async def test_cronjob_with_unsigned_image(cosign_validator):
    """Test CronJob with unsigned image is rejected."""
    image_name = f"{REGISTRY_URL}/test-app:unsigned"
    admission_review = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "test-cronjob-unsigned",
            "operation": "CREATE", 
            "namespace": "default",
            "name": "test-cronjob",
            "kind": {
                "kind": "CronJob",
                "version": "v1",
                "group": "batch"
            },
            "object": {
                "apiVersion": "batch/v1",
                "kind": "CronJob",
                "metadata": {
                    "name": "test-cronjob",
                    "namespace": "default"
                },
                "spec": {
                    "schedule": "*/5 * * * *",
                    "jobTemplate": {
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {
                                            "name": "worker",
                                            "image": image_name,
                                            "command": ["echo", "hello"],
                                            "resources": {
                                                "limits": {
                                                    "memory": "128Mi",
                                                    "cpu": "100m"
                                                }
                                            }
                                        }
                                    ],
                                    "restartPolicy": "OnFailure"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    
    result = await cosign_validator.validate(admission_review)
    
    assert isinstance(result, ValidationResult)
    assert result.allowed is False, "Expected CronJob with unsigned image to be rejected"
    assert len(result.messages) > 0


def test_prerequisites_verification():
    """Test that all prerequisites are available (registry, OPA, test images)."""
    # Check registry
    result = subprocess.run([
        "curl", "-s", f"http://{REGISTRY_URL}/v2/_catalog"
    ], check=True, capture_output=True, text=True)
    
    catalog = json.loads(result.stdout)
    repositories = catalog.get("repositories", [])
    
    # Check that our test images are available
    assert "test-app" in repositories, f"Expected repository test-app not found in catalog: {repositories}"
    
    # Check tags for test-app
    result = subprocess.run([
        "curl", "-s", f"http://{REGISTRY_URL}/v2/test-app/tags/list"
    ], check=True, capture_output=True, text=True)
    
    tags_info = json.loads(result.stdout)
    tags = tags_info.get("tags", [])
    
    expected_tags = ["signed", "unsigned", "wrongsig"]
    for tag in expected_tags:
        assert tag in tags, f"Expected tag {tag} not found in available tags: {tags}"
    
    # Check cosign keys
    assert COSIGN_KEY_PATH.exists(), f"Cosign public key not found at {COSIGN_KEY_PATH}"
    assert WRONG_KEY_PATH.exists(), f"Wrong cosign public key not found at {WRONG_KEY_PATH}"
    
    print(f"✓ All prerequisites verified:")
    print(f"  - Registry: {REGISTRY_URL}")
    print(f"  - OPA: localhost:8181") 
    print(f"  - Test images: {tags}")
    print(f"  - Cosign keys: {COSIGN_KEY_PATH.parent}")