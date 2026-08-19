# OpenClaw for Home Assistant

A Home Assistant custom component that bridges your HA voice assistant to a locally-running [OpenClaw](https://openclaw.ai) instance — turning OpenClaw into the conversation agent behind your smart home.

## How it works

```
User speaks → HA Assist → OpenClaw Gateway (WebSocket) → OpenClaw AI → response → HA
```

The integration connects to the OpenClaw Gateway WebSocket API (`chat.send` / `session.message`), routes your voice or text input to a specific OpenClaw session, and returns the response to Home Assistant.

## Requirements

- Home Assistant **2025.2** or newer
- OpenClaw running on your local network (`openclaw onboard` to get started)
- Your OpenClaw **gateway URL** (e.g. `ws://192.168.1.50:18789`)
- Your OpenClaw **session key** (visible in the Control UI)
- Your gateway **auth token** (from `openclaw config` — leave blank if auth is disabled)

---

## Installation

### Option A — HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations → ⋮ → Custom repositories**
3. Add `https://github.com/Ron-Nefyodov/openclaw-ha-integration` as an **Integration**
4. Search for **OpenClaw** and install
5. Restart Home Assistant

### Option B — Manual

1. Download this repository
2. Copy the `custom_components/openclaw/` folder into your HA config directory:
   ```
   /config/custom_components/openclaw/
   ```
3. Restart Home Assistant

---

## Setup

1. Go to **Settings → Integrations → Add integration**
2. Search for **OpenClaw**
3. Enter:
   - **Gateway URL** — `ws://<your-openclaw-ip>:18789`
   - **Auth token** — leave blank if you haven't set one
   - **Session key** — copy from the OpenClaw Control UI (`http://<ip>:18789`)
4. Click Submit

### Set as voice assistant

1. Go to **Settings → Voice Assistants**
2. Edit your assistant (or create one)
3. Set **Conversation agent** to **OpenClaw**

---

## Reconfiguring

You can update any setting without reinstalling:

| What to change | Where |
|---|---|
| Gateway URL, auth token, session key | **Integrations → OpenClaw → ⋮ → Reconfigure** |
| Session key, system prompt prefix | **Integrations → OpenClaw → ⋮ → Options** |

---

## Troubleshooting

**"Cannot connect to the OpenClaw gateway"**
- Make sure OpenClaw is running: `openclaw gateway status`
- Check the URL — use the machine's LAN IP, not `localhost`
- Check that port 18789 is not blocked by a firewall

**No response / timeout**
- Verify the session key in the OpenClaw Control UI
- Make sure the session is active and not paused
- The default timeout is 60 seconds

**"Invalid auth token"**
- Find your token with: `openclaw config get gateway.auth.token`

---

## License

MIT
