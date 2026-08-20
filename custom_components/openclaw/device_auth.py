"""Ed25519 device authentication for OpenClaw."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, LOGGER, STORAGE_KEY_DEVICE, STORAGE_VERSION

_STORAGE_KEY_TOKEN = f"{DOMAIN}_device_token"


async def _get_or_create_keypair(hass: HomeAssistant) -> tuple[bytes, bytes]:
    """Load or generate an Ed25519 keypair persisted in HA private storage."""
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY_DEVICE, private=True)
    data = await store.async_load()

    if data and "private_key_b64" in data and "public_key_b64" in data:
        private_key = base64.b64decode(data["private_key_b64"])
        public_key = base64.b64decode(data["public_key_b64"])
        return private_key, public_key

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_obj = Ed25519PrivateKey.generate()
        private_key = private_obj.private_bytes_raw()
        public_key = private_obj.public_key().public_bytes_raw()
    except ImportError:
        LOGGER.warning(
            "cryptography package not available — device auth disabled. "
            "Install it via pip or add it to requirements."
        )
        raise

    await store.async_save(
        {
            "private_key_b64": base64.b64encode(private_key).decode(),
            "public_key_b64": base64.b64encode(public_key).decode(),
        }
    )
    LOGGER.debug("Generated new Ed25519 device keypair for OpenClaw")
    return private_key, public_key


def _derive_device_id(public_key_bytes: bytes) -> str:
    """Derive a device ID as SHA-256 hex of the public key bytes.

    Matches the format used by the OpenClaw CLI client.
    """
    return hashlib.sha256(public_key_bytes).hexdigest()


def _sign(private_key_bytes: bytes, payload: str) -> str:
    """Sign a UTF-8 string with Ed25519 and return base64-encoded signature."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_obj = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    signature = private_obj.sign(payload.encode())
    return base64.b64encode(signature).decode()


async def _get_device_token(hass: HomeAssistant, entry_id: str) -> str | None:
    """Return the stored device token for this entry, or None."""
    store: Store = Store(hass, STORAGE_VERSION, _STORAGE_KEY_TOKEN, private=True)
    data = await store.async_load() or {}
    return data.get(entry_id)


async def save_device_token(hass: HomeAssistant, entry_id: str, token: str) -> None:
    """Persist a device token obtained after pairing approval."""
    store: Store = Store(hass, STORAGE_VERSION, _STORAGE_KEY_TOKEN, private=True)
    data = await store.async_load() or {}
    data[entry_id] = token
    await store.async_save(data)


async def build_device_auth(
    hass: HomeAssistant,
    entry_id: str,
    challenge_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the device auth dict for the connect RPC.

    Field layout required by the gateway:
        id        — SHA-256 hex of publicKey bytes
        publicKey — base64 public key
        nonce     — challenge string from connect.challenge event
        signedAt  — ISO-8601 UTC timestamp
        signature — Ed25519 signature of (nonce + signedAt)
        token     — device token (only after pairing is approved)
    """
    try:
        private_key, public_key = await _get_or_create_keypair(hass)
    except (ImportError, Exception) as err:
        LOGGER.warning("Cannot build device auth: %s", err)
        return None

    device_id = _derive_device_id(public_key)
    public_key_b64 = base64.b64encode(public_key).decode()

    nonce = (challenge_payload or {}).get("challenge") or str(uuid.uuid4())
    signed_at = int(datetime.now(timezone.utc).timestamp() * 1000)  # Unix ms

    # Sign nonce + str(signedAt)
    signature = _sign(private_key, nonce + str(signed_at))

    payload: dict[str, Any] = {
        "id": device_id,
        "publicKey": public_key_b64,
        "nonce": nonce,
        "signedAt": signed_at,
        "signature": signature,
    }

    device_token = await _get_device_token(hass, entry_id)
    if device_token:
        payload["token"] = device_token
        LOGGER.debug("Connecting with paired device token (id=%s)", device_id)
    else:
        LOGGER.info(
            "OpenClaw device not yet paired (id=%s) — gateway should create "
            "a pending pairing request. Approve it then reload the integration.",
            device_id,
        )

    return payload


async def get_device_id(hass: HomeAssistant) -> str | None:
    """Return the device ID (SHA-256 of public key) for display/logging."""
    try:
        _, public_key = await _get_or_create_keypair(hass)
        return _derive_device_id(public_key)
    except Exception:
        return None
