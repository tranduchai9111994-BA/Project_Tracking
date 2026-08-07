# -*- coding: utf-8 -*-
"""
Chuyển Postman Collection v2.1 → integration registry (không copy secret).

Credential trong Postman ({{var}}) → placeholder env prefix; user set .env sau.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from analyzer.integrations import _sanitize_integration


def _slug_env_prefix(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "").strip().upper()).strip("_")
    return (s[:40] or "POSTMAN")


def _auth_entries(auth: dict | None) -> dict[str, str]:
    if not isinstance(auth, dict):
        return {}
    t = str(auth.get("type") or "").lower()
    if not t or t == "noauth":
        return {}
    raw = auth.get(t) or auth.get("apikey") or auth.get("bearer") or auth.get("basic")
    out: dict[str, str] = {}
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and e.get("key"):
                out[str(e["key"])] = str(e.get("value") or "")
    return out


def _map_postman_auth(auth: dict | None, env_prefix: str) -> dict[str, Any]:
    prefix = _slug_env_prefix(env_prefix)
    entries = _auth_entries(auth)
    t = str((auth or {}).get("type") or "").lower()
    if t == "apikey":
        hdr = entries.get("key") or "X-API-Key"
        loc = (entries.get("in") or "header").lower()
        return {
            "method": "api_key",
            "apikey_env": prefix,
            "apikey_header": hdr[:80],
            "apikey_location": "query" if loc == "query" else "header",
            "verify_ssl": True,
        }
    if t == "bearer":
        return {
            "method": "bearer_token",
            "bearer_env": prefix,
            "verify_ssl": True,
        }
    if t == "basic":
        return {
            "method": "basic_auth",
            "credential_env": prefix,
            "verify_ssl": True,
        }
    # form_login placeholder — user điền .env hoặc chỉnh auth sau import
    return {
        "method": "form_login",
        "login_path": "/login",
        "credential_env": prefix,
        "username_field": "username",
        "password_field": "password",
        "verify_ssl": True,
    }


def _parse_postman_url(url_field: Any) -> tuple[str, dict[str, str], str]:
    """Trả (path, query_params, base_url)."""
    params: dict[str, str] = {}
    base_url = ""
    path = ""

    if isinstance(url_field, str):
        raw = url_field.strip()
        if raw.startswith("http://") or raw.startswith("https://"):
            parsed = urlparse(raw)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            path = parsed.path or "/"
            if parsed.query:
                for part in parsed.query.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        params[k] = v
        else:
            path = raw if raw.startswith("/") else f"/{raw}"
        return path, params, base_url

    if not isinstance(url_field, dict):
        return "", {}, ""

    for q in url_field.get("query") or []:
        if isinstance(q, dict) and q.get("key"):
            params[str(q["key"])] = str(q.get("value") or "")

    path_parts = url_field.get("path") or []
    if isinstance(path_parts, list):
        path = "/" + "/".join(str(p) for p in path_parts if p)
    else:
        path = str(path_parts or "")
    if path and not path.startswith("/"):
        path = "/" + path

    host_parts = url_field.get("host") or []
    protocol = str(url_field.get("protocol") or "https").lower()
    if isinstance(host_parts, list) and host_parts:
        host = ".".join(str(h) for h in host_parts)
        base_url = f"{protocol}://{host}"

    raw = str(url_field.get("raw") or "").strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        if not base_url:
            base_url = f"{parsed.scheme}://{parsed.netloc}"
        if not path and parsed.path:
            path = parsed.path
        if not params and parsed.query:
            for part in parsed.query.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params.setdefault(k, v)

    return path or "/", params, base_url


def _flatten_items(items: list | None, prefix: str = "") -> list[dict]:
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        full_name = f"{prefix}{name}".strip() if prefix else name
        if item.get("request"):
            out.append({**item, "_display_name": full_name or name or "request"})
        if item.get("item"):
            sub = f"{full_name} / " if full_name else prefix
            out.extend(_flatten_items(item.get("item"), sub))
    return out


def postman_to_integration(collection: dict, env_prefix: str | None = None) -> dict:
    """
    Chuyển 1 Postman Collection v2.1 → payload integration (chưa persist).
    """
    if not isinstance(collection, dict):
        raise ValueError("Postman collection phải là JSON object")
    info = collection.get("info") or {}
    schema = str(info.get("schema") or "")
    if schema and "v2.1" not in schema and "v2.0" not in schema:
        # Vẫn thử parse nếu có item[]
        if not collection.get("item"):
            raise ValueError("Không nhận diện Postman collection (cần v2.0/v2.1 hoặc có item[])")

    coll_name = str(info.get("name") or "Postman import").strip()
    prefix = env_prefix or _slug_env_prefix(coll_name)
    flat = _flatten_items(collection.get("item"))
    if not flat:
        raise ValueError("Postman collection không có request")

    endpoints: list[dict] = []
    bases: list[str] = []
    first_req_auth: dict | None = None

    for it in flat:
        req = it.get("request") or {}
        if not first_req_auth and req.get("auth"):
            first_req_auth = req.get("auth")
        method = str(req.get("method") or "GET").upper()
        if method not in ("GET", "POST"):
            method = "GET"
        path, params, base = _parse_postman_url(req.get("url"))
        if base:
            bases.append(base.rstrip("/"))
        ep_name = str(it.get("_display_name") or it.get("name") or path or "endpoint")[:120]

        body_json: dict | list | None = None
        body = req.get("body") or {}
        if method == "POST" and isinstance(body, dict):
            mode = str(body.get("mode") or "").lower()
            if mode == "raw":
                raw = str(body.get("raw") or "").strip()
                if raw:
                    try:
                        body_json = json.loads(raw)
                    except json.JSONDecodeError:
                        body_json = None

        ep: dict[str, Any] = {
            "name": ep_name,
            "path": path[:500],
            "http_method": method,
            "params": params,
            "response_type": "json",
            "target_action": "snapshot",
        }
        if body_json is not None:
            ep["body_json"] = body_json
        endpoints.append(ep)

    base_url = ""
    if bases:
        from collections import Counter
        base_url = Counter(bases).most_common(1)[0][0]

    if not base_url:
        raise ValueError(
            "Không suy ra base_url — mỗi request cần URL đầy đủ (https://host/...) hoặc host/path Postman"
        )

    coll_auth = collection.get("auth") or first_req_auth
    auth = _map_postman_auth(coll_auth if isinstance(coll_auth, dict) else None, prefix)

    payload = {
        "name": coll_name[:120],
        "base_url": base_url,
        "source_app": "postman",
        "visibility": "internal",
        "env": "prod",
        "docs_url": str(info.get("description") or "").strip()[:500]
        if str(info.get("description") or "").startswith("http")
        else "",
        "auth": auth,
        "endpoints": endpoints,
    }
    return _sanitize_integration(payload)


def import_postman_collection(
    project_dir: str,
    collection: dict,
    mode: str = "merge",
    env_prefix: str | None = None,
) -> dict:
    """Parse Postman + merge/replace registry."""
    from analyzer.integrations import import_registry

    integration = postman_to_integration(collection, env_prefix=env_prefix)
    if not integration.get("endpoints"):
        raise ValueError("Không tạo được endpoint từ collection")
    result = import_registry(project_dir, {"integrations": [integration]}, mode=mode)
    result["integration_name"] = integration.get("name")
    result["endpoint_count"] = len(integration.get("endpoints") or [])
    auth = integration.get("auth") or {}
    result["env_prefix"] = (
        auth.get("apikey_env") or auth.get("bearer_env") or auth.get("credential_env") or ""
    )
    return result
