from asyncio import subprocess
import json
import logging
import os
from typing import Dict

from sek8s.validators.base import ValidatorBase, ValidationResult


logger = logging.getLogger(__name__)


class CosignValidator(ValidatorBase):
    """Validator that checks container images against registry allowlist."""
    
    async def validate(self, admission_review: Dict) -> ValidationResult:
        """Validate that all container images are from allowed registries."""
        request = admission_review.get("request", {})
        
        # Only check pods and pod-creating resources
        kind = request.get("kind", {}).get("kind", "")
        if kind not in ["Pod", "Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "ReplicaSet"]:
            return ValidationResult.allow()
        
        # Extract images
        obj = request.get("object", {})
        images = self.extract_images(obj)
        
        if not images:
            return ValidationResult.allow()
        
        # Check each image
        violations = []
        for image in images:

            try:

                # If image is tag-based, resolve to digest
                if '@' not in image:
                    digest = subprocess.check_output(
                        ["docker", "inspect", "--format={{index .RepoDigests 0}}", image],
                        text=True
                    ).strip().split('@')[1]
                    image = f"{image.split(':')[0]}@{digest}"
                result = subprocess.run(
                    ["/usr/bin/cosign", "verify", "--key", self.config.cosign_public_key, image],
                    capture_output=True,
                    text=True,
                    check=True
                )
                if "Error: " in result.stdout:
                    violations.append(result.stdout)
                json.loads(result.stdout)
            except subprocess.CalledProcessError as e:
                violations.append(f"Verification failed: {e}")
            except json.JSONDecodeError:
                violations.append("Invalid cosign output.")
        
        result = ValidationResult.deny("; ".join(violations)) if violations else ValidationResult.allow()

        return result