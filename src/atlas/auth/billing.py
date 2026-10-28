"""Stripe Checkout for a one-time pass. No subscription and no card on the trial."""

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError

# Live one-time prices on the Sole trader account. Checkout uses these instead of ad-hoc amounts.
PRICE_IDS = {
    "30": "price_1UVZYz17sTkAsp8vkCgGHapo",
    "90": "price_1UVZZ017sTkAsp8vIrnhg1Is",
    "365": "price_1UVZZ117sTkAsp8vgQzNAVhh",
}


def create_checkout(
    *,
    secret_key: str,
    user_id: str,
    email: str,
    plan: str,
    success_url: str,
    cancel_url: str,
) -> str:
    if plan not in PRICE_IDS:
        raise KeyError(plan)
    form = {
        "mode": "payment",
        "customer_email": email,
        "client_reference_id": user_id,
        "metadata[plan]": plan,
        "metadata[user_id]": user_id,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "line_items[0][quantity]": "1",
        "line_items[0][price]": PRICE_IDS[plan],
    }
    request = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=urllib.parse.urlencode(form).encode(),
        headers={"Authorization": f"Bearer {secret_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(detail or "Stripe rejected the checkout") from exc
    url = payload.get("url")
    if not isinstance(url, str) or not url:
        raise RuntimeError("Stripe did not return a checkout URL")
    return url


def signed_event(secret: str, payload: bytes, header: str, now: int | None = None) -> dict:
    moment = int(time.time()) if now is None else now
    parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
    timestamp = parts.get("t", "")
    signature = parts.get("v1", "")
    if not timestamp.isdigit() or not signature:
        raise ValueError("Bad signature")
    if abs(moment - int(timestamp)) > 300:
        raise ValueError("Stale signature")
    expected = hmac.new(
        secret.encode(),
        f"{timestamp}.".encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Bad signature")
    event = json.loads(payload)
    if not isinstance(event, dict):
        raise ValueError("Bad event")
    return event
