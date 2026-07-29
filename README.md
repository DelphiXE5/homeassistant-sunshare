# Sunshare Inverter — Reverse-Engineered Cloud API

Reverse-engineered documentation and tooling for the Sunshare/Sunsharetek cloud API used by the
`com.sunshare.cloud` Android app to monitor and control a Sunshare micro-storage/inverter system.
Built in three phases: BLE protocol analysis (dead end — this device generation is cloud-only for
control), MITM/Frida traffic capture (dead end — Flutter's bundled TLS trust store blocked
interception), and finally black-box REST API probing against a live account (this is what worked).

## Repo layout

| Path | What it is |
|---|---|
| `openapi/sunshare-api.yaml` | OpenAPI 3.0 spec — the source of truth for every endpoint, request/response schema, and confidence level (`[CONFIRMED]` / `[FAILING]` / `[UNTESTED]`). |
| `docs/index.html` | Stoplight Elements viewer for the spec above. Static page, no build step. |
| `API_DOCUMENTATION.md` | Narrative write-up: *why* each schema was chosen, failed attempts, and next-step suggestions for the endpoints that don't work yet. |
| `sunshare_api.py` | Python client (`login` / `call` / `raw` subcommands) used to derive the spec via live testing. |
| `.venv/` | Python virtualenv for `sunshare_api.py` (gitignored). |
| `PHASE1_FINDINGS.md`, `PHASE2_CAPTURE_GUIDE.md`, `analyze_capture.py`, `sunshare_ble.py` | Earlier BLE reverse-engineering phase — kept for reference, superseded by the REST API approach. |

Large/sensitive artifacts from the analysis (the decompiled `libapp.so`, string-pool dumps,
`adb bugreport` capture, pcaps) are gitignored — they contain real device/account data and aren't
needed to use or extend the documented API.

## Running the API docs locally

```bash
npm install
npm run docs
```

Then open **http://localhost:4400/docs/**.

This serves the whole repo (so the docs page can fetch `../openapi/sunshare-api.yaml`) using
[`serve`](https://github.com/vercel/serve) on port 4400. The docs page is Stoplight Elements
loaded from a CDN — no build step, no API key needed to view it.

Note: the spec's "Try it" button will hit CORS restrictions calling the real Sunshare API directly
from a browser (their server doesn't appear to set CORS headers for arbitrary origins) — use
`sunshare_api.py` for actually exercising the API, and treat the docs page as reference.

## Using `sunshare_api.py` directly

```bash
# create this yourself — never commit it, never paste your password into chat
echo '{"username": "you@example.com", "password": "..."}' > ~/.sunshare_credentials.json

.venv/bin/python sunshare_api.py login
.venv/bin/python sunshare_api.py call app/sysDeviceInfo/findDeviceListByUserId '{}'
```

**Important:** only one login session is valid per account at a time — logging into the phone app
invalidates a script session and vice versa. See `API_DOCUMENTATION.md` §2.

## Roadmap: Home Assistant custom integration

The API is now documented well enough to sketch what a `custom_components/sunshare/` integration
would look like. Not built yet — this is a plan, not a promise.

**Auth / config flow**
- A `config_flow.py` `ConfigFlow` asking for `userAccount`/`password`, storing them in HA's
  encrypted config entry storage (never in YAML).
- A small auth helper that logs in on startup and re-authenticates on 401 — needed because of the
  single-session-per-account limitation; HA's session would need to "win" against the mobile app,
  or vice versa, so this should be documented clearly for users in the integration's setup flow.

**Data layer**
- A `DataUpdateCoordinator` polling `findDeviceListByUserId` on an interval — confirmed this is a
  genuinely live-updating source (`power`/`consumption`/status flags change between polls; see
  `API_DOCUMENTATION.md` §3). Direct MQTT was investigated as an alternative to polling and ruled
  out — the credentials `findById` exposes are real and connectable, but scoped exclusively to the
  device's own live session; using them would mean permanently fighting the physical device for
  its own connection (§3a). REST polling is the right approach, no push/webhook path exists.
- Sensors to expose per device: output wattage (`permPower`), battery SOC limits (`socMin`/`socMax`
  — read-only until §6's write endpoint is solved), online status, RSSI, lifetime
  generation/revenue/CO₂ (`selectInveSummary`).

**Control**
- A `number` entity for output wattage, backed by `updateEmsParaById` (confirmed working — see
  spec).
- Battery charge/discharge SOC limits as `number` entities is **blocked** until
  `updateEmsModeAdvanById`'s request schema is found (currently `[FAILING]` — 6 schema variants
  tried, all fail identically). This would be the first thing to resolve before starting the HA
  integration, likely via decompiling `libapp.so` rather than more black-box guessing.

**Open questions before starting implementation**
- Confirm the single-session behavior doesn't cause a fight with the mobile app in normal use
  (maybe acceptable if users primarily control via HA).
- Rate-limit behavior is unknown — polling interval should be conservative until confirmed safe.
- Battery SOC control (`updateEmsModeAdvanById`) is still unsolved (§6) — worth resolving before
  committing to the integration's scope, since "control battery limits" would otherwise have to be
  cut from v1.
