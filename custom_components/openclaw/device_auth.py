"""Ed25519 device authentication for OpenClaw."""

from __future__ import annotations

import base64
import hashlib
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CLIENT_ID,
    CLIENT_MODE,
    CLIENT_PLATFORM,
    DEVICE_ROLE,
    DEVICE_SCOPES,
    DOMAIN,
    LOGGER,
    STORAGE_KEY_DEVICE,
    STORAGE_VERSION,
)

_STORAGE_KEY_TOKEN = f"{DOMAIN}_device_token"

# Ed25519 SPKI DER prefix (12 bytes) — matches OpenClaw JS source
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _b64url(data: bytes) -> str:
    """Base64url encode (no padding), matching the OpenClaw JS implementation."""
    return base64.b64encode(data).decode().replace("+", "-").replace("/", "_").rstrip("=")


def _normalize_device_metadata(value: str | None) -> str:
    """Lowercase + strip, or empty string. Matches normalizeDeviceMetadataForAuth."""
    if not value:
        return ""
    return value.strip().lower()


async def _get_or_create_keypair(hass: HomeAssistant) -> tuple[bytes, bytes]:
    """Load or generate an Ed25519 keypair persisted in HA private storage.

    Returns (private_key_raw_bytes, public_key_raw_bytes) — each 32 bytes.
    """
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY_DEVICE, private=True)
    data = await store.async_load()

    if data and "private_key_b64" in data and "public_key_b64" in data:
        private_key = base64.b64decode(data["private_key_b64"])
        public_key = base64.b64decode(data["public_key_b64"])
        return private_key, public_key

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat, PublicFormat,
        )

        priv_obj = Ed25519PrivateKey.generate()
        # Export raw bytes (32 bytes each)
        private_key = priv_obj.private_bytes_raw()
        pub_der = priv_obj.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        # Strip the 12-byte SPKI prefix to get the raw 32-byte key
        public_key = pub_der[len(_ED25519_SPKI_PREFIX):]
    except ImportError:
        LOGGER.warning(
            "cryptography package not available — device auth disabled. "
            "Add it to requirements or install via pip."
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


def _derive_device_id(raw_public_key: bytes) -> str:
    """SHA-256 hex of the raw Ed25519 public key bytes.

    Matches the JS: fingerprintPublicKey → SHA-256 of derivePublicKeyRaw.
    """
    return hashlib.sha256(raw_public_key).hexdigest()


def _build_v3_payload(
    device_id: str,
    signed_at_ms: int,
    signature_token: str,
    nonce: str,
    platform: str = CLIENT_PLATFORM,
    device_family: str = "",
) -> str:
    """Build the v3 pipe-separated payload string for signing.

    Format (from OpenClaw JS buildDeviceAuthPayloadV3):
      v3|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce|platform|deviceFamily
    """
    scopes_str = ",".join(sorted(DEVICE_SCOPES))
    parts = [
        "v3",
        device_id,
        CLIENT_ID,
        CLIENT_MODE,
        DEVICE_ROLE,
        scopes_str,
        str(signed_at_ms),
        signature_token or "",
        nonce,
        _normalize_device_metadata(platform),
        _normalize_device_metadata(device_family),
    ]
    return "|".join(parts)


def _sign(private_key_bytes: bytes, payload: str) -> str:
    """Sign a UTF-8 payload with Ed25519 and return a base64url signature (no padding)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    sig = priv.sign(payload.encode("utf-8"))
    return _b64url(sig)


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
    gateway_token: str = "",
) -> dict[str, Any] | None:
    """Return the device auth dict for the connect RPC.

    The gateway verifies the signature against this payload (v3 format):
      v3|deviceId|gateway-client|backend|operator|scopes|signedAtMs|token|nonce|platform|deviceFamily

    The 'token' in the payload is the signatureToken, i.e.:
      - auth.token  (gateway token)        — for initial/unpaired connections
      - auth.deviceToken (device token)    — after pairing approval

    Returns a dict with device object AND auth dict, so gateway.py can include both.
    """
    try:
        private_key, public_key = await _get_or_create_keypair(hass)
    except (ImportError, Exception) as err:
        LOGGER.warning("Cannot build device auth: %s", err)
        return None

    cp = challenge_payload or {}
    LOGGER.debug("connect.challenge payload: %s", cp)
    nonce = cp.get("nonce") or cp.get("challenge") or str(uuid.uuid4())

    import time
    signed_at_ms = int(time.time() * 1000)
    device_id = _derive_device_id(public_key)
    pub_key_b64url = _b64url(public_key)

    device_token = await _get_device_token(hass, entry_id)

    # The signature token (goes inside the signed payload AND in auth):
    #   - use device token if we have one (post-pairing)
    #   - otherwise use gateway token (initial pairing)
    signature_token = device_token if device_token else gateway_token

    payload_str = _build_v3_payload(device_id, signed_at_ms, signature_token, nonce)
    LOGGER.debug("Device auth payload: %s", payload_str)
    signature = _sign(private_key, payload_str)

    device = {
        "id": device_id,
        "publicKey": pub_key_b64url,
        "signature": signature,
        "signedAt": signed_at_ms,
        "nonce": nonce,
    }

    auth: dict[str, Any]
    if device_token:
        auth = {"deviceToken": device_token}
        LOGGER.info("Connecting with paired device token (id=%s)", device_id[:16])
    else:
        auth = {"token": gateway_token} if gateway_token else {}
        LOGGER.info(
            "OpenClaw device not yet paired (id=%s) — gateway should create "
            "a pending pairing request. Approve it then reload the integration.",
            device_id,
        )

    return {"device": device, "auth": auth}


async def get_device_id(hass: HomeAssistant) -> str | None:
    """Return the device ID (SHA-256 hex of raw public key) for display/logging."""
    try:
        _, public_key = await _get_or_create_keypair(hass)
        return _derive_device_id(public_key)
    except Exception:
        return None
