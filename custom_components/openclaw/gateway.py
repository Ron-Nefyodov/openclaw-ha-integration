"""OpenClaw Gateway WebSocket client."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from typing import Any
import uuid

import aiohttp

from .const import (
    GATEWAY_CLIENT_ID,
    GATEWAY_CLIENT_VERSION,
    GATEWAY_PROTOCOL_VERSION,
    LOGGER,
    RESPONSE_TIMEOUT,
)


class OpenClawError(Exception):
    """Base error for OpenClaw gateway errors."""


class OpenClawAuthError(OpenClawError):
    """Raised on authentication failure."""


class OpenClawConnectionError(OpenClawError):
    """Raised when connection to the gateway fails."""


class OpenClawTimeoutError(OpenClawError):
    """Raised when waiting for a response times out."""


class OpenClawGateway:
    """WebSocket client for the OpenClaw Gateway."""

    def __init__(
        self,
        url: str,
        token: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the gateway client."""
        self._url = url
        self._token = token
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._event_listeners: list[Callable[[dict], None]] = []
        self._listen_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Connect to the Gateway and complete the authentication handshake."""
        try:
            self._ws = await self._session.ws_connect(
                self._url,
                heartbeat=30.0,
                timeout=aiohttp.ClientTimeout(total=15),
            )
        except aiohttp.ClientError as err:
            raise OpenClawConnectionError(f"Cannot reach OpenClaw gateway: {err}") from err

        # Wait for the challenge event
        try:
            raw = await asyncio.wait_for(self._ws.receive(), timeout=10.0)
        except asyncio.TimeoutError as err:
            raise OpenClawConnectionError("Gateway did not send a challenge") from err

        if raw.type != aiohttp.WSMsgType.TEXT:
            raise OpenClawConnectionError("Unexpected message type from gateway")

        challenge = json.loads(raw.data)
        if challenge.get("event") != "connect.challenge":
            raise OpenClawConnectionError(
                f"Expected connect.challenge, got {challenge.get('event')}"
            )

        # Start the listener before the connect RPC so we can receive the response
        self._listen_task = asyncio.get_event_loop().create_task(self._listen())

        try:
            await self._call(
                "connect",
                {
                    "minProtocol": GATEWAY_PROTOCOL_VERSION,
                    "maxProtocol": GATEWAY_PROTOCOL_VERSION,
                    "client": {
                        "id": GATEWAY_CLIENT_ID,
                        "version": GATEWAY_CLIENT_VERSION,
                        "platform": "homeassistant",
                        "mode": "operator",
                    },
                    "role": "operator",
                    "scopes": ["operator.read", "operator.write"],
                    "auth": {"token": self._token},
                },
            )
        except OpenClawAuthError:
            raise
        except Exception as err:
            raise OpenClawConnectionError(f"Gateway handshake failed: {err}") from err

        # Subscribe to receive session events
        await self._call("watch.subscribe", {})
        LOGGER.debug("Connected to OpenClaw gateway at %s", self._url)

    async def ensure_session(self, session_key: str = "") -> str:
        """Return session_key as-is if provided, or create/reuse a 'homeassistant' session.

        When no session key is configured, we look for an existing session whose
        key starts with 'homeassistant' and reuse it, or create a new one.
        """
        if session_key:
            return session_key

        default_key = "homeassistant"

        try:
            result = await self._call("chats.list", {})
            chats = result.get("chats") or result.get("items") or []
            for chat in chats:
                key = chat.get("sessionKey") or chat.get("key") or ""
                if key.startswith(default_key):
                    LOGGER.debug("Reusing existing OpenClaw session: %s", key)
                    return key
        except OpenClawError:
            pass

        # No existing session found — create one
        try:
            result = await self._call(
                "sessions.create",
                {"key": default_key, "title": "Home Assistant"},
            )
            key = result.get("sessionKey") or result.get("key") or default_key
            LOGGER.debug("Created new OpenClaw session: %s", key)
            return key
        except OpenClawError:
            # Fall back to the plain key and let chat.send handle it
            LOGGER.warning(
                "Could not create session — using key '%s' directly", default_key
            )
            return default_key

    async def disconnect(self) -> None:
        """Disconnect from the gateway."""
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        # Cancel any pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send an RPC request and await the response."""
        if self._ws is None or self._ws.closed:
            raise OpenClawConnectionError("Not connected to gateway")

        req_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = future

        await self._ws.send_str(
            json.dumps({"type": "req", "id": req_id, "method": method, "params": params})
        )

        try:
            return await asyncio.wait_for(future, timeout=15.0)
        except asyncio.TimeoutError as err:
            self._pending.pop(req_id, None)
            raise OpenClawTimeoutError(f"RPC call '{method}' timed out") from err

    async def _listen(self) -> None:
        """Receive and dispatch messages from the gateway."""
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._dispatch(json.loads(msg.data))
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    LOGGER.warning("OpenClaw gateway connection closed: %s", msg)
                    break
        except asyncio.CancelledError:
            pass
        except Exception as err:
            LOGGER.error("OpenClaw gateway listener error: %s", err)

        # Cancel all waiting futures so callers don't hang
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    def _dispatch(self, frame: dict[str, Any]) -> None:
        """Route a received frame to pending RPC futures or event listeners."""
        frame_type = frame.get("type")

        if frame_type == "res":
            req_id = frame.get("id")
            future = self._pending.pop(req_id, None)
            if future and not future.done():
                if frame.get("ok"):
                    future.set_result(frame.get("payload", {}))
                else:
                    err = frame.get("error", {})
                    code = err.get("code", "")
                    msg = err.get("message", "Gateway error")
                    if code in ("AUTH_FAILED", "UNAUTHORIZED"):
                        future.set_exception(OpenClawAuthError(msg))
                    else:
                        future.set_exception(OpenClawError(f"{code}: {msg}"))

        elif frame_type == "event":
            LOGGER.debug("Gateway event: %s", frame.get("event"))
            for listener in list(self._event_listeners):
                try:
                    listener(frame)
                except Exception as err:
                    LOGGER.error("Event listener error: %s", err)

    def add_event_listener(self, listener: Callable[[dict], None]) -> Callable[[], None]:
        """Register an event listener. Returns a callable that removes it."""
        self._event_listeners.append(listener)

        def remove() -> None:
            try:
                self._event_listeners.remove(listener)
            except ValueError:
                pass

        return remove

    async def send_message(self, session_key: str, text: str) -> str:
        """Send a chat message and wait for the assistant's cumulative response.

        OpenClaw protocol v4 sends two kinds of updates:
        - `chat` events with deltaText (streaming chunks) — ignored here
        - `session.message` events with a cumulative `message` snapshot once the
          run completes — this is what we resolve on.
        """
        loop = asyncio.get_event_loop()
        response_future: asyncio.Future[str] = loop.create_future()

        def on_event(frame: dict) -> None:
            payload = frame.get("payload", {})
            if (
                frame.get("event") == "session.message"
                and payload.get("sessionKey") == session_key
                and payload.get("role") == "assistant"
                # `message` is the cumulative snapshot; fall back to `text` for
                # older gateway versions that used that field name.
                and ("message" in payload or "text" in payload)
                and not response_future.done()
            ):
                response_future.set_result(
                    payload.get("message") or payload.get("text", "")
                )

        # Register listener BEFORE sending to avoid race conditions
        remove = self.add_event_listener(on_event)

        try:
            await self._call(
                "chat.send",
                {
                    "sessionKey": session_key,
                    "text": text,
                    "queueMode": "steer",
                },
            )
            return await asyncio.wait_for(response_future, timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError as err:
            raise OpenClawTimeoutError(
                "No response from OpenClaw within the timeout period"
            ) from err
        finally:
            remove()
