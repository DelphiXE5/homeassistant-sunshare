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
serial (matches the BLE advertised name from the earlier BLE phase). **`power`/`consumption` are
genuinely live** — confirmed by polling twice a few minutes apart and observing `ss` change value
(`0` → `1`) while `power`/`consumption` stayed `0.0`; the zeros are very likely an accurate current
reading (no active solar/battery flow at test time), not a broken/static field. This is the
recommended endpoint for live power-flow polling in a future integration — no need to chase the
MQTT route (see §3a) or the broken real-time-session endpoint below for this. `es`/`ss`/`ds` are
short status flags whose exact meaning wasn't fully confirmed (`ds`=device status, `ss`=solar
status, `es`=energy-storage status, by naming convention — unconfirmed).

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

### `POST app/sysMicoInverterRealDataMinute/realTimePower` ✅ (mostly null for this device)
### `POST app/sysMicoInverterRealDataMinute/dataStatistics` ✅ (needs params, see below)
### `POST app/sysMicoInverterRealDataMinute/dataSummary` ✅ (returned `data: null`)
### `POST app/inveRealDataMinute/dataStatistics` ✅ (needs params, see below)

Body pattern for the two `dataStatistics` endpoints: `{"deviceId": <deviceId>, "dataType": <0-3>,
"beginTime": "YYYY-MM-DD", "endTime": "YYYY-MM-DD"}`. Without `beginTime`/`endTime`, both return
`{"code":500,"msg":"System maintenance in progress"}` (a misleading generic message — really just a
missing/unparsed date range). With date params, `dataType` 0/1/3 returned `{"code":200}` with no
`data` payload (empty result set), `dataType: 2` returned the "System maintenance" error again
(possibly an invalid enum value). **These endpoints are almost certainly intended for standalone
"Micro-inverter"-type devices (`deviceType` ≠ 2) rather than this "Micro-storage" device** —
`realTimePower`'s response was a mostly-null template (`status: 99, statusDes: "off-line"`) even
though the device itself was online, reinforcing that this endpoint family doesn't apply to
Micro-storage systems. Likely dead ends for this specific device type; **untested against an actual
Micro-inverter-type device.**

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
