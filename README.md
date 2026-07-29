# Sunshare Inverter — Reverse-Engineered Cloud API

> ## ⚠️ AI slop warning — read before using
>
> This entire repository — the reverse-engineered API docs, the Python client, and the Home
> Assistant integration — was written by an AI coding agent (Claude), with a human directing and
> spot-checking the conversation, **not** a full line-by-line security or code review. The API
> itself was reverse-engineered by string-pool analysis and black-box probing against a single real
> account; several fields documented as "confirmed live" earlier were later downgraded after more
> testing turned up contradicting evidence (see `API_DOCUMENTATION.md`'s liveness notes in §3/§3b).
> Treat every "\[CONFIRMED\]" in this repo as "confirmed at the time someone tested it," not as an
> audited guarantee.
>
> **Do not run this against a production/unattended Home Assistant instance, or point it at a
> device you depend on, without reading `custom_components/sunshare/` yourself first.** Concretely:
> it stores your Sunshare account password in HA's config entry, it calls an undocumented
> third-party cloud API that can change your inverter's real output wattage, and it has an
> unresolved single-session conflict with the official mobile app (§2). Use an isolated/test HA
> instance until you've reviewed the code and understand these tradeoffs.

Reverse-engineered documentation and tooling for the Sunshare/Sunsharetek cloud API used by the
`com.sunshare.cloud` Android app to monitor and control a Sunshare micro-storage/inverter system.
Built in three phases: BLE protocol analysis (dead end — this device generation is cloud-only for
control), MITM/Frida traffic capture (dead end — Flutter's bundled TLS trust store blocked
interception), and finally black-box REST API probing against a live account (this is what worked).

## Repo layout

| Path | What it is |
|---|---|
| `custom_components/sunshare/` | Home Assistant custom integration (config flow, coordinator, `number` + `sensor` platforms) — see below. |
| `hacs.json` | Marks the repo as a HACS-installable custom repository — see the installation instructions below. |
| `openapi/sunshare-api.yaml` | OpenAPI 3.0 spec — the source of truth for every endpoint, request/response schema, and confidence level (`[CONFIRMED]` / `[FAILING]` / `[UNTESTED]`). |
| `docs/index.html` | Stoplight Elements viewer for the spec above. Static page, no build step. |
| `API_DOCUMENTATION.md` | Narrative write-up: *why* each schema was chosen, failed attempts, and next-step suggestions for the endpoints that don't work yet. |
| `sunshare_api.py` | Python client (`login` / `call` / `raw` subcommands) used to derive the spec via live testing. |
| `.venv/` | Python virtualenv for `sunshare_api.py` (gitignored). |
| `PHASE1_FINDINGS.md`, `PHASE2_CAPTURE_GUIDE.md`, `analyze_capture.py`, `sunshare_ble.py` | Earlier BLE reverse-engineering phase — kept for reference, superseded by the REST API approach. |
| `.reverse_engieneering_data/` | Local-only raw artifacts (decompiled `libapp.so`, string-pool dumps, `adb bugreport`, pcaps) — gitignored, never pushed. See its own `README.md`. |

Large/sensitive artifacts from the analysis (the decompiled `libapp.so`, string-pool dumps,
`adb bugreport` capture, pcaps) live in `.reverse_engieneering_data/` and are gitignored — they
contain real device/account data and aren't needed to use or extend the documented API.

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

## Home Assistant custom integration

`custom_components/sunshare/` is a working v1 (config flow + coordinator + `number` + `sensor`
platforms).

### Installing

**Option A — HACS (custom repository)**

This repo isn't in the default HACS store (it's a private/internal reverse-engineered integration,
not something to submit there) — add it as a HACS **custom repository** instead. Read the AI-slop
warning at the top of this file before doing this on a real HA instance.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DelphiXE5&repository=homeassistant-sunshare&category=integration)

