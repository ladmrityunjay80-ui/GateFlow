import os
import ssl
import sys
from pathlib import Path
from typing import Any

import uvicorn

if __name__ == "__main__" and __package__ is None:
    # Running the file directly (e.g. from an IDE) rather than `python -m gateflow`.
    # Put the project root on the path so the `gateflow` package is importable.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateflow.config import get_settings
from gateflow.logging_config import setup_logging


def _build_ssl_context(settings) -> dict[str, Any]:
    """Return Uvicorn-compatible SSL kwargs from settings."""
    ssl_kwargs: dict[str, Any] = {}
    if not settings.ssl_certfile or not settings.ssl_keyfile:
        return ssl_kwargs

    cert = Path(settings.ssl_certfile)
    key = Path(settings.ssl_keyfile)
    if not cert.is_file() or not key.is_file():
        raise FileNotFoundError(f"TLS cert/key not found: {cert}, {key}")

    if settings.mtls_enabled and settings.ssl_ca_certs:
        ca = Path(settings.ssl_ca_certs)
        if not ca.is_file():
            raise FileNotFoundError(f"mTLS CA file not found: {ca}")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(settings.ssl_certfile, settings.ssl_keyfile)
        ctx.load_verify_locations(settings.ssl_ca_certs)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ssl_kwargs["ssl"] = ctx
    else:
        ssl_kwargs["ssl_certfile"] = settings.ssl_certfile
        ssl_kwargs["ssl_keyfile"] = settings.ssl_keyfile

    return ssl_kwargs


def main() -> None:
    setup_logging()
    settings = get_settings()
    ssl_kwargs = _build_ssl_context(settings)

    uvicorn.run(
        "gateflow.main:app",
        host=settings.gateway_host,
        port=settings.gateway_port,
        loop="uvloop",
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
