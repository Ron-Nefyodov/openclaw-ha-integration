"""Ed25519 device authentication for OpenClaw."""

from __future__ import annotations

import base64
from typing import Any

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


def _sign_challenge(private_key_bytes: bytes, challenge: str) -> str:
    """Sign a challenge string with Ed25519 and return base64-encoded signature."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_obj = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    signature = private_obj.sign(challenge.encode())
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

    Two modes depending on whether a device token has been obtained:

    *Before pairing approval* — sends only deviceId + publicKey so the
    gateway creates a pending pairing request. No signature (the gateway
    can't verify it before the device is registered).

    *After pairing approval* — also sends the deviceToken and a signature
    of the challenge so the gateway grants operator.read/write scopes.
    """
    try:
        private_key, public_key = await _get_or_create_keypair(hass)
    except (ImportError, Exception) as err:
        LOGGER.warning("Cannot build device auth: %s", err)
        return None

    public_key_b64 = base64.b64encode(public_key).decode()
    device_id = f"{DOMAIN}-{entry_id}"

    device_token = await _get_device_token(hass, entry_id)

    if device_token:
        # Paired: include token + challenge signature to get operator scopes
        challenge = (challenge_payload or {}).get("challenge", "")
        signature = _sign_challenge(private_key, challenge) if challenge else None
        payload: dict[str, Any] = {
            "deviceId": device_id,
            "publicKey": public_key_b64,
            "token": device_token,
        }
        if signature:
            payload["signature"] = signature
        LOGGER.debug("Connecting with paired device token for %s", device_id)
        return payload

    # Not yet paired — send only identity so gateway creates pending request
    LOGGER.info(
        "OpenClaw device %s not yet paired — gateway will create a pending "
        "pairing request. Approve it and then reload the integration.",
        device_id,
    )
    return {
        "deviceId": device_id,
        "publicKey": public_key_b64,
    }


async def get_public_key_b64(hass: HomeAssistant) -> str | None:
    """Return the stored public key in base64, or None if not yet generated."""
    try:
        _, public_key = await _get_or_create_keypair(hass)
        return base64.b64encode(public_key).decode()
    except Exception:
        return None
