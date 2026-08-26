from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Locate .env in the project root so it is found no matter the working directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "GateFlow"
    debug: bool = False
    admin_key: str = "gateflow-admin-dev"
    admin_read_keys: str = ""  # comma-separated read-only admin keys
    admin_rate_limit_enabled: bool = True
    admin_rate_limit_capacity: int = 30
    admin_rate_limit_refill_rate: float = 1.0
    key_secret: str = "gateflow-key-secret-change-in-production"
    # Comma-separated list of previous key secrets, newest first, used to validate
    # older API keys after the primary secret is rotated.
    key_secret_versions: str = ""
    cors_origins: str = ""  # comma-separated; empty disables CORS

    # mTLS / TLS configuration
    mtls_enabled: bool = False
    mtls_header: str = "X-Client-Verify"
    mtls_required_value: str = "SUCCESS"
    mtls_subject_header: str = "X-Client-S-DN"
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    ssl_ca_certs: str = ""

    database_url: str = "sqlite+aiosqlite:///gateflow.db"
    redis_url: str = "redis://localhost:6379/0"

    # Sentinel / HA settings
    redis_sentinels: str = ""  # comma-separated host:port,host2:port2
    redis_service_name: str = "mymaster"
    redis_socket_connect_timeout: float = 1.0
    redis_socket_timeout: float = 10.0
    redis_health_check_interval: int = 30
    redis_retry_on_timeout: bool = True
    redis_socket_keepalive: bool = True

    # Redis AUTH / ACL
    redis_username: str = ""
    redis_password: str = ""

    # Redis TLS in-transit
    redis_ssl: bool = False
    redis_ssl_certfile: str = ""
    redis_ssl_keyfile: str = ""
    redis_ssl_ca_certs: str = ""

    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    # Comma-separated list of trusted proxy CIDRs. Empty disables proxy headers.
    forwarded_allow_ips: str = ""

    # Circuit breaker
    circuit_breaker_threshold: int = 5
    circuit_breaker_window_seconds: float = 30.0
    circuit_breaker_open_duration: float = 30.0

    # Timeouts
    downstream_timeout_seconds: float = 0.5

    # Retry/backoff before fallback. max_retries=1 means a single attempt.
    downstream_max_retries: int = 1
    downstream_retry_base_seconds: float = 0.05

    # Readiness probe options
    ready_downstream_probe: bool = True
    ready_downstream_timeout: float = 1.0
    ready_downstream_required: bool = False

    # Default tier fallback (used when a tier record is missing in Redis)
    default_tier_capacity: int = 10
    default_tier_refill_rate: float = 1.0

    # Body / payload limits
    max_request_body_bytes: int = 1 * 1024 * 1024  # 1 MiB

    # Idempotency key cache for mutating requests
    idempotency_enabled: bool = False
    idempotency_ttl: int = 3600
    idempotency_max_body_bytes: int = 100 * 1024  # 100 KiB

    # In-memory cache for hot auth keys and tiers
    cache_ttl_seconds: int = 60
    cache_max_size: int = 10000

    # ML-based anomaly detection
    ml_anomaly_enabled: bool = False
    ml_anomaly_window_size: int = 60
    ml_anomaly_threshold: float = 3.0
    # Path to a scikit-learn model saved with joblib. Empty disables model-based detection.
    ml_model_path: str = ""

    # Anomaly notifications
    notification_worker_enabled: bool = False
    notification_webhook_url: str = ""
    # Secret used to sign outbound webhooks. Use different secrets in rotation.
    webhook_signing_secret: str = ""

    # Global/multi-region rate limiting
    global_rate_limit_enabled: bool = False
    global_rate_limit_capacity: int = 10000
    global_rate_limit_refill_rate: float = 1000.0

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="GATEFLOW_")


@lru_cache
def get_settings() -> Settings:
    # Allow `GATEFLOW_` prefixed env vars as well as the Pydantic defaults.
    return Settings()
