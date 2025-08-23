"""
Configuration management for admission controller using Pydantic v2.
"""

from typing import List, Optional, Dict, Literal, Any
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class NamespacePolicy(BaseSettings):
    """Policy configuration for a namespace."""
    mode: Literal["enforce", "warn", "monitor"] = "enforce"
    exempt: bool = False
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


class AdmissionConfig(BaseSettings):
    """Main configuration for admission controller using Pydantic v2."""
    
    # Server configuration
    bind_address: str = Field(default="127.0.0.1", alias="ADMISSION_BIND_ADDRESS")
    port: int = Field(default=8443, alias="ADMISSION_PORT", ge=1, le=65535)
    
    # TLS configuration
    tls_cert_path: Optional[Path] = Field(default=None, alias="TLS_CERT_PATH")
    tls_key_path: Optional[Path] = Field(default=None, alias="TLS_KEY_PATH")
    
    # OPA configuration
    opa_url: str = Field(default="http://localhost:8181", alias="OPA_URL")
    opa_timeout: float = Field(default=5.0, alias="OPA_TIMEOUT", gt=0)
    
    # Policy configuration
    policy_path: Path = Field(default=Path("/etc/opa/policies"), alias="POLICY_PATH")
    
    # Registry allowlist - expects JSON array from environment
    allowed_registries: List[str] = Field(
        default=["docker.io", "gcr.io", "quay.io", "localhost:30500"],
        alias="ALLOWED_REGISTRIES",
        description="JSON array of allowed registries"
    )
    
    # Cache configuration
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_ttl: int = Field(default=300, alias="CACHE_TTL", ge=0)
    
    # Enforcement configuration
    enforcement_mode: Literal["enforce", "warn", "monitor"] = Field(
        default="enforce",
        alias="ENFORCEMENT_MODE"
    )
    
    # Namespace policies - expects JSON object from environment
    namespace_policies: Dict[str, NamespacePolicy] = Field(
        default={
            "kube-system": NamespacePolicy(mode="warn", exempt=False),
            "kube-public": NamespacePolicy(mode="warn", exempt=False),
            "kube-node-lease": NamespacePolicy(mode="warn", exempt=False),
            "gpu-operator": NamespacePolicy(mode="warn", exempt=False),
            "chutes": NamespacePolicy(mode="enforce", exempt=False),
            "default": NamespacePolicy(mode="enforce", exempt=False),
        },
        alias="NAMESPACE_POLICIES",
        description="JSON object of namespace policies"
    )
    
    # Debug mode
    debug: bool = Field(default=False, alias="DEBUG")
    
    # Metrics configuration
    metrics_enabled: bool = Field(default=True, alias="METRICS_ENABLED")
    
    # Config file support
    config_file: Optional[Path] = Field(default=None, alias="CONFIG_FILE")

    # Cosign config
    cosign_oidc_identity_regex: str = Field(default="^https://github.com/your-org/.*")
    cosign_oidc_issuer: str = Field(default="https://token.actions.githubusercontent.com")
    cosign_rekor_url: str = Field(default="https://rekor.sigstore.dev")
    cosign_public_key: str = Field(default="/root/.cosign/cosign.pub")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="",  # No prefix since we use aliases
        populate_by_name=True,  # Allow both field name and alias
        use_enum_values=True,
        validate_assignment=True,  # Validate on assignment
        extra="ignore"  # Ignore extra fields
    )
    
    @field_validator("namespace_policies", mode="before")
    @classmethod
    def parse_namespace_policies(cls, v: Any) -> Dict[str, NamespacePolicy]:
        """Parse namespace policies from dict, ensuring NamespacePolicy objects."""
        if isinstance(v, dict):
            return {
                ns: NamespacePolicy(**policy) if isinstance(policy, dict) else policy
                for ns, policy in v.items()
            }
        return v
    
    @field_validator("tls_cert_path", "tls_key_path", mode="after")
    @classmethod
    def validate_tls_paths(cls, v: Optional[Path]) -> Optional[Path]:
        """Validate that TLS paths exist if specified."""
        if v is not None and not v.exists():
            raise ValueError(f"TLS path does not exist: {v}")
        return v
    
    @field_validator("policy_path", mode="after")
    @classmethod
    def validate_policy_path(cls, v: Path) -> Path:
        """Ensure policy path exists or can be created."""
        if not v.exists():
            v.mkdir(parents=True, exist_ok=True)
        return v
    
    def __init__(self, **kwargs):
        """Initialize config with support for config file."""
        # Check if config file is specified
        config_file_path = kwargs.get("config_file") or kwargs.get("CONFIG_FILE")
        if not config_file_path:
            config_file_path = Path("/etc/admission-controller/config.json")
        
        # Load from config file if it exists
        file_config = {}
        if config_file_path and Path(config_file_path).exists():
            with open(config_file_path, 'r') as f:
                file_config = json.load(f)
        
        # Merge configurations (kwargs take precedence over file)
        merged_config = {**file_config, **kwargs}
        
        super().__init__(**merged_config)
    
    def get_namespace_policy(self, namespace: str) -> NamespacePolicy:
        """Get policy for a specific namespace."""
        if namespace in self.namespace_policies:
            return self.namespace_policies[namespace]
        return self.namespace_policies.get("default", NamespacePolicy())
    
    def is_namespace_exempt(self, namespace: str) -> bool:
        """Check if namespace is exempt from admission control."""
        policy = self.get_namespace_policy(namespace)
        return policy.exempt
    
    def export_json(self) -> str:
        """Export configuration as JSON."""
        return self.model_dump_json(indent=2, exclude_unset=False)
    
    def export_dict(self) -> dict:
        """Export configuration as dictionary."""
        return self.model_dump(exclude_unset=False)

