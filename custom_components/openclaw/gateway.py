"""OpenClaw Gateway WebSocket client."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from typing import Any
import uuid

import aiohttp

from .const import (
    CLIENT_DISPLAY_NAME,
    CLIENT_ID,
    CLIENT_MODE,
    CLIENT_PLATFORM,
    CLIENT_VERSION,
    DEVICE_ROLE,
    DEVICE_SCOPES,
    HEARTBEAT_INTERVAL,
    LOGGER,
    PROTOCOL_MAX_VERSION,
    PROTOCOL_MIN_VERSION,
    RECONNECT_DELAY,
    REQUEST_TIMEOUT,
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


ConnectedCallback = Callable[[], None]
DisconnectedCallback = Callable[[], None]
EventCallback = Callable[[dict], None]


class OpenClawGateway:
    """Persistent WebSocket client for the OpenClaw Gateway.

    Maintains an auto-reconnecting connection with a heartbeat.
    """

    def __init__(
        self,
        host: str,
        port: int,
        token: str,
        session: aiohttp.ClientSession,
        ssl: bool = False,
        device_auth_builder: Any | None = None,
    ) -> None:
        """Initialize the gateway client.

        device_auth_builder: async callable(challenge_payload) -> dict | None
        Used to sign the connect challenge with an Ed25519 keypair so the
        gateway grants operator.read / operator.write scopes.
        """
        scheme = "wss" if ssl else "ws"
        self._url = f"{scheme}://{host}:{port}"
        self._token = token
        self._session = session
        self._device_auth_builder = device_auth_builder

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._event_listeners: list[EventCallback] = []
        self._on_connected: list[ConnectedCallback] = []
        self._on_disconnected: list[DisconnectedCallback] = []

        self._listen_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None

        self._connected = False
        self._should_run = False

    # ── Public state ──────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """Return True when the WS handshake is complete."""
        return self._connected

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the connection manager (non-blocking)."""
        self._should_run = True
        self._reconnect_task = asyncio.get_event_loop().create_task(
            self._connect_loop()
        )

    async def stop(self) -> None:
        """Disconnect and stop all background tasks."""
        self._should_run = False
        for task in (self._reconnect_task, self._listen_task, self._heartbeat_task):
            if task and not task.done():
                task.cancel()
        self._reconnect_task = self._listen_task = self._heartbeat_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self._connected = False
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # ── Connection loop ───────────────────────────────────────────────────────

    async def _connect_loop(self) -> None:
        while self._should_run:
            try:
                await self._connect_once()
                # _listen_task is already running (started inside _connect_once).
                # Wait for it to finish, which means the connection dropped.
                if self._listen_task:
                    await self._listen_task
            except asyncio.CancelledError:
                return
            except Exception as err:
                LOGGER.warning("OpenClaw connection error: %s", err)

            if not self._should_run:
                return

            self._connected = False
            self._notify_disconnected()

            # Cancel pending futures so callers don't hang during reconnect
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.cancel()
            self._pending.clear()

            LOGGER.info(
                "OpenClaw reconnecting in %s seconds…", RECONNECT_DELAY
            )
            await asyncio.sleep(RECONNECT_DELAY)

    async def _connect_once(self) -> None:
        """Open the WebSocket and complete the handshake."""
        try:
            self._ws = await self._session.ws_connect(
                self._url,
                timeout=aiohttp.ClientTimeout(total=15),
            )
        except (aiohttp.ClientError, OSError) as err:
            raise OpenClawConnectionError(
                f"Cannot reach OpenClaw gateway at {self._url}: {err}"
            ) from err

        # The gateway always sends a connect.challenge event first.
        # We wait up to 10 s; some older builds may skip it (legacy fallback).
        challenge_payload: dict | None = None
        try:
            raw = await asyncio.wait_for(self._ws.receive(), timeout=10.0)
            if raw.type == aiohttp.WSMsgType.TEXT:
                frame = json.loads(raw.data)
                if frame.get("event") == "connect.challenge":
                    challenge_payload = frame.get("payload", {})
                else:
                    # Not a challenge — dispatch as a normal frame and proceed
                    self._dispatch(frame)
        except asyncio.TimeoutError:
            LOGGER.debug("No connect.challenge received — proceeding without device auth")

        # Build device auth by signing the challenge (grants operator scopes)
        device_auth: dict | None = None
        if challenge_payload and self._device_auth_builder:
            try:
                device_auth = await self._device_auth_builder(challenge_payload)
                LOGGER.debug("Device auth built: %s", device_auth)
            except Exception as err:
                LOGGER.warning("Device auth build failed (no scope upgrade): %s", err)

        connect_params = self._build_connect_params(challenge_payload, device_auth)

        # Start the real listener BEFORE the connect RPC so it can dispatch the response.
        # Without this, _raw_call's future would never be resolved.
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        self._listen_task = asyncio.get_event_loop().create_task(self._listen())

        try:
            result = await self._raw_call("connect", connect_params)
            LOGGER.warning("Gateway connect response: %s", result)
        except OpenClawAuthError:
            raise
        except Exception as err:
            raise OpenClawConnectionError(f"Gateway handshake failed: {err}") from err

        self._connected = True
        self._start_heartbeat()
        self._notify_connected()
        LOGGER.info("Connected to OpenClaw gateway at %s", self._url)

    def _build_connect_params(
        self, challenge: dict | None, device_auth: dict | None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "minProtocol": PROTOCOL_MIN_VERSION,
            "maxProtocol": PROTOCOL_MAX_VERSION,
            "client": {
                "id": CLIENT_ID,
                "displayName": CLIENT_DISPLAY_NAME,
                "version": CLIENT_VERSION,
                "platform": CLIENT_PLATFORM,
                "mode": CLIENT_MODE,
            },
        }
        if device_auth:
            # Device auth takes precedence — sending both token+device causes
            # the gateway to use the token path and skip the pairing flow.
            params["device"] = device_auth
        elif self._token:
            params["auth"] = {"token": self._token}
        return params

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def _start_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = asyncio.get_event_loop().create_task(
            self._heartbeat_loop()
        )

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if self._ws and not self._ws.closed:
                    await self._ws.ping()
        except asyncio.CancelledError:
            pass
        except Exception as err:
            LOGGER.debug("Heartbeat error: %s", err)

    # ── Listener ──────────────────────────────────────────────────────────────

    async def _listen(self) -> None:
        """Receive and dispatch messages until the socket closes."""
        if self._ws is None:
            return
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._dispatch(json.loads(msg.data))
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    LOGGER.info("OpenClaw WS closed: %s", msg)
                    break
        except asyncio.CancelledError:
            pass
        except Exception as err:
            LOGGER.error("OpenClaw listener error: %s", err)

    def _dispatch(self, frame: dict[str, Any]) -> None:
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
            event_name = frame.get("event", "")
            LOGGER.debug("Gateway event: %s", event_name)
            for listener in list(self._event_listeners):
                try:
                    listener(frame)
                except Exception as err:
                    LOGGER.error("Event listener error: %s", err)

    # ── RPC ───────────────────────────────────────────────────────────────────

    async def _raw_call(
        self, method: str, params: dict[str, Any], timeout: float = REQUEST_TIMEOUT
    ) -> dict[str, Any]:
        """Send an RPC request and await the response (no reconnect guard)."""
        if self._ws is None or self._ws.closed:
            raise OpenClawConnectionError("Not connected to gateway")

        req_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        await self._ws.send_str(
            json.dumps({"type": "req", "id": req_id, "method": method, "params": params})
        )

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as err:
            self._pending.pop(req_id, None)
            raise OpenClawTimeoutError(f"RPC call '{method}' timed out") from err

    async def call(
        self, method: str, params: dict[str, Any], timeout: float = REQUEST_TIMEOUT
    ) -> dict[str, Any]:
        """Send an RPC request — raises if not connected."""
        if not self._connected:
            raise OpenClawConnectionError("Gateway is not connected")
        return await self._raw_call(method, params, timeout)

    # ── Session helpers ───────────────────────────────────────────────────────

    async def ensure_session(self, session_key: str = "") -> str:
        """Return session_key if given, else find/create the 'homeassistant' session."""
        if session_key:
            return session_key

        default_key = "homeassistant"

        try:
            result = await self.call("sessions.list", {})
            sessions = result.get("sessions") or result.get("items") or []
            for s in sessions:
                key = s.get("sessionKey") or s.get("key") or ""
                if key.startswith(default_key):
                    LOGGER.debug("Reusing existing OpenClaw session: %s", key)
                    return key
        except OpenClawError:
            pass

        try:
            result = await self.call(
                "sessions.create",
                {"key": default_key, "title": "Home Assistant"},
            )
            key = result.get("sessionKey") or result.get("key") or default_key
            LOGGER.debug("Created OpenClaw session: %s", key)
            return key
        except OpenClawError:
            LOGGER.warning("Could not create session, using key '%s' directly", default_key)
            return default_key

    # ── Sending messages ──────────────────────────────────────────────────────

    async def send_message(self, session_key: str, text: str) -> str:
        """Send a message to the agent and wait for the cumulative response.

        Uses the 'agent' RPC method (not 'chat.send') and waits for a
        session.message event carrying the full assistant reply.
        """
        loop = asyncio.get_event_loop()
        response_future: asyncio.Future[str] = loop.create_future()

        def on_event(frame: dict) -> None:
            payload = frame.get("payload", {})
            if (
                frame.get("event") == "session.message"
                and payload.get("sessionKey") == session_key
                and payload.get("role") == "assistant"
                and ("message" in payload or "text" in payload)
                and not response_future.done()
            ):
                response_future.set_result(
                    payload.get("message") or payload.get("text", "")
                )

        remove = self.add_event_listener(on_event)

        try:
            await self.call(
                "agent",
                {
                    "message": text,
                    "sessionKey": session_key,
                    "idempotencyKey": str(uuid.uuid4()),
                },
                timeout=RESPONSE_TIMEOUT,
            )
            return await asyncio.wait_for(response_future, timeout=RESPONSE_TIMEOUT)
        except asyncio.TimeoutError as err:
            raise OpenClawTimeoutError(
                "No response from OpenClaw within the timeout period"
            ) from err
        finally:
            remove()

    # ── Health / status ───────────────────────────────────────────────────────

    async def get_health(self) -> dict[str, Any]:
        """Return the gateway health payload."""
        return await self.call("health", {})

    async def get_status(self) -> dict[str, Any]:
        """Return the gateway status payload (uptime, clients, etc.)."""
        return await self.call("status", {})

    # ── Event registration ────────────────────────────────────────────────────

    def add_event_listener(self, listener: EventCallback) -> Callable[[], None]:
        """Register a listener. Returns a remove callable."""
        self._event_listeners.append(listener)

        def remove() -> None:
            try:
                self._event_listeners.remove(listener)
            except ValueError:
                pass

        return remove

    def add_connected_listener(self, cb: ConnectedCallback) -> Callable[[], None]:
        self._on_connected.append(cb)
        return lambda: self._on_connected.remove(cb) if cb in self._on_connected else None

    def add_disconnected_listener(self, cb: DisconnectedCallback) -> Callable[[], None]:
        self._on_disconnected.append(cb)
        return lambda: self._on_disconnected.remove(cb) if cb in self._on_disconnected else None

    def _notify_connected(self) -> None:
        for cb in list(self._on_connected):
            try:
                cb()
            except Exception as err:
                LOGGER.error("Connected callback error: %s", err)

    def _notify_disconnected(self) -> None:
        for cb in list(self._on_disconnected):
            try:
                cb()
            except Exception as err:
                LOGGER.error("Disconnected callback error: %s", err)