That button requires the [My Home Assistant](https://www.home-assistant.io/integrations/my/)
integration and HACS already installed, and opens the "add custom repository" dialog pre-filled.
Manually, the same thing:

1. HACS → the "⋮" menu (top right) → **Custom repositories**.
2. Repository: `https://github.com/DelphiXE5/homeassistant-sunshare`, category **Integration**.
3. Find "Sunshare" in HACS → **Download**.
4. Restart Home Assistant.
5. **Settings → Devices & Services → Add Integration → Sunshare**, enter your Sunshare account
   email + password.

A minimal `hacs.json` is included at the repo root so HACS recognizes it once added; there's no
GitHub Release/tag yet, so HACS will track the default branch until one is cut.

**Option B — manual copy**

1. Copy `custom_components/sunshare/` into `<home-assistant-config>/custom_components/sunshare/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Sunshare**, enter your Sunshare account
   email + password.

**Auth / config flow** — `config_flow.py` asks for the account email + password, validates them
with a live login, and stores them in HA's encrypted config entry storage. An options flow lets
you tune the polling interval (default 30 s, min 10 s) — see the "open questions" below on rate
limits. Because of the single-session-per-account limit (`API_DOCUMENTATION.md` §2), setting this
up will kick out an active mobile-app session, and vice versa.

**Data layer** — `coordinator.py`'s `SunshareDataUpdateCoordinator` polls, per device,
`findDeviceListByUserId` + `findById` + `queryMesSettingUpdate` + `selectInveSummary` on every
interval and merges them into one `SunshareDevice`. No MQTT — see §3a, direct-broker access is
single-occupancy by design and unusable for a long-running integration.

**Control** — `number.py` exposes exactly one entity: **output power** (0 W .. the device's
`countryMaxPower`), backed by the confirmed `updateEmsParaById` call. This is the integration's
main actor, as requested.

**Sensors** (`sensor.py`) — split into three groups:
- *Confirmed*: status, Wi-Fi RSSI, firmware version, country max power, battery charge/discharge
  SOC limits (`socMin`/`socMax` — these are the *charging-range settings*, not a live charge level),
  lifetime + today's energy generated, lifetime revenue, lifetime CO₂ saved.
- *Battery telemetry* — SOC, temperature, remaining/rated capacity (kWh), backed by
  `app/sysDeviceInfo/findBatteryAndDsSsById`, found via string-pool analysis while investigating why
  `findById`'s `soc`/`temp1` didn't match reality (see below) — SOC/temp/capacity confirmed live and
  correct (API_DOCUMENTATION.md §3b). The fifth field, *battery power* (`batPow`), is **not**
  confirmed live (see next point) — kept as a sensor since it's the right unit/identity, but don't
  trust the number yet.
- *Unconfirmed liveness* (clearly labeled "(raw, unconfirmed)" or documented as such, diagnostic
  category): `power`/`consumption` from `findDeviceListByUserId`, and `batPow` from
  `findBatteryAndDsSsById`. Originally thought live; a 2026-07-29 test polling all three every
  8–15 s for 4+ minutes during a **verified real event** (device discharging the battery at ~200 W
  to the grid) had **all three stuck at exactly 0 the whole time**. The account holder also
  confirmed the app's own homescreen wattage figure stays perfectly fixed even while real output
  changes — strong evidence it's displaying `permPower` (the target setting) rather than a live
  measurement. **No confirmed source for a true live "current output"/"PV input" reading exists in
  this API yet.** The integration's `number` entity (`permPower`) remains the closest thing to a
  "current output" value — it's a setting, not a measurement. **Open task:** if a longer refresh
  cycle or a charging (not discharging) event ever shows movement in these three fields, promote
  the relevant one to a primary sensor (rename in `sensor.py`'s `SENSOR_DESCRIPTIONS`, no
  architecture changes needed) — otherwise this line of investigation may be a dead end.

**Not implemented**
- Battery SOC *limit* control (`updateEmsModeAdvanById`) is still `[FAILING]` in the API (§6, 6
  schema variants tried); a `number` entity for `socMin`/`socMax` write access is blocked on that.

**A dead end worth knowing about:** `findById`'s `soc`/`temp1` fields looked promising at first but
are confirmed dead placeholders (cross-checked 2026-07-29: app showed 21 % / 0.32 kWh / 23°C while
`findById` simultaneously returned `soc: 0`/`temp1: 0` with a 3-day-stale `updateTime`) — see
API_DOCUMENTATION.md §3. The real source, `findBatteryAndDsSsById`, was found right after via
static string-pool analysis of `libapp.so` (traffic sniffing remains a dead end for this app, see
`PHASE2_CAPTURE_GUIDE.md`); the `iot.sunsharetek.com`/`dev.sunsharetek.com` hosts were also tried
as an alternative and confirmed **not** usable for this account (reachable, but reject its
credentials) — `web.sunsharetek.com` is the only working host.

**Open questions**
- Confirm the single-session behavior is acceptable in your household (HA vs. mobile app).
- Rate-limit behavior is unknown — the default 30 s interval is a conservative guess, tune via the
  options flow if needed.
