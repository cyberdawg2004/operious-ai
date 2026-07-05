#!/usr/bin/env python
"""Live connector egress probe.

Exercises the generic connector transport from inside the deployed container,
proving:
  1. SSRF validator permits the configured public host
  2. IP-pinned transport resolves and connects
  3. Real HTTP GET completes and response is parsed

This bypasses the API auth layer (no JWT needed) but uses the SAME transport
substrate the real connector path uses: validate_public_https_url → PinnedIP
transport → create_isolated_http_client. It does NOT bypass governance — it
only exercises the READ transport path (no mutations, no credentials needed).

Usage (from Fly):
    fly ssh console -a operious-ai-imad -C \
        "python scripts/live_connector_probe.py --url https://httpbin.org/json"

    fly ssh console -a operious-ai-imad -C \
        "python scripts/live_connector_probe.py --url https://httpbin.org/get"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

sys.path.insert(0, "/app")


async def probe(url: str, allowed_host: str) -> dict[str, object]:
    from app.core.http import create_isolated_http_client
    from app.core.ssrf import PinnedIPAsyncHTTPTransport, validate_public_https_url

    validated = await asyncio.to_thread(
        validate_public_https_url,
        url,
        allowed_hosts=(allowed_host,),
    )
    print(f"[ssrf] validated: host={validated.hostname} ip={validated.pinned_ip}")

    transport = PinnedIPAsyncHTTPTransport(
        pinned_ip=validated.pinned_ip,
        ssl_context=None,
    )
    async with create_isolated_http_client(
        transport=transport,
        timeout_seconds=10.0,
        follow_redirects=False,
    ) as client:
        response = await client.request(
            "GET",
            validated.url,
            timeout=10.0,
            follow_redirects=False,
        )

    body_text = response.text[:2000]
    try:
        body_json = response.json()
    except Exception:
        body_json = None

    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body_preview": body_text[:500],
        "body_json": body_json,
        "ssrf_validated_host": validated.hostname,
        "ssrf_pinned_ip": validated.pinned_ip,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Live connector egress probe")
    parser.add_argument(
        "--url",
        required=True,
        help="HTTPS URL to probe (must be public, SSRF-validated)",
    )
    parser.add_argument(
        "--allowed-host",
        default=None,
        help="Override the allowed_hosts check (default: derived from URL)",
    )
    args = parser.parse_args()

    url: str = args.url
    if not url.startswith("https://"):
        print("ERROR: URL must start with https://", file=sys.stderr)
        sys.exit(1)

    from urllib.parse import urlparse

    allowed_host = args.allowed_host or urlparse(url).hostname
    if not allowed_host:
        print("ERROR: cannot derive host from URL", file=sys.stderr)
        sys.exit(1)

    print(f"[probe] url={url} allowed_host={allowed_host}")
    result = asyncio.run(probe(url, allowed_host))
    print("\n[result]")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
