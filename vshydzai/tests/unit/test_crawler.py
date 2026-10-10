import socket
from unittest.mock import Mock

import pytest
import telemetry
import webhealth
from validation import validate_target, validate_url


def test_success_preserves_status_and_measures_latency(monkeypatch):
    monkeypatch.setattr(webhealth, "fetch_status", lambda url, timeout: 200)
    result = webhealth.check_website("https://example.com")
    assert result["availability"] == 1
    assert result["http_status"] == 200
    assert result["latency_ms"] >= 0


def test_http_error_preserves_real_status(monkeypatch):
    monkeypatch.setattr(webhealth, "fetch_status", lambda url, timeout: 503)
    assert webhealth.check_website("https://example.com")["http_status"] == 503
    assert webhealth.check_website("https://example.com")["availability"] == 0


def test_timeout_reports_unavailable(monkeypatch):
    def fail(*args):
        raise TimeoutError()
    monkeypatch.setattr(webhealth, "fetch_status", fail)
    assert webhealth.check_website("https://example.com")["error"] == "TimeoutError"


def test_dns_error_reports_unavailable(monkeypatch):
    def fail(*args):
        raise socket.gaierror()
    monkeypatch.setattr(webhealth, "fetch_status", fail)
    assert webhealth.check_website("https://example.com")["availability"] == 0


def test_literal_private_addresses_rejected():
    for url in ("http://127.0.0.1", "http://169.254.169.254", "http://[::1]", "http://10.0.0.1"):
        with pytest.raises(ValueError):
            validate_url(url)


def test_dns_private_address_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        webhealth.resolve_public("example.com", 443)


def test_mixed_public_and_private_dns_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
        for ip in ("93.184.216.34", "192.168.1.1")])
    with pytest.raises(ValueError):
        webhealth.resolve_public("example.com", 443)


def test_connection_uses_validated_ip(monkeypatch):
    connect = Mock(return_value=Mock())
    monkeypatch.setattr(socket, "create_connection", connect)
    connection = webhealth.PinnedHTTPConnection("example.com", 80, "93.184.216.34", 3)
    connection.connect()
    connect.assert_called_once_with(("93.184.216.34", 80), 3)
    assert connection.host == "example.com"


def test_https_keeps_hostname_certificate_verification(monkeypatch):
    sock, wrapped, ctx = Mock(), Mock(), Mock()
    ctx.wrap_socket.return_value = wrapped
    monkeypatch.setattr(socket, "create_connection", lambda *a: sock)
    monkeypatch.setattr(webhealth.ssl, "create_default_context", lambda: ctx)
    connection = webhealth.PinnedHTTPSConnection("example.com", 443, "93.184.216.34", 3)
    connection.connect()
    ctx.wrap_socket.assert_called_once_with(sock, server_hostname="example.com")
    assert connection.sock is wrapped


def test_redirect_destination_is_revalidated(monkeypatch):
    reply = Mock(status=302)
    reply.getheader.return_value = "http://169.254.169.254/latest/meta-data/"
    connection = Mock()
    connection.getresponse.return_value = reply
    monkeypatch.setattr(webhealth, "resolve_public", lambda *a: "93.184.216.34")
    monkeypatch.setattr(webhealth, "PinnedHTTPSConnection", lambda *a: connection)
    with pytest.raises(ValueError):
        webhealth.fetch_status("https://example.com", 3)
    connection.close.assert_called_once()


def test_target_validation_rejects_unknown_and_wrong_types():
    with pytest.raises(ValueError):
        validate_target({"name": "x", "url": "https://example.com", "enabled": "yes"})
    with pytest.raises(ValueError):
        validate_target({"name": "x", "url": "https://example.com", "id": "override"})


def test_international_urls_normalize_for_http_transport_without_double_encoding():
    normalized = validate_url("https://bücher.example/café?q=été&keep=%2F")
    assert normalized == "https://xn--bcher-kva.example/caf%C3%A9?q=%C3%A9t%C3%A9&keep=%2F"
    assert validate_url(normalized) == normalized
    with pytest.raises(ValueError, match="2048"):
        validate_url("https://example.com/" + "é" * 1000)


def test_timed_operation_emits_measured_elapsed_time(monkeypatch):
    ticks = iter((10, 10.025))
    emit = Mock()
    monkeypatch.setattr(telemetry.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(telemetry, "emit", emit)
    assert telemetry.timed("crawler", "Read", lambda: "result") == "result"
    assert emit.call_args.args[1]["DynamoDBReadMs"] == pytest.approx(25)
