# Sunshare / Sunsharetek Cloud REST API — Reverse-Engineered Documentation

Reverse-engineered from the Android app (`com.sunshare.cloud`, versionName `1.2.0`) via static
string-pool analysis of the Flutter/Dart AOT snapshot (`libapp.so`) plus black-box live testing
against a real account/device. See `PHASE1_FINDINGS.md` for the original static-analysis notes and
`sunshare_api.py` for a working Python client used to derive this document.

Confidence legend:
- ✅ **Confirmed working** — tested live, response verified (and, for control endpoints, verified to
  actually change device state).
- ⚠️ **Confirmed reachable, wrong/unknown schema** — the path exists and responds, but every request
  body tried so far fails; best-guess schema is documented.
- ❔ **Untested** — found only in the app's string pool / Dart class list, never called live. Schema
  is a best-effort guess from adjacent pool strings and naming convention. Treat as a starting point,
  not a confirmed contract.

## 1. Base URLs & environments

| Host | Role |
|---|---|
| `https://web.sunsharetek.com/app/` | Production — confirmed working, used for all testing here |
| `https://iot.sunsharetek.com/app/` | Found in binary, untested |
| `https://dev.sunsharetek.com/app/` | Found in binary, untested (likely a dev/staging backend) |

**Path-prefix gotcha:** the base URL already ends in `/app/`. Most `sysDeviceInfo`/`sysMicoInverter*`/
`inveRealDataMinute` endpoint strings found in the binary *also* start with a literal `app/` — this is
not a mistake, both prefixes are real and required. So the actual URL is
`https://web.sunsharetek.com/app/` + `app/sysDeviceInfo/findById` = `.../app/app/sysDeviceInfo/findById`.
`auth/*` and `purview/*` paths do **not** get this doubling (they're a different route module).

## 2. Authentication

### `POST auth/login` ✅

Full URL: `https://web.sunsharetek.com/app/auth/login`

Request body:
```json
{"userAccount": "user@example.com", "password": "plaintext-password"}
```
The field **must** be `userAccount` — `username`, `email`, and `loginEmail` were all tried and
rejected with a validation error (`"Please enter your Email address"`).

Response (200):
```json
{
  "code": 200,
  "msg": null,
  "data": {
    "access_token": "<JWT>",
    "expires_in": 43200,
    "realTime": 2500,
    "incomeTime": 60000,
    "devicePage": 3000,
    "faultTime": 3000,
    "deviceTime": 3000,
    "switchTime": 25000
  }
}
```
Use `data.access_token` **verbatim** (no `Bearer ` prefix) as the `Authorization` header on every
subsequent call.

**⚠️ Security note (incidental finding, not part of the task but worth knowing):** the JWT's payload
(base64-decoded) embeds the account's bcrypt password hash, user id, area id, and account email in
plaintext-visible-if-decoded form. Not actionable for us, but notable app-side hygiene issue.

**Single-session constraint:** only one token is valid at a time. Logging into the mobile app
invalidates a script's token, and vice versa — a second login anywhere immediately 401s the other
session's calls. Always log in fresh immediately before a batch of calls if the app might also be
active.

### Common headers on every call
```
Content-Type: application/json
language: en
localeName: en
Authorization: <access_token>   (omit for auth/login itself)
```

## 3. Device discovery & info

### `POST app/sysDeviceInfo/findDeviceListByUserId` ✅
Body: `{}` (user identity comes from the JWT).

Returns an array of the account's devices with live-ish summary fields:
```json
{
  "code": 200,
  "data": [{
    "id": 14926,
    "sn": "020225I1903A0",
    "deviceName": "Mein Speicher",
    "deviceType": 2,
    "deviceTypeDec": "Micro-storage",
    "power": 0.0,
    "consumption": 0.0,
    "es": 0,
    "ss": 0,
    "ds": 1,
    "emsStatus": 1,
    "statusDec": "on-line",
    "rssi": -55,
    "countryMaxPower": 800,
    "wifiName": "FRITZ!Box 6660 Cable RW",
    "clientId": "GID_sun@@@020225I1903A0"
  }]
}
```
`id` is the numeric `deviceId` used by almost every other endpoint. `sn` is the physical device
serial (matches the BLE advertised name from the earlier BLE phase). `es`/`ss`/`ds` are short
status flags whose exact meaning wasn't fully confirmed (`ds`=device status, `ss`=solar status,
`es`=energy-storage status, by naming convention — unconfirmed).

**⚠️ `power`/`consumption` liveness — downgraded from an earlier "confirmed live" claim.** The
original basis for that claim was weak (only `ss` changed value across two polls; `power`/
`consumption` themselves stayed `0.0` both times, i.e. no positive evidence they ever move). A
follow-up test on 2026-07-29 during a **verified real event** — the device actively feeding
~200 W to the grid from battery, confirmed by the account holder watching the physical
setup — polled `findDeviceListByUserId`, `findBatteryAndDsSsById` (§3b) and
`findDeviceRealStatusByDeviceId` every 8–15 s for over 4 minutes, plus once with
`queryOnlineStatusByDeviceIdAndOpenRealTime` opened first: **`power`, `consumption`, and
`findBatteryAndDsSsById`'s `batPow` stayed at exactly `0` throughout, the entire time real power
was flowing.** Only `queryMesSettingUpdate`'s `permPower` (`200`) matched the real 200 W —
but that's the constant-output *target setting*, not an independent measurement.

**Further evidence it's the setting, not a live reading:** the account holder confirmed the app's
own homescreen "200 W" figure **stayed perfectly fixed** while watched for 30–60 s (no fluctuation
at all, unlike a real meter), and separately reported that actual physical output dropped to `0`
once the battery hit its discharge cutoff (`socMin=20%`, §5) — i.e. the true physical output
changed state (200 W → 0 W) in a way neither the API's `power`/`consumption`/`batPow` fields nor
(apparently) the app's own displayed number reflected in real time.

**Update 2026-07-29, 08:31 — retested during confirmed real solar generation (~40 W) and now
effectively closed.** With the account holder confirming genuine, non-trivial solar input
happening at the moment of the call (not idle, not a discharge-to-cutoff edge case — a third,
independent real condition), `power`/`consumption` (and `batPow`, §3b) **still read exactly `0`.**
Across all three tested real conditions now (idle, ~200 W battery discharge, ~40 W solar
generation), these fields have never once shown a non-zero value. **Conclusion: treat
`power`/`consumption`/`batPow` as non-functional for this account via these endpoints** — not
"unconfirmed pending more testing," but as settled a negative result as black-box testing without a
working traffic-capture method can produce (see `PHASE2_CAPTURE_GUIDE.md` for why MITM isn't
available here). **No confirmed source for a true independent "current power output" or "PV
input" reading exists in this API.** The Home Assistant integration's `number` entity (backed by
`permPower`) remains the closest thing to a "current output" value, and it is a target/setting,
not a measurement — see README.md. These three fields are kept as diagnostic sensors in the
integration only on the off chance a much longer/different refresh cadence than tested here
reveals movement — a tighter, faster-cadence retest (matching the login response's `realTime: 2500`
hint, §2) was also tried and made no difference (still flat `0`) — don't expect them to ever show
anything but 0 in practice.

**Side observation while retesting — `permPower` drifted across four checks (200 → 260 → 230 →
160) over about 2 hours — explained, not mysterious:** the account holder confirmed this is the
Home Assistant integration's own `number` entity being adjusted (an automation on their end),
**not** some device/server-side auto-optimization as first guessed here. Correcting that guess:
`permPower` is exactly the flat, externally-set target it was always documented as (§5/§6) — the
"drift" was this project's own control loop, observed from the read side without realizing it at
the time. Doesn't change anything about `power`/`consumption`/`batPow`'s liveness conclusion above,
which was based on independent direct observation, not on this (mistaken) reasoning.

**Also worth tracking — `findBatteryAndDsSsById`'s `bhs` field changed value again independently**
(`0` at 06:45 → `2` at 08:31, having earlier gone `0`→`2` around the first discharge-cutoff event
too). This is now the *second* time `bhs` has changed value across real, independently-verified
conditions — the strongest evidence yet that it's a genuine live status flag (as opposed to
`power`/`consumption`/`batPow`, which have never moved once). Its exact meaning is still unknown
(enum with at least values 0 and 2 seen so far); a promising thread if anyone wants to keep
correlating it against real device state.

