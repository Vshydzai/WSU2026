"""Target validation shared by the API and the crawler."""

import ipaddress
import re
from urllib.parse import quote, urlsplit, urlunsplit

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("Target ID must contain 1–64 letters, digits, underscores or hyphens")
    return value


def validate_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("url must be a string of at most 2048 characters")
    value = value.strip()
    if not value or any(ord(char) < 33 for char in value) or "\\" in value:
        raise ValueError("url contains invalid characters")
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise ValueError("url is malformed") from exc
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise ValueError("url must be an HTTP(S) URL without credentials")
    if parts.fragment or port not in {None, 80, 443}:
        raise ValueError("url fragments and nonstandard ports are not supported")
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private/internal targets are not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid hostname") from exc
        if not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host:
            raise ValueError("Invalid public hostname")
    else:
        if not address.is_global:
            raise ValueError("Private/internal targets are not allowed")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/?%:@!$&'()*+,;=-._~")
    normalized = urlunsplit((parts.scheme, authority, path, query, ""))
    if len(normalized) > 2048:
        raise ValueError("Normalized url exceeds 2048 characters")
    return normalized


def validate_target(payload):
    if not isinstance(payload, dict) or set(payload) - {"name", "url", "enabled"}:
        raise ValueError("Use only name, url and enabled fields")
    name = payload.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
        raise ValueError("name must contain 1–100 characters")
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    return {"name": name.strip(), "url": validate_url(payload.get("url")), "enabled": enabled}