class OPAConfig(BaseSettings):
    """Configuration specific to OPA."""
    
    opa_binary_path: Path = Field(
        default=Path("/usr/local/bin/opa"),
        alias="OPA_BINARY_PATH"
    )
    opa_log_level: Literal["debug", "info", "warn", "error"] = Field(
        default="info",
        alias="OPA_LOG_LEVEL"
    )
    opa_decision_logs: bool = Field(default=False, alias="OPA_DECISION_LOGS")
    opa_diagnostic_addr: str = Field(default="0.0.0.0:8282", alias="OPA_DIAGNOSTIC_ADDR")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="",
        populate_by_name=True
    )


class CosignConfig(BaseSettings):
    """Configuration for Cosign integration (Phase 4b)."""
    
    cosign_enabled: bool = Field(default=False, alias="COSIGN_ENABLED")
    cosign_public_key: Optional[Path] = Field(default=None, alias="COSIGN_PUBLIC_KEY")
    cosign_kms_key: Optional[str] = Field(default=None, alias="COSIGN_KMS_KEY")
    cosign_keyless: bool = Field(default=False, alias="COSIGN_KEYLESS")
    cosign_fulcio_url: str = Field(
        default="https://fulcio.sigstore.dev",
        alias="COSIGN_FULCIO_URL"
    )
    cosign_rekor_url: str = Field(
        default="https://rekor.sigstore.dev",
        alias="COSIGN_REKOR_URL"
    )
    cosign_cache_ttl: int = Field(default=3600, alias="COSIGN_CACHE_TTL", ge=0)
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="",
        populate_by_name=True
    )
    
    @field_validator("cosign_public_key", mode="after")
    @classmethod
    def validate_public_key(cls, v: Optional[Path]) -> Optional[Path]:
        """Validate that public key exists if specified."""
        if v is not None and not v.exists():
            raise ValueError(f"Cosign public key not found: {v}")
        return v


# For backward compatibility and convenience
def load_config(**kwargs) -> AdmissionConfig:
    """Load configuration with environment variables and optional overrides."""
    return AdmissionConfig(**kwargs)