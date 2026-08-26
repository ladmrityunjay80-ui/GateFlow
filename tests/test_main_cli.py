from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gateflow.config import get_settings


def test_main_runs_uvicorn(monkeypatch):
    monkeypatch.setenv("GATEFLOW_GATEWAY_PORT", "8123")
    get_settings.cache_clear()

    with patch("gateflow.__main__.uvicorn.run") as mock_run:
        from gateflow.__main__ import main

        main()

    assert mock_run.called
    args, kwargs = mock_run.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8123


def test_build_ssl_context_plain(tmp_path, monkeypatch):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("cert")
    key.write_text("key")
    monkeypatch.setenv("GATEFLOW_SSL_CERTFILE", str(cert))
    monkeypatch.setenv("GATEFLOW_SSL_KEYFILE", str(key))
    get_settings.cache_clear()

    from gateflow.__main__ import _build_ssl_context

    settings = get_settings()
    ctx = _build_ssl_context(settings)
    assert ctx["ssl_certfile"] == str(cert)
    assert ctx["ssl_keyfile"] == str(key)


def test_build_ssl_context_missing_cert(monkeypatch):
    monkeypatch.setenv("GATEFLOW_SSL_CERTFILE", "/non/existent/cert.pem")
    monkeypatch.setenv("GATEFLOW_SSL_KEYFILE", "/non/existent/key.pem")
    get_settings.cache_clear()

    from gateflow.__main__ import _build_ssl_context

    with pytest.raises(FileNotFoundError):
        _build_ssl_context(get_settings())


def test_build_ssl_context_mtls(tmp_path, monkeypatch):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    ca = tmp_path / "ca.pem"
    cert.write_text("cert")
    key.write_text("key")
    ca.write_text("ca")
    monkeypatch.setenv("GATEFLOW_SSL_CERTFILE", str(cert))
    monkeypatch.setenv("GATEFLOW_SSL_KEYFILE", str(key))
    monkeypatch.setenv("GATEFLOW_SSL_CA_CERTS", str(ca))
    monkeypatch.setenv("GATEFLOW_MTLS_ENABLED", "true")
    get_settings.cache_clear()

    from gateflow.__main__ import _build_ssl_context

    settings = get_settings()
    with patch("gateflow.__main__.ssl.SSLContext") as mock_ctx:
        instance = MagicMock()
        mock_ctx.return_value = instance
        ctx = _build_ssl_context(settings)
        assert ctx["ssl"] is instance
