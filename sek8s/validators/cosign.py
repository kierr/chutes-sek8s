import asyncio
import json
import logging
from typing import Dict

from sek8s.validators.base import ValidatorBase, ValidationResult


logger = logging.getLogger(__name__)


class CosignValidator(ValidatorBase):
    """Validator that verifies container image signatures using cosign."""
    
    async def validate(self, admission_review: Dict) -> ValidationResult:
        """Validate that all container images have valid cosign signatures."""
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
                # Verify the image signature
                is_valid = await self._verify_image_signature(image)
                if not is_valid:
                    violations.append(f"Image {image} has invalid or missing signature")
                    
            except Exception as e:
                logger.error(f"Error verifying image {image}: {e}")
                violations.append(f"Verification failed for {image}: {str(e)}")
        
        if violations:
            return ValidationResult.deny("; ".join(violations))
        else:
            return ValidationResult.allow()

    async def _verify_image_signature(self, image: str) -> bool:
        """Verify image signature using cosign."""
        try:
            # Check if public key exists
            if not hasattr(self.config, 'cosign_public_key') or not self.config.cosign_public_key:
                logger.error("No cosign public key configured")
                return False
                
            # Resolve tag to digest if needed for consistent signature verification
            resolved_image = await self._resolve_image_reference(image)
            
            # Run cosign verify command
            process = await asyncio.create_subprocess_exec(
                "cosign", "verify", 
                "--key", str(self.config.cosign_public_key),
                resolved_image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Additional validation: ensure output is valid JSON
                try:
                    verification_result = json.loads(stdout.decode())
                    # Cosign verify returns a list of verification results
                    return isinstance(verification_result, list) and len(verification_result) > 0
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON output from cosign verify: {stdout.decode()}")
                    return False
            else:
                logger.debug(f"Cosign verification failed for {image}: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Exception during cosign verification: {e}")
            return False
            
    async def _resolve_image_reference(self, image: str) -> str:
        """Resolve image tag to digest if necessary."""
        # If image already has digest, return as-is
        if '@' in image:
            return image
            
        try:
            # Use docker inspect to resolve tag to digest
            process = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format={{index .RepoDigests 0}}", image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                digest_ref = stdout.decode().strip()
                if digest_ref and digest_ref != "<no value>":
                    return digest_ref
            
            # If resolution fails, return original image reference
            # This allows cosign to handle the resolution
            return image
            
        except Exception as e:
            logger.debug(f"Could not resolve image reference {image}: {e}")
            return image