### `POST app/sysDeviceInfo/findById` ✅
Body: `{"id": <deviceId>}`

Returns the **full** device entity — the richest single read call. Notable fields:
```json
{
  "id": 14926,
  "sn": "020225I1903A0",
  "deviceName": "Mein Speicher",
  "model": "SR-C1K2EU",
  "brand": "SUNSHARE",
  "hwVersionNo": "HW1000.0002.0002",
  "otaVer": "V1.097.0",
  "appVersion": "1.2.0",
  "permPower": 200,
  "maxGridPower": 800,
  "countryMaxPower": 800,
  "emsModePara": "{\"emsStrategyType\":1,\"permPower\":200,\"powerSetPojos\":[],\"deviceId\":14926,\"homeId\":2229,\"isOnlySave\":0,\"eleType\":0}",
  "emsModeAdvan": "{\"countryMaxPower\":800,\"socMax\":96,\"socMin\":20,\"zeroNetworkButton\":0}",
  "electrovalency": 0.36,
  "currency": "USD",
  "eleUnit": "EUR",
  "areaId": 33,
  "areaName": "Germany",
  "lat": "51.0284907",
  "lon": "13.7202112",
  "warranty": "2036-06-29",
  "instanceId": "mqtt-cn-fxf45evy502",
  "endPoint": "mqtt-cn-fxf45evy502.mqtt.aliyuncs.com:8883",
  "userName": "DeviceCredential|DC.QZ9xX8SrQRapKTtED6BONA|mqtt-cn-fxf45evy502",
  "clientId": "GID_sun@@@020225I1903A0",
  "mapList": [{"packSn": "020625I30020A", "warrantyTime": "2036-06-29"}]
}
```
**Important:** `permPower` appears both as a top-level column *and* embedded inside the
`emsModePara` JSON-string. **The top-level column is cosmetic/denormalized — only the value inside
`emsModePara` (and `emsModeAdvan`) actually drives the physical device.** See §5 for why this matters.

**Fields found only while building the Home Assistant integration, not previously documented, and
now confirmed dead** — `findById`'s response is far wider than the excerpt above; a full dump
against the live account (02:22 local time, no PV, presumably no load) also showed:
```json
{"soc": 0, "temp1": 0, "socPer": null, "currentPower": null, "totalPower": null,
 "disStopSoc": null, "chargeStopSoc": null, "onlineStatus": null, "workStatus": null,
 "onoroffStatus": null, "bcs": null, "batData": null, "packRateWh": null, "inverterP": null,
 "pe": null}
```
By naming convention `soc` looked like the live battery state-of-charge percentage and `temp1` an
inverter/battery temperature. **Cross-checked live against the app itself the same
day (2026-07-29): the app showed the battery at 21 % SOC / 0.32 kWh capacity / 23°C, while
`findById` simultaneously returned `soc: 0`/`temp1: 0`.** The response's own `updateTime` field
was `2026-07-26 23:35:30` — three days stale — confirming this isn't a transient miss but that
`findById`'s row is a periodic/event-driven snapshot that these two columns were never wired into.
**Verdict: `findById.soc`/`findById.temp1` are dead placeholders, not live telemetry — do not use
them.** Same failure pattern as `findDeviceRealStatusByDeviceId`'s power/consumption (§3 above).

**Resolved — see §3b below.** The endpoint the app actually uses for live battery SOC/capacity/
temperature is `app/sysDeviceInfo/findBatteryAndDsSsById`, found via string-pool analysis (traffic
sniffing was tried in an earlier phase and is a dead end — Flutter's bundled TLS trust store blocks
interception, see `PHASE2_CAPTURE_GUIDE.md`) and confirmed live + correct against the same live
cross-check (21 % / 23°C) that first exposed `findById.soc`/`temp1` as dead.

Also reveals the device connects to an **Alibaba Cloud IoT MQTT** broker
(`mqtt-cn-fxf45evy502.mqtt.aliyuncs.com:8883`) — this is almost certainly the real transport that
pushes settings to hardware; the REST API is a thin control-plane in front of it. See §3a for a full
writeup of a live test connecting directly to this broker — short answer: it works, but isn't usable
for a sustained integration.

### 3a. Can a third party connect directly to the device's Alibaba Cloud IoT MQTT broker? ⚠️ Tested live — not viable

Investigated because `findById` exposes what look like ready-to-use MQTT connect parameters:
`endPoint` (`mqtt-cn-fxf45evy502.mqtt.aliyuncs.com:8883`), `clientId`
(`GID_sun@@@020225I1903A0` — note the suffix is literally the device `sn`), `userName`
(`DeviceCredential|DC.QZ9xX8SrQRapKTtED6BONA|mqtt-cn-fxf45evy502`), and a `password` field.

**Static analysis first:** searched the app's Dart snapshot and raw `classes*.dex` bytecode for any
MQTT client (Dart package, or a native Alibaba IoT "LinkKit" `.so`) — found neither. The only
Alibaba code present is `com.aliyun.sls.*`, their Log Service SDK (crash/telemetry logging),
completely unrelated to IoT/MQTT. There's a `control_mqtt_mode.dart` / `OperatorMqtt` class (a
sibling to the BLE control path, `control_ble_mode.dart` / `OperatorBle`), but with no MQTT client
anywhere in the app, it almost certainly just calls the REST API — "Mqtt mode" describes the
device's transport, not the app's. **Conclusion: the app itself never connects to this broker
directly; the `findById` fields are read-only status metadata about the device's own connection**
(matches the class name `DeviceMqttStatusEntity`), most likely surfaced server-side by Alibaba's
`GetDeviceCredential`-style API and just relayed for display/diagnostics.

**Live test (with explicit user sign-off, since this touches a real physical device's cloud
session):**
1. TCP+TLS reachability check to the endpoint (no MQTT packet sent, zero risk) — succeeded,
   real TLS 1.3 handshake, confirming a genuine live Aliyun broker instance.
2. Authenticated `CONNECT` using the exact `clientId`/`userName`/`password` from `findById`, via
   `paho-mqtt` — **accepted (`rc=0`)**. The credentials are real and directly usable with a
   standard MQTT client, no signing/derivation needed.
3. Reconnected and subscribed to broad wildcards (`#`, `+/+`, `+/+/+`, `+/+/+/+`) for a 20-second
   window — the connection **reconnected roughly every 1.5–2 seconds** for the whole window
   (~12 cycles) and **zero messages** were received on any subscription.
4. Tried connecting with two different, non-colliding client IDs (`sunshare-ha-observer-001`,
   `GID_sun@@@020225I1903A0_observer`), same username/password — both got **`rc=5` (Not
   Authorized)** immediately.

**Interpretation:** step 4 confirms Alibaba's device-credential auth is scoped to that *exact*
client ID — there is no way to obtain a separate, non-colliding identity with these credentials.
Combined with step 3's rapid reconnect-fight (consistent with the device's own firmware retrying
on a short backoff after being kicked), this means **any connection under this identity directly
contends with the device's real, live session for as long as it's held open.** A brief
connect-then-disconnect is a short, self-recovering blip; holding the connection open — which is
what continuous telemetry/control would require — means permanently and repeatedly disconnecting
the physical device's own cloud session. This is not a workaround-able quirk; it's exactly what
per-device credential scoping is designed to prevent.

**Verdict: do not build a Home Assistant integration (or anything else long-running) on this
channel.** It's a genuine, working MQTT credential, but single-occupancy by design. Stick to the
REST API (§3's `findDeviceListByUserId`, confirmed to carry live-updating power/status fields) for
polling, and `updateEmsParaById` (§6) for control.

### 3b. `POST app/sysDeviceInfo/findBatteryAndDsSsById` ✅ — the real live battery telemetry endpoint

Not in the app's confirmed string pool the first time §3 was written — found via a second,
targeted `strings` pass over `libapp.so` grepping for `pack|batt|soc|temp|realdata`, since traffic
sniffing (MITM/Frida) is a confirmed dead end for this app (`PHASE2_CAPTURE_GUIDE.md`) and was
explicitly ruled out again for this follow-up. Also checked: the `iot.sunsharetek.com` and
`dev.sunsharetek.com` hosts mentioned in §1 as "found in binary, untested" — both are live and
reachable (HTTP 200), but both reject this account's credentials with `"The username or password
is incorrect"`, confirming they're either separate environments/accounts or simply not used for
this account. `web.sunsharetek.com` remains the only working host.

Body: `{"id": <deviceId>}` — same key as `findById`, **not** `deviceId` like most other calls.

```json
{
  "code": 200,
  "data": {
    "ss": 1,
    "socPer": "20%",
    "mapList": [
      {"packSn": "020625I30020A", "warrantyTime": "2036-06-29", "soc": "20%", "power": "1.50", "temp1": 23}
    ],
    "bcs": 0,
    "currentPower": "0.30",
    "batPow": 0,
    "currentDate": "2026-07-29 02:39:22",
    "bhs": 0,
    "totalPower": "1.50",
    "ds": 1
  }
}
```

**Confirmed live/correct at the time this section was first written, two independent ways** (see
important caveat below though):
1. `currentDate` is a server-generated timestamp that matched the real wall-clock request time on
   the first two calls (re-polled 50s apart: `02:38:32` → `02:39:22`, both exactly matching actual
   request time) — unlike `findById`'s `updateTime`, which sat 3 days stale.
2. Cross-checked against the app itself the same session: app showed battery **21 % SOC / 0.32 kWh
   remaining / 23°C**, packSn `020625I30020A`. The API returned `packSn: "020625I30020A"` (exact
   match), `temp1: 23` (exact match), `soc`/`socPer: "20%"` (same ballpark — plausibly a slightly
   later/earlier read on a slowly-draining idle battery), and `currentPower: "0.30"` — which is
   `0.20 × totalPower(1.50)`, i.e. SOC% × rated capacity, matching the app's 0.32 kWh within normal
   rounding/timing drift.

**⚠️ Caveat found in later testing (same day):** during the extended background poll referenced in
§3's liveness note, `currentDate` was observed to **repeat the exact same value
(`2026-07-29 02:53:10`) across two polls 32 seconds apart**, whereas the first test above showed it
changing within 50 seconds. This is more consistent with **the whole response being server-side
cached for some interval** (which happens to include `currentDate` at cache-write time) than with
every call reaching a truly live source — meaning the earlier "confirmed live via `currentDate`"
conclusion needs qualifying: the endpoint is at least *sometimes* fresher than `findById` (which
never moved across 3 days), but is not proven to be live on every single call. This is also
consistent with `batPow`/`power`/`consumption` never moving during the same test window (§3): if
responses are cached for minutes at a time, a 4-minute poll could easily fall entirely inside one
cache window and see zero movement regardless of real device activity.

**One field did change, though:** `bhs` flipped from `0` to `2` between the first live-load test
(§3's `poll_live2.sh` run, ~02:53) and the later background poll (~02:55), right around when the
account holder reported the battery hitting its `socMin` discharge cutoff. This is the only field
across all of this testing that has ever been observed to change value, which is reasonably strong
evidence `bhs` is a real, event-driven status flag (previously guessed as possibly "battery health
status" — a charge/discharge-inhibited-state flag now seems at least as plausible given the
timing). Not enough data yet to build a Home Assistant sensor around it with confidence, but worth
tracking why/when it changes in a future session.

**Testing note:** this second round of live testing was cut short by a `401` (the account's
single-session-per-account limit, §2, was hit again — the account holder was actively using the
mobile app to watch the same event) partway through the 10-minute background poll. Further
testing was paused rather than repeatedly re-logging in and fighting the user's own live app
session.

**Field meanings — confirmed via the app's own UI tooltip strings found alongside these field names
in the string pool** (numbered list shown in the app's battery-info dialog):
- `socPer` = *"State of Charge (%): Average SOC of all batteries"* — average across all packs.
- `currentPower` = *"Remaining Capacity (kWh): Total estimated energy of all batteries"* — despite
  the misleading "Power" in the name, this is **capacity in kWh, not instantaneous power**.
- `totalPower` = *"Rated Capacity (kWh): Sum of all batteries' rated capacity"* — same "Power"
  naming trap, also kWh not W.
- `mapList[]` = per-pack breakdown (`packSn`, per-pack `soc`, per-pack `power` [= per-pack rated
  capacity, kWh], per-pack `temp1` [°C, confirmed]).
- `batPow` — **not** covered by a tooltip string; by naming convention (and being the one field
  actually in Watts, distinct from the kWh-but-named-"Power" fields above) this is a plausible
  candidate for instantaneous battery charge/discharge power. **⚠️ Downgraded after a follow-up
  test (2026-07-29, see §3's liveness note):** polled every 8–15 s for 4+ minutes during a period
  the account holder describes as the device actively discharging the battery at ~200 W to the
  grid — `batPow` stayed at `0` throughout, same flat-zero pattern as `power`/`consumption`. Could
  mean `batPow` isn't live either, or that true output was already near-zero for the whole test
  window (the battery was sitting right at its `socMin=20%` cutoff — plausible the discharge had
  already throttled down before polling started). **Treat as unconfirmed, not "very likely",
  pending a test during a charge cycle or a discharge caught clearly before cutoff.**
- `ds`/`ss` — same device-status/solar-status flags seen in `findDeviceListByUserId` (§3).
- `bcs`/`bhs` — new, no tooltip found; by naming convention possibly "battery charge status" /
  "battery health status", both `0` at idle/presumably-healthy. Untested further — not surfaced as
  Home Assistant sensors, too speculative to be useful yet.

This is still the recommended endpoint for battery SOC/temperature/capacity in a Home Assistant
integration (see README.md) — those fields' liveness is independently confirmed (§3b above) —
`findById`'s `soc`/`temp1` (§3 above) should not be used. `batPow` is included as a sensor but with
downgraded confidence per the above.

### 3c-FINAL. ✅✅✅ FULLY SOLVED & REPLICATED — live power via `systemDiagramUpdate` (AES-encrypted channel)

**This is the definitive answer and it is confirmed working from a standalone script (no app, no
device-push dependency required beyond an open real-time session).** The app reads live power from
a **known** `/app/` endpoint that this document had already listed but mis-tested, because the app
uses an **encrypted request/response channel** that plaintext probing never triggered.

**Endpoint:** `POST /app/app/sysDeviceInfo/systemDiagramUpdate` (polled ~every 2 s by the app).

**Required header:** `encchannel: 1` (plus the usual `Authorization: <access_token>`). Without this
header the server returns a plaintext empty `{"msg":null,"code":200}` — which is exactly why every
earlier plaintext test of `systemDiagramUpdate` looked "empty/dead".

**Crypto:** **AES-128-ECB, PKCS7 padding, static key `sunsharesunshare`** (16 ASCII bytes;
`73756e736861726573756e7368617265`). ECB (no IV) — confirmed by block-analysis (identical plaintext
blocks → identical ciphertext blocks across responses) and by a known-plaintext key search over the
iOS `App` binary (the key sits at file offset `0xb170c0`; block 0 decrypts to `{"msg":"success"`).
The same key/mode is used for both request and response, and for all `encchannel:1` endpoints.

**Request body:** `{"encryptData": "<base64( AES-ECB-encrypt( JSON ) )>"}` where JSON is
`{"clientId":"GID_sun@@@<sn>","deviceId":<id>}`.

**Response body:** a raw base64 blob (the whole envelope is encrypted). base64-decode → AES-ECB
decrypt → strip PKCS7 → JSON:
```json
{"msg":"success","code":200,"data":{
  "pvPow":586, "pv1Pow":0, "pv2Pow":586,      // total PV + per-MPPT-string input power (W)
  "invPow":190,                               // inverter output power (W)
  "batPow":-396,                              // battery power (W); NEGATIVE = charging, positive = discharging
  "loadPow":190, "gridPow":0,                 // household load / grid power (W)
  "soc":45,                                   // battery state-of-charge (%)
  "energyFlowType":4, "bhs":0, "deviceId":14926,
  "iPa":null,"iPb":null,"iPc":null,           // per-phase currents (single-phase unit → null)
  "pvPreal":586,"invPreal":190,"batPreal":-360,
  "oldPvPow":.., "oldInvPow":.., "oldBatPow":.., "oldLoadPow":..,  // previous sample
  "time":1785335998675, "clientId":"...", "deviceType":2}}
```

**Prerequisite:** an open real-time session — call `queryOnlineStatusByDeviceIdAndOpenRealTime`
(`{"deviceId":<id>}`) first and re-assert it as a keepalive; this makes the device push fresh
samples that `systemDiagramUpdate` returns. (Subject to the §2 single-session limit — HA will
contend with the mobile app.)

**Verified end-to-end 2026-07-29** from `sunshare_api.py`-style standalone code: logged in, opened
the session, sent the encrypted request with `encchannel:1`, and decrypted a live response
(`pvPow=300, invPow=300, batPow=0, soc=69` — values distinct from the app-capture, i.e. genuinely
live and independent of the app). **This is directly usable by the Home Assistant integration** —
it finally provides the three originally-requested live sensors (PV input `pvPow`, current output
`invPow`, battery power `batPow`) plus SOC/load/grid. See README.

**How this endpoint relates to the plaintext `collect-service` push (below):** the ESP32 device
POSTs raw telemetry to `collect-service` (unencrypted, §3c-CAPTURE below); the server caches it and
serves it to the app through the `encchannel:1` `systemDiagramUpdate` read. Two valid data paths now
exist for a HA integration: (a) this encrypted cloud read (works today, key known), or (b) the local
plaintext device push. The cloud read is simpler to implement (no LAN/DNS setup) and is the
recommended default.

---

### 3c-CAPTURE. How the live data was first located — on-device network capture

The question "where does the app get its second-accurate live wattage" is answered, and it is
**not** in the `/app/` API at all. A packet capture on the customer's own WLAN
(`.reverse_engieneering_data/wlan-*.eth`, taken while the mobile app was open) shows the
**inverter's own Wi-Fi module** (`User-Agent: ESP32 HTTP Client/1.0`) POSTing telemetry to a
completely separate microservice **every ~3 seconds**:

```
POST https://web.sunsharetek.com/collect-service/collect/emsRealDataMinute/realTimeElectricFlow
User-Agent: ESP32 HTTP Client/1.0
Content-Type: application/json         (no Authorization header — device-side ingestion)

{"clientId":"GID_sun@@@020225I1903A0","deviceType":"2","time":1785327128057,
 "pvPow":86,"pv1Pow":0,"pv2Pow":98,"offGridPow":2,"otherPow":0,"batPow":0,
 "loadPow":190,"invPow":86,"gridPow":104,"pvPreal":98,"batPreal":1,"invPreal":86,
 "smtdP":0,"iPa":null,"iPb":null,"iPc":null,"soc":18,"bhs":0}
```
Server replies `{"msg":"success","code":200}`. This is **device → server ingestion**, not a read —
but it hands us the complete, authoritative real-time schema and confirms the values are real
(`soc:18` matches §3b's live SOC; `loadPow:190` matches `permPower`; two MPPT strings `pv1Pow`/
`pv2Pow` match the hardware).

**Field mapping (this is the answer to the integration's original three-sensor request):**

| Field | Meaning | Example |
|---|---|---|
| `pvPow` | **Total PV / solar input power (W)** — the "PV Input" sensor | 86 |
| `pv1Pow` / `pv2Pow` | Per-MPPT-string PV power (W) — this device has **2 trackers** | 0 / 98 |
| `invPow` | **Inverter output power (W)** — the "Current Power Output" sensor | 86 |
| `batPow` | **Battery power (W)** — the "Battery In/Output" sensor (0 here: at `socMin` cutoff) | 0 |
| `gridPow` | Grid power (W) | 104 |
| `loadPow` | Household load (W) | 190 |
| `offGridPow` | Off-grid-port power (W) | 2 |
| `otherPow` | Other/unaccounted power (W) | 0 |
| `pvPreal` / `batPreal` / `invPreal` | Per-source "real" instantaneous readings (W) | 98 / 1 / 86 |
| `smtdP` | Smart-meter power (W) — 0, no meter accessory | 0 |
| `iPa` / `iPb` / `iPc` | Per-phase currents (null — single-phase unit) | null |
| `soc` | Battery state-of-charge (%) | 18 |
| `bhs` | Battery status flag (seen 0/2 elsewhere) | 0 |

**The app's READ side — found by black-box probing of `collect-service`:**
`GET https://web.sunsharetek.com/collect-service/collect/emsRealDataMinute/getRealTimeElectricFlow?clientId=<clientId>`
- Confirmed to exist and to be the right shape: it **requires** query param `clientId` (omitting it
  → `"Required request parameter 'clientId'"`), and is **GET** (POST → `"Request method 'POST' not
  supported"`). Sibling verbs `selectRealTimeElectricFlow`/`queryRealTimeElectricFlow`/
  `lastRealTimeElectricFlow` also exist but take a Long `id` (row-id reads, not useful live).
- **Why it doesn't (yet) return data for a script — two gates, one of them a Sunshare bug:**
  1. **The device only pushes while a real-time session is open.** With the app closed and no
     session, `getRealTimeElectricFlow` returns a bare empty `500` (Redis key absent). The customer's
     own observation — "this only happens when I open the app" — is exactly this: opening the app
     starts the ESP32's 3-second upload loop (server → MQTT → device), which is what fills the cache.
     This also finally explains §3/§3b: every earlier "always 0" test had the app closed, so the
     device was silent and there was genuinely no live data server-side to read.
  2. **After `queryOnlineStatusByDeviceIdAndOpenRealTime` (`openRealTime`) is called, the read
     endpoint changes to a hard server-side error:**
     `io.lettuce.core.RedisCommandExecutionException: WRONGTYPE Operation against a key holding the
     wrong kind of value`. This is a **bug in Sunshare's backend** — `getRealTimeElectricFlow` issues
     a Redis string GET against a key that (in the state a script-opened session leaves it) holds a
     different Redis type. Not fixable or tunable from the client; no parameter variant avoids it
     (`deviceType`, `time`, `id`, `deviceId` all identical).

**Trigger CONFIRMED (2026-07-29 12:31, second capture `wlan-129_29.07.26_1231.eth`):** with the
mobile app **closed**, a script calling `queryOnlineStatusByDeviceIdAndOpenRealTime`
(`openRealTime`) and re-asserting it every ~3s caused the ESP32 to begin POSTing
`realTimeElectricFlow` every ~3s for the whole window (`time` values `1785328281948`… land exactly
inside the 12:31:2x trigger window; live values `pvPow:97, pv2Pow:109, invPow:97`). So
**`openRealTime` is the trigger** — no real app needed to start the device's push. This also
retroactively explains every earlier "always 0" result in §3/§3b: those tests had the app closed
and no session, so the device was silent and the server genuinely had nothing live to serve.

**But the cloud READ path is blocked by a Sunshare server bug.** Even with the device actively
pushing (verified), during an open session `getRealTimeElectricFlow?clientId=GID_sun@@@…` returns
`io.lettuce.core.RedisCommandExecutionException: WRONGTYPE`. Diagnostics pin it down precisely: the
error only occurs for the **exact full `clientId`** (`GID_sun@@@020225I1903A0`) — a truncated/other
key returns the generic empty error instead — proving the device's data **is** stored in Redis
under that clientId, but `getRealTimeElectricFlow` issues the wrong Redis command for the key's
actual type (e.g. a string GET against a hash/list). Not client-fixable; no parameter variant
(`deviceType`, `time`, `id`, `sn`, alternate clientId forms) avoids it. Every `/app/`-service read
(`findDeviceRealStatusByDeviceId`, `findDeviceListByUserId`, `findBatteryAndDsSsById`,
`systemDiagramUpdate`, …) also stays `null`/`0` even during an active push — none of them is wired
to this Redis cache.

**The decisive practical finding: the ESP32 pushes over plain-text HTTP, not HTTPS.** The captures
are readable precisely because the device firmware uses `http://web.sunsharetek.com/collect-service/…`
(User-Agent `ESP32 HTTP Client/1.0`, no TLS, no auth header — only the app's own traffic is
TLS-pinned). **This makes a fully local, cloud-independent integration feasible without ever
solving the buggy cloud read:** on the device's LAN, override DNS for `web.sunsharetek.com` (or
transparently proxy port 80) so the inverter's own 3-second POST bodies are read locally, then
forwarded upstream unchanged. That yields the complete `pvPow`/`pv1Pow`/`pv2Pow`/`invPow`/`gridPow`/
`loadPow`/`batPow`/`soc` set every 3s with no session conflict and no dependency on the broken
`getRealTimeElectricFlow`. The one requirement is that the device must be *pushing*, i.e. a real-time
session must be kept open — which `openRealTime` does from a script (confirmed), so a small poller
(or the HA integration) can keep the stream alive while the local proxy harvests it.

**Net conclusion:** the live power-flow data, its full schema, its trigger, and its transport are
all now known. The cloud read is a dead end (Sunshare Redis bug), but the device's **plaintext-HTTP
LAN push** is a robust alternative source. Recommended architecture for live power in Home Assistant:
keep a real-time session open via `openRealTime`, and capture the device's local plaintext POST via
a DNS/proxy redirect — see README's HA section. Pure-cloud live power is not currently possible for
this device without Sunshare fixing the `getRealTimeElectricFlow` WRONGTYPE bug.

**Security note (incidental, unrelated to this endpoint):** while brute-scanning read endpoints for
a value matching the app's display, `purview/userShare/list` was observed returning device-share
records — including other account holders' email addresses — for `homeId`/`clientId`/`areaId` values,
i.e. an apparent broken-access-control/IDOR leak on Sunshare's server. Not explored further and no
data retained; noted here only so it can be reported to Sunshare (responsible disclosure) if desired.

### `POST app/sysDeviceInfo/findDeviceRealStatusByDeviceId` ⚠️ power/consumption confirmed dead
Body: `{"deviceId": <deviceId>}`

Returns a status subset of the `findById` fields (`deviceTypeDec`, `emsStatus`, `rssi`, `statusDec`,
`countryMaxPower`, `offGridState`, etc.) `power`/`consumption`/`es` are consistently `null` here —
tested with `queryOnlineStatusByDeviceIdAndOpenRealTime` called first and polling every 4s for 32s
afterward, still null throughout. **Confirmed this endpoint just doesn't carry those fields,
regardless of the "open real-time session" call or polling duration.** Use
`findDeviceListByUserId` instead — its same-named fields are numeric and confirmed live (see §3).

### `POST app/sysDeviceInfo/findDeviceListByHomeIdSimple` ✅ (empty for our home)
Body: `{"homeId": <homeId>}`. Returned `"data": []` for our home — schema/purpose otherwise unconfirmed;
possibly only populated for homes with multiple devices sharing a home grouping.

### `POST app/sysDeviceInfo/queryOnlineStatusByDeviceIdAndOpenRealTime` ✅
### `POST app/sysDeviceInfo/stopRealTimeByDeviceId` ✅
Body for both: `{"deviceId": <deviceId>}`. Both return `{"data": {"status": 0}}`. Named like a
start/stop live-telemetry-session pair, but confirmed (32s poll test, see
`findDeviceRealStatusByDeviceId` above) that "opening" a real-time session does not make that
endpoint's null fields populate. Likely just an online/offline ping pair with a misleading name, or
tied to a mechanism (push/websocket?) not reachable via polling — not useful for telemetry. Use
`findDeviceListByUserId` for live numbers instead.

### `POST app/sysDeviceInfo/getDeviceMqttOnlinOrNotOnlin` ✅
Body: `{"deviceId": <deviceId>}` → `{"data": {"status": 0}}`. Cheap online/offline check.

## 4. Home info

### `POST app/sysHome/findHomeList` ✅
Body: `{}`. Returns the account's home(s):
```json
{"data": [{"homeId": 2229, "homeName": "Sunshare", "currency": "EUR", "electrovalency": 0.36, "eleType": 1, "isShare": "0"}]}
```

## 5. EMS / power settings — read

### `POST app/sysDeviceInfo/queryMesSettingUpdate` ✅ — best read for current control settings
Body: `{"deviceId": <deviceId>}`

This is the **structured** equivalent of parsing `findById`'s `emsModePara`/`emsModeAdvan` JSON
strings yourself — use this instead:
```json
{
  "code": 200,
  "data": {
    "mesSettingUpdatePojo": {
      "emsStrategyType": 1,
      "homeLoadSource": 4,
      "meterList": null,
      "socketList": null,
      "permPower": 200,
      "powerSetPojos": [],
      "deviceId": 14926,
      "userId": null,
      "homeId": null,
      "isOnlySave": 0,
      "eleType": null
    },
    "emsModeAdvan": {
      "adVanSetType": 0,
      "socMin": 20,
      "socMax": 96,
      "countryMaxPower": 800,
      "zeroNetworkButton": 0,
      "deviceId": null,
      "isOnlySave": null
    },
    "emsWk": 1
  }
}
```
`permPower` = the output/default-load wattage setting (in Watts). `socMin`/`socMax` = battery
discharge-stop / charge-stop state-of-charge limits (%). `countryMaxPower` = grid feed-in power cap.

## 6. EMS / power settings — write

### `POST app/sysDeviceInfo/updateEmsParaById` ✅ **CONFIRMED — the wattage-control endpoint**
Body must be wrapped under key **`mesSettingUpdatePojo`** (found via pool string adjacent to
`powerSetPojos`, matching Dart class `MicroStorageEmsMesSettingUpdatePojo`):
```json
{
  "mesSettingUpdatePojo": {
    "emsStrategyType": 1,
    "permPower": 150,
    "powerSetPojos": [],
    "deviceId": 14926,
    "isOnlySave": 0
  }
}
```
Response: `{"code": 200, "msg": null, "data": true}`.

**How this was found:** sending the same fields *unwrapped* (flat, matching the `emsModePara` blob
shape 1:1) always returned a generic `{"code":500,"msg":null}` — a server-side NullPointerException
in business logic, not a validation error. This was confirmed by deliberately sending a wrong JSON
type (`isOnlySave: false` instead of `0`), which returned a *real* Jackson deserialization error
message — proving the flat shape *does* parse correctly and the 500 happens after binding, inside the
handler. The fix was the wrapper key, discovered by searching the string pool for names adjacent to
`powerSetPojos`.

**Verified end-to-end:** confirmed via live device/app testing (not just DB read-back) that this
actually changes the physical inverter's output wattage — not merely a database column.
- **Dead end for reference:** `app/sysDeviceInfo/updateById` (a generic full-entity CRUD update, see
  §8) will happily persist a changed `permPower`/`emsModePara` to the database and return success,
  but **does not** propagate to the physical device. Only `updateEmsParaById` triggers whatever
  downstream dispatch (presumably an MQTT publish to `clientId`) actually reaches the hardware.

### `POST app/sysDeviceInfo/updateEmsModeAdvanById` ⚠️ — battery SOC / grid-limit control, NOT WORKING
This is presumably the write-counterpart for `emsModeAdvan` (battery `socMin`/`socMax` charge/discharge
limits, `countryMaxPower` grid feed-in cap, `zeroNetworkButton`) — but **every schema attempted
returned a generic `{"code":500,"msg":null}`**, same NPE-style failure pattern as the unwrapped
`updateEmsParaById` attempts. Tried and failed:
```json
// Attempt 1 — wrapped as "emsModeAdvan" (matching the read-side key name)
{"emsModeAdvan": {"adVanSetType":0,"socMin":20,"socMax":96,"countryMaxPower":800,"zeroNetworkButton":0,"deviceId":14926,"isOnlySave":0}}

// Attempt 2 — wrapped as "emsAdvanStagePojo" (pool string found adjacent to "adVanSetType",
// analogous to how "mesSettingUpdatePojo" was the right wrapper for updateEmsParaById)
{"emsAdvanStagePojo": {"adVanSetType":0,"socMin":20,"socMax":96,"countryMaxPower":800,"zeroNetworkButton":0,"deviceId":14926,"isOnlySave":0}}

// Attempt 3 — same, plus deviceId/id duplicated at top level
{"deviceId": 14926, "emsAdvanStagePojo": {...}}
{"id": 14926, "emsAdvanStagePojo": {...}}

// Attempt 4 — flat/unwrapped
{"adVanSetType":0,"socMin":20,"socMax":96,"countryMaxPower":800,"zeroNetworkButton":0,"deviceId":14926,"isOnlySave":0}

// Attempt 5 — with sn added
{"emsAdvanStagePojo": {..., "sn":"020225I1903A0"}, "deviceId": 14926}
```
All six variants returned identical `{"code":500,"msg":null}` (all values sent were the account's own
*current* unchanged settings, i.e. these were meant as safe no-ops). Best next guesses if picking
this back up:
- The wrapper key might need a `Pojo`-suffixed variant not yet tried (e.g. singular field names
  inside might differ from the read-side `emsModeAdvan` blob — the read response's own `deviceId`
  and `isOnlySave` inside `emsModeAdvan` were `null`, suggesting those two keys may not belong inside
  the write DTO at all, or belong under different names).
- Possibly requires a completely different field for the device reference than `deviceId` (try `sn`
  alone, or `id`, as the *only* device-identifying field, removing `deviceId` entirely).
- Could require additional fields not present in the read response at all (e.g. `homeId`, `userId`)
  given the read-side already showed `null` for fields that logically shouldn't be null.
- Worth trying JADX/Ghidra decompilation of `libapp.so`'s Dart AOT snapshot specifically for the
  `MicroStorageEmsModeAdvan`-equivalent class fields, since string-pool guessing has hit a wall here.

### `POST app/sysDeviceInfo/getMaxGrid` ✅ — country grid-feed-in-limit lookup
Body: `{"areaId": <areaId>}` (NOT device-specific — a country/region lookup table).
```json
{"code": 200, "data": {"dictLabel": "800", "dictValue": 33}}
```
`dictLabel` = the max grid feed-in wattage for that area/country (matches `countryMaxPower`).
`dictValue` = the `areaId` echoed back. Calling with `{}`, `{"sn": ...}`, or `{"deviceId": ...}` alone
(no `areaId`) returns the generic 500.

## 7. Historical / statistics data

### `POST app/inveRealDataMinute/selectInveSummary` ✅ — lifetime totals
Body: `{"deviceId": <deviceId>}`
```json
{"data": {"totalAllPower": 19.5, "totalAllPowerUnit": "kWh", "totalAllPrice": "7.0", "totalAllPriceUnit": "USD", "accuCo2Redu": 7.0, "accuCo2ReduUnit": "kg", "dayPower": 0.0, "dayPowerUnit": "kWh"}}
```
Matches the "19.50 kWh Erzeugung / 6.84 EUR Ertrag / 7.10 kg CO₂" cards on the app's home screen.

### `POST app/inveRealDataMinute/energyPlanStatistics` ✅ — 48×30-min schedule
Body: `{"deviceId": <deviceId>}`. Returns `data.permMap`: an array of 48 half-hour slots for the day,
each `{"timeStamp": "HH:MM", "power": <watts>}` — the configured default-load-power schedule (all
`200` in our test, i.e. flat/no time-based schedule active, matching `powerSetPojos: []`).

### `POST app/sysMicoInverterRealDataMinute/realTimePower` ✅ reachable, empty for this device — deep-dived 2026-07-29
### `POST app/sysMicoInverterRealDataMinute/dataStatistics` ✅ (needs params, see below)
### `POST app/sysMicoInverterRealDataMinute/dataSummary` ✅ (returned `data: null`)
### `POST app/inveRealDataMinute/dataStatistics` ✅ (needs params, see below)

Body pattern for the two `dataStatistics` endpoints: `{"deviceId": <deviceId>, "dataType": <0-3>,
"beginTime": "YYYY-MM-DD", "endTime": "YYYY-MM-DD"}`. Without `beginTime`/`endTime`, both return
`{"code":500,"msg":"System maintenance in progress"}` (a misleading generic message — really just a
missing/unparsed date range). With date params, `dataType` 0/1/3 returned `{"code":200}` with no
`data` payload (empty result set), `dataType: 2` returned the "System maintenance" error again
(possibly an invalid enum value).

**Deep-dive on `realTimePower`, 2026-07-29 — prompted by a fair challenge: the response schema's
two PV-string fields (`pv1V`/`pv1C`, `pv2V`/`pv2C`) match this device's actual hardware (2 MPPT
trackers), so "wrong device family" was worth re-examining harder rather than assuming.**

The response wraps a `newTime` object (suspicious name, but explained below) with a rich field set
— found by triggering a deliberate type-mismatch error (same trick that found `updateEmsParaById`'s
wrapper key, §6): sending `"time": "2026-07-29 09:30:00"` (a string) returned a Jackson
deserialization error naming the real backend class:
```
JSON parse error: Cannot deserialize value of type `java.lang.Long` from String "2026-07-29 09:30:00"
... (through reference chain: com.sunshare.purview.api.domain.SysMicoInverterRealDataMinute["time"])
```
This confirms (a) the backend entity is literally called `SysMicoInverterRealDataMinute` — a
per-minute time-series table — explaining the odd `newTime` wrapper key (it's just this entity
reused/nested under a field named for its temporal-record nature, not a hidden second parameter);
(b) `time` is a real, expected field, type `Long` (epoch milliseconds, not a date string).

Full field list revealed by the null template: `pvW` (PV power, W), `gIw`/`gOw` (grid
import/output W), `lW` (load W), `pv1V`/`pv1C`/`pv2V`/`pv2C` (per-MPPT-string voltage/current),
`gPw`/`gQw` (grid active/reactive power), `gF` (grid frequency), `bLv`/`bHv` (battery low/high
voltage?), `rssi`, plus lifetime/cycle totals (`cyclePowerGeneration`, `totaPower`, `totaIncome`,
`totaCo2`, etc.) — this is exactly the granular PV/inverter telemetry this project has been looking
for, schema-wise.

**Retested with a correct epoch-millis `time` value, and every device-identifier variant that could
plausibly be "the missing correct parameter":** `deviceId`, `sn`, `clientId`, each combined with the
`time` field, plus explicit `deviceType`/`inverterType` hints (`1`, `2`, matching this account's own
`deviceType: 2`) — **every single combination returned the identical empty template**: `id: 0`
(no matching database row — `id: 0` is notably different from the *other* null fields, which read
`null`, not `0`; `id: 0` reads as "primary key of a row that doesn't exist" rather than "field not
populated"), `status: 99`, `statusDes: "off-line"`. The two sibling endpoints in the same family
were also retested with a valid date range and are consistently empty too (`dataSummary` →
`data: null`; `dataStatistics` → `{"code":200}` with no `data` key at all).

**Conclusion: this is not a missing/wrong-parameter problem — it's zero rows for this `deviceId` in
this specific backend table, confirmed across every identifier/type combination tried.** The
schema match to this device's real MPPT hardware is a fair observation and made this worth
re-testing properly (rather than re-asserting the earlier guess), but the evidence now points to a
**backend data-pipeline/business-classification split**: Sunshare's backend likely never writes
this device's telemetry into `SysMicoInverterRealDataMinute` at all — regardless of the physical
hardware being a good match, the "Micro-storage" product line (§3's `deviceType: 2`) appears to be
routed to a completely different (and, per §3/§3b's exhaustive live testing, apparently
non-populated) telemetry path. **Still untested: an actual standalone Micro-inverter-type account**,
which would conclusively prove whether this table is populated at all for anyone, or is dead
company-wide.

**➜ Superseded/confirmed by §9b:** the request DTO has since been fully enumerated (52 fields) and
the device-key question settled — `sn`/`inverterSn`/`commSn`/`packSn` are not fields of this entity
at all, only `deviceId`/`id`/`clientId`/`userId` are, and all four fail identically. §9b also
identifies the table that *does* hold this device's rows (`SysInveRealDataMinute`, which has
`power`/`batPow`/`temp1`/`permPower` columns) and proves no real-time route exists on it. Read §9b
instead of re-deriving any of this.

### `POST app/sysRevenReport/revenueReport` ⚠️
Body `{"deviceId": <deviceId>}` alone → `{"code":500,"msg":"System maintenance in progress"}` (same
missing-date-range pattern as above — untested with `beginTime`/`endTime`/`dataType` added, but
likely follows the same convention).

## 8. Generic entity CRUD — dead end for control, useful for raw reads

### `POST app/sysDeviceInfo/updateById` ✅ (works, but don't use for control)
Body: the **full** device entity (as returned by `findById`), with any field(s) changed. Returns
`{"code":200,"data":true}` and *does* persist the change to the database (verified: changing
`permPower` here is readable back via `findById` immediately after) — but **does not** propagate to
the physical device. Confirmed dead end for actual control; documented here only so nobody re-derives
this the hard way. No known legitimate use case found for this endpoint from the outside.

## 9. Misc / reference

| Endpoint | Body | Notes |
|---|---|---|
| `app/sysDeviceInfo/sysDictDataForDeviceInfo` ✅ | `{}` | Returns `{"code":200}` with no data in our test — likely needs a dict-type param, untested further. |
| `app/sysDeviceInfo/querySysBanner` ✅ | `{}` | Returns marketing banner image/link list (`linkUrl`, `pic`). Not device-related. |
| `app/sysNotice/sysDeviceRealTime` ✅ | `{"deviceId": ...}` | Returned `data: []` (empty) — presumably a fault/alert feed. |
| `app/sysDeviceInfo/queryTimeListByPersonNum` ✅ | `{"deviceId": ...}` | Returns household-size presets (`emsPersonType`, `timeAll`: array of `timePerion` strings like `"22:00-06:00"`) used for the "first EMS setup by person count" wizard. |
| `app/sysDeviceInfo/offGridPort` ✅ | `{"deviceId": ...}` | Returns `{"code":200}` with no data — likely a control/toggle action, not a read; **not tested with meaningful params** since it could change real device state (off-grid port enable). |

## 9a. Static-analysis search for a hidden "real live power" endpoint — negative result

Prompted by the confirmed-dead `power`/`consumption`/`batPow` fields (§3/§3b): if the app's own
homescreen shows numbers that (per the account holder) change over longer intervals, *some* code
path in the app must be fetching that data — so `libapp.so` was searched again, specifically for
anything not yet cataloged. Traffic capture remains off the table (confirmed dead end, see
`PHASE2_CAPTURE_GUIDE.md`), so this was string-pool analysis only — no disassembly, since Blutter
(the standard Dart-AOT decompiler) already failed against this arm32 build (`PHASE1_FINDINGS.md`).

**Ruled out:**
- **Push/notification SDKs** (Firebase/FCM, GeTui/个推, JPush, UMeng, Aliyun Cloud Push) — none
  found. The app isn't receiving live telemetry via a push side-channel.
- **IoT thing-model / device-shadow calls** (Aliyun LinkKit-style `getProperty`/`thingModel`
  naming) — none found, consistent with §3a's conclusion that the app never talks to the Aliyun
  IoT broker directly.
- **A hidden host or URL** — the full `https://` string list in the binary is exactly the three
  known hosts (`web`/`iot`/`dev.sunsharetek.com`, §1), nothing else. No separate real-time backend.
- **A dedicated "Micro-storage real data" REST path** — searched every `app/.../.../` path string
  in the binary (the complete list matches what's already documented here); nothing exists beyond
  the endpoints already cataloged in this file.

**What *was* found — a real "real-time data" concept exists for this device type in the app, but
with no separate backing endpoint:** a whole cluster of Dart source-path strings —
`package:sunshare/biz/device/models/micro_storage_real_data_entity.dart`,
`package:sunshare/generated/json/micro_storage_real_data_entity.g.dart` (generated JSON
(de)serialization), `getMicroStorageRealData()`/`stopMicroStorageRealData()` functions, and —
notably — a whole **debug page family**: `micro_storage_debug_main_page.dart`,
`micro_storage_ems_setting_page.dart`, and `micro_storage_real_time_page.dart`, all under
`package:sunshare/biz/device/page/debug/`. This confirms Sunshare's developers built (at least) a
debug view specifically for live Micro-storage telemetry. But since no distinct URL string backs
it, `getMicroStorageRealData()` almost certainly just calls one of the endpoints already documented
here (`findDeviceListByUserId` is the best guess — its response already contains exactly the short
field names — `power`, `consumption`, `es`, `ss`, `ds` — this entity would need) and deserializes
the same (confirmed dead) fields into a nicer-named Dart object. **This is a negative result that
reinforces §3/§3b's conclusion rather than opening a new lead:** there does not appear to be a
secret, separate, working live-data endpoint hiding in the app.

**A separate, unrelated family also found:** `WnRealTimePowerEntity`, `WnRealDataMainEntity`,
`WnStatisticsEntity`, etc. (`Wn` ≈ "微逆", *Wēi Nì*, Chinese for "micro-inverter") with per-phase
fields (`powerA`/`powerB`/`powerC`) — these back the standalone 3-phase **Micro-inverter** device
type (`deviceType` ≠ 2), i.e. `sysMicoInverterRealDataMinute/*` (§7). Not applicable to our
Micro-storage unit — matches the existing conclusion in §7 that those endpoints are for a different
hardware family.

**One remaining, non-technical option, if anyone wants to keep pulling this thread:** the debug
page family above suggests the app may have a hidden debug menu (common Flutter pattern: tapping a
version/build number several times). If the account holder can find and open it in the actual app,
it might display more granular values than the homescreen — but without a working traffic-capture
method, there's no way to confirm *which* call populates it, so this would only be useful as another
data point for manual cross-checking (like the homescreen number already was), not as a way to find
a new endpoint.

## 9b. Backend introspection — two new oracles, and the actual answer on live power

§9a's app-side search came up empty. This section documents a second attempt that **did** produce
hard structural answers — not from the app binary, but from the backend's own error handling.

### 9b.1 Failed first: object-pool proximity analysis ❌ (documented so nobody retries it)

The theory was that Dart AOT lays out string literals in compilation order, so a request-body key
would sit physically next to its endpoint URL in the pool (the story behind the original
`mesSettingUpdatePojo` find, §6). **Tested and disproven:** extracting all 58 900 pool strings with
byte offsets and dumping the 50 neighbours of `app/sysDeviceInfo/updateEmsParaById` — a case where
we *know* the answer — yields only unrelated Flutter internals, image assets and localization
strings. The pool is globally deduplicated/reordered, not compilation-ordered. **Proximity analysis
is useless on this snapshot; the earlier find was luck, not method.**

### 9b.2 Oracle A — Jackson type-mismatch as a DTO field/type enumerator ✅

Sending a field with a deliberately impossible JSON type (an array where any scalar is expected)
distinguishes bound from unknown fields, because Spring/Jackson is configured to *ignore* unknown
properties but *error* on type mismatches:

| Request | Response |
|---|---|
| `{"deviceId": []}` | `code:500`, `msg:"JSON parse error: Cannot deserialize value of type `java.lang.Long` … through reference chain: com.sunshare.purview.api.domain.<Entity>[\"deviceId\"]"` |
| `{"zzzNotAFieldXyz": []}` | no error at all |

This yields, for **any** endpoint: the bound backend entity's fully-qualified class name, its exact
field names, and each field's Java type. It works on every route tested and needs nothing but HTTP.

### 9b.3 Oracle B — 404 vs. 200/500 as a route-existence probe ✅

A non-existent route returns a bare **HTTP 404** with no JSON envelope, while every real route
returns HTTP 200 (with `code` 200 or 500 inside). So undocumented endpoint names can be brute-forced
by name. Validated against a known-good and two known-bogus paths.

Also settled with Oracle B: **`"System maintenance in progress"` is not a maintenance flag** — it's
this backend's generic uncaught-exception message. Proven by `sysRevenReport/revenueReport`, which
returns it with `{"deviceId"}` alone but a clean `code:200` once `dataType`+`beginTime`+`endTime` are
added. Treat it as "handler threw", usually a missing/unusable parameter.

### 9b.4 Result: `realTimePower` cannot serve this device, and here is the proof

Enumerating `sysMicoInverterRealDataMinute/realTimePower`'s request DTO gave **52 bound fields on
`com.sunshare.purview.api.domain.SysMicoInverterRealDataMinute`** — the entire response schema is
also accepted as *input* (the route binds request and response to the same entity). Critically, of
every plausible device key, **only `deviceId` (Long), `id` (long), `clientId` (String) and
`userId` (Long) are bound** — `sn`, `inverterSn`, `commSn`, `packSn` and `homeId` are **not fields
of this entity at all**. All four bindable keys were tried, alone and combined, with a valid
epoch-millis `time` and with `deviceType`/`inverterType` hints: every single one returns the same
empty template (`id: 0`, `status: 99`, `statusDes: "off-line"`).

**So the earlier "wrong device family" conclusion (§7) was right, but for a better reason than the
MPPT-count argument suggested** — and the fair objection that this device really does have 2 MPPT
trackers is answered: the schema fits the hardware, but the *table* doesn't contain this device.
This device's per-minute rows live in a **different table**:

| Route family | Bound entity | Has our device's data? |
|---|---|---|
| `app/sysMicoInverterRealDataMinute/*` | `SysMicoInverterRealDataMinute` | ❌ no rows, any key |
| `app/inveRealDataMinute/*` | **`SysInveRealDataMinute`** | ✅ yes — `selectInveSummary` returns real, growing totals |

And `SysInveRealDataMinute`'s own DTO enumeration shows it has exactly the columns this project
wanted: **`power` (Double), `batPow` (int), `temp1` (int), `permPower` (int), `totalPower` (double),
`bhs` (int), `pe` (int)**, plus `sn`/`packSn`/`homeId` (which the Mico entity lacks).

**But there is no real-time read route on that family.** Oracle B was used to brute-force 22
plausible names (`realTimePower`, `realTimeData`, `selectRealTime`, `latestData`, `selectMinuteData`,
…) under `app/inveRealDataMinute/` — **all 404**. That matches the app binary's own complete path
inventory (§9a), which contains exactly three `inveRealDataMinute` routes: `selectInveSummary`,
`energyPlanStatistics`, `dataStatistics`. Of those, `dataStatistics` throws the generic exception for
**every** parameter combination tried (all `dataType` 0–7, six date formats, `time`/`timeValue`
sweeps, `sn`/`homeId`/pagination variants) while its sibling routes accept the same shapes — so the
per-minute history is not reachable through it either, at least not from this account.

### 9b.5 Why `power`/`consumption` are structurally always 0 — best explanation yet

`findDeviceListByUserId` and `findDeviceRealStatusByDeviceId` do **not** bind `SysDeviceInfo` like
the other device routes — they bind **`com.sunshare.purview.api.domain.HomeLoadPower`**. Enumerating
it is revealing:

- It has a bound `homeLoadPower` (double) field that has **never appeared in any response** we've
  captured (Jackson omits nulls) — plus `homeId`, `userId`, `timeStamp`, likewise never seen.
- **`power` and `consumption` are *not* bindable fields of it** — yet they appear in its responses.
  A property that serializes but won't deserialize is a **getter-only/derived value**, i.e. computed
  by the service layer rather than read from this entity's table.

The entity being named *HomeLoadPower* — combined with `queryMesSettingUpdate`'s
`homeLoadSource: 4`, `meterList: null`, `socketList: null` (§5) and this device having
`meterSn`/`socketSn`/`meterStatus`/`meterHave` all `null` (§3's `findById`) — points to a concrete
conclusion: **`power`/`consumption` are home-load figures sourced from a smart meter or smart socket
accessory, and this installation has neither, so they are structurally 0 rather than broken.**
That is consistent with every observation to date, including the ~200 W and ~40 W tests, and it
means no amount of parameter-guessing will make them report inverter output.

`batPow` reading 0 during the ~40 W solar test is also physically consistent under this reading: the
battery sat at 19 % SOC against a `socMin` of 20 %, i.e. below its discharge cutoff and not
charging much, so near-zero *battery* power is plausibly correct — `batPow` may well be a genuine
live field that simply had nothing to report. Worth one more check during a clear charge cycle.

### 9b.6 Bonus: `dayPower` is confirmed working ✅

`selectInveSummary` now returns `dayPower: 0.2` (kWh today) and `totalAllPower` grew 19.5 → 23.6 kWh
across the session — this endpoint *does* track real production, just as accumulated energy rather
than instantaneous power. The Home Assistant integration already exposes both
(`today_energy`/`lifetime_energy`), so **daily/lifetime yield is properly covered**; only
instantaneous wattage is missing.

### 9b.7 What is left

The app displays an instantaneous wattage that no enumerated REST field reproduces. Given §9a
(no push SDK, no MQTT client, no hidden host, no extra route in the binary) and §9b (no bound field
that could carry it, no reachable per-minute route), the remaining possibilities are:
1. The app derives it client-side — e.g. from `permPower` plus `energyPlanStatistics`'s 48-slot
   `permMap`, both of which track the *setting*, and the account holder did confirm the app's figure
   stays fixed over short windows.
2. It comes from a route bound to a field whose name is not among the ~90 candidates probed. A full
   dictionary sweep of `app/<module>/<name>` using Oracle B could close this off definitively — the
   module list is already known from the binary.
3. A real-time cache path that only fills under conditions not reproducible from a script.

The cleanest remaining experiment needs no reverse engineering at all: poll continuously for a few
minutes **while watching the app side by side**, and check whether the app's number moves at all
during a period when our polls are flat. If it does not move, option 1 is proven and the question is
closed.

## 10. Found in binary, never called — ❔ untested

These path strings exist in the app's Dart snapshot but were not exercised live (either not relevant
to this task, or risky to call blind against a real device without a stated need). Schema is
unknown/guessable at best from the field name alone.

**Device management (likely risky/destructive — do not call without a clear reason and explicit
confirmation):**
- `app/sysDeviceInfo/deviceSetting` — body seen in pool alongside fields `isOnlySave`, `controlType`;
  UI text nearby suggests this is the **device power on/off toggle**.
- `app/sysDeviceInfo/deviceSocketSetting` — smart-socket/"flex socket" configuration (energy-saving
  standby policy per EU ErP directive, per adjacent UI strings).
- `app/sysDeviceInfo/deleteById`, `deleteBySn` — device un-binding/removal.
- `app/sysDeviceInfo/updateBySn`, `updateKindBySn` — alternate update paths keyed by serial instead
  of id.
- `app/sysDeviceInfo/addBlueToothData`, `addWifiName` — BLE/Wi-Fi provisioning-related (see the
  earlier BLE reverse-engineering phase — these are the REST-side counterparts of that flow).
- `app/sysDeviceInfo/verifyDeviceUniquenessBySn119` — provisioning pre-check.
- `app/sysDeviceInfo/systemDiagramUpdate` — unclear purpose.
- `app/sysDeviceInfo/updateFirstEmsSetBySn`, `updateFristEmsSetByDeviceId`,
  `fristEmsSetByPersonNum` (typo "frist" is in the app itself) — first-time-setup EMS wizard writes.
- `app/sysDeviceMeter/deleteByDeviceId`, `app/sysDeviceSocket/deleteByDeviceId` — accessory
  (smart-meter/smart-plug) removal.
- `app/sysOtaVersion/deviceOtaUpdate`, `selectDeviceCurVerAndUpVer`, `selectDeviceOtaUpdatePro`,
  `updateFirstConfirById`, `updateFirstSuccessConfir` — firmware OTA update flow. **Do not experiment
  with these against a live device.**

**Home/user/sharing management:**
- `app/sysHome/add`, `deleteById`, `updateById` — home CRUD.
- `purview/userShare/addSimple`, `deleteById`, `list` — device-sharing-with-other-accounts feature.
- `purview/user/edit`, `updatePassword`, `deleteById`, `getAttaBaseStr`, `uploadLocal` — account
  profile management.
- `purview/dict/data/type`, `purview/user/queryAreaOut`, `purview/user/getNoticeNotDis`,
  `noticeNotDis` — misc dictionary/notification-preferences lookups.

**Auth (beyond login, untested):**
- `auth/logout`, `auth/register`, `auth/resetPassword`, `auth/resetSendEmail`, `auth/regisSendEmail`,
  `auth/querySysLanguage`.

**Notifications/feedback:**
- `app/sysNotice/batchInsertForNotice`, `batchInsertForDeviceonFaultRead`,
  `sysDeviceHightLevelPushApp`, `sysNoticePushApp`, `selectIsOrNotLastNewMessage`.
- `app/sysHelpFeedblack/add`, `sysDictDataForHelpFeedblack`, `uploadFeedblackAttachBatch` (typo
  "Feedblack" is in the app itself).

## 11. Tooling

- `sunshare_api.py` — Python client with `login`/`call`/`raw` subcommands, credential loading from a
  local untracked `~/.sunshare_credentials.json` (never logged/printed), token cached to
  `.sunshare_token.json`.
- `.venv/` — Python virtualenv with `requests` installed; run via `.venv/bin/python sunshare_api.py ...`.
- Given the single-session constraint (§2), prefer writing one-off scripts that log in fresh
  immediately before the calls they need, rather than relying on the cached token file across a
  session where the mobile app might also be in use.
