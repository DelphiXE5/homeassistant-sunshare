# Phase 1 — Static analysis findings (Sunshare BLE)

Binary: `libapp.so` — ELF 32-bit ARM (armeabi-v7a), Flutter AOT snapshot, stripped, 15.45 MB.
Analysis method: ELF section parsing + Dart snapshot string/object-pool string extraction
(no decompiler; see "Tooling verdict" for why).

Confidence legend: **[C]** confirmed from binary · **[I]** inferred, unverified · **[?]** ambiguous.

## 1. Binary / snapshot identity **[C]**
| Item | Value |
|---|---|
| Arch | ARM 32-bit LE, EABI5 |
| Dart snapshot version hash | `97ff04a728735e6b6b098bdf983faaba` |
| Features | `product ... dedup_instructions arm android no-compressed-pointers` |
| Isolate snapshot **data** (string/object pool) | file off `0x74c0`, size `0x704bb8` (~7.3 MB) |
| Isolate snapshot **instructions** (`.text`) | vaddr `0x716cc0`, size `0x7a19b0` |

Hash not present in public hash→version tables (they end ~Flutter 3.0.1 / 2022), so this is a
**newer Flutter (Dart 3.x)**. Section `addr == file offset` (identity mapped) — handy for later Ghidra work.

## 2. Code inventory — the BLE path is real and present **[C]**
All the source paths from the brief are in the snapshot string pool:
`ble/ble_manager.dart`, `ble/ble_connect_manager.dart`, `ble/ble_data_handler.dart`,
`ble/ble_data_handler_4nep.dart`, `ble/ext/ble_device_response_frames.dart` (class `BleDeviceResponseFrames`),
`ble/ext/aes_util_4nep.dart`, `ble/ext/tea_encryptor.dart`, `control/control_ble_mode.dart`,
`control/control_mqtt_mode.dart`, `control/device_control_factory.dart`, `control/interface/device_control.dart`.
BLE plugin = `flutter_blue_plus` (`+_android`, `+_platform_interface`) — uses `writeCharacteristic`,
`setNotifyValue`, `BmWriteCharacteristicRequest`, `BmSetNotifyValueRequest`.

## 3. Crypto **[C except where noted]** — UPDATED with pool info
- Stack = **`encrypt` package over `pointycastle`**. `AesUtil4Nep` sits next to `ParametersWithIV`
  ⇒ **IV-based mode (CBC or CTR), not ECB**. The `encrypt` pkg default is CTR(SIC); app may force CBC.
- App error literal **`"Key must be 16 bytes (128 bits), current: "`** ⇒ **AES-128**. **[C]**
- **CORRECTION (from pool context):** the three 32-hex constants I flagged in the first pass are NOT keys —
  the pool shows them interleaved with `secp128r1`/`secp128r2` labels and they ARE those curve params:
  `e87579c1…` = secp128r1 `b`; `d6031998…` = secp128r2 `a`; `5eeefca3…` = secp128r2 `b`. They only looked
  non-curve because they're 128-bit curves (16 bytes, same size as an AES key). **Dead hypothesis.**
- **Actual key literal found: `hiflying12345678`** (pool idx 13761) — 16 ASCII bytes = AES-128 key.
  "Hi-Flying" is the Wi-Fi/IoT module vendor; this is the HF module's default/app-configured AES key. **[C
  that the string exists; [I] that it's the control key]**
- **No handshake:** pool has no pairing/nonce/challenge/sessionKey/deriveKey vocabulary ⇒ the BLE AES key is
  **static, not exchanged**. `hiflying12345678` is the only plaintext 16-byte key literal in the entire pool
  ⇒ prime candidate for BOTH provisioning and control crypto. **[I]**
- **CRC8:** there is a dedicated `CRC8` class in `ble_data_handler_4nep.dart` ⇒ frames carry a **CRC8**
  checksum. **[C]**
- Separate `AesEncryptionService` (`util/sunshare/aes_util.dart`) + `flutter_secure_storage`
  (`AES_CBC_PKCS7Padding`, `RSA_ECB_PKCS1Padding`) handle REST/local-auth — distinct from the BLE path.
- TEA (`tea_encryptor.dart` / class `TEA`) present as an alternate cipher for another device gen; delta not a
  raw constant (Dart ints are tagged) so its absence proves nothing. **[I]**

## 4. BLE UUIDs — 16-bit short UUIDs, recovered from pool **[C]**
No 128-bit custom UUID exists; `GUID must be 16, 32, or 128 bit` + short values confirm **16-bit UUIDs**
(expanded via BT base `0000XXXX-0000-1000-8000-00805f9b34fb`). Characteristic map from pool (value → role):
| Short UUID | Role | Path |
|---|---|---|
| **C303** | **`controlChar`** — device control (the target) | 4NEP control |
| C301 | `netConfigChar` | Wi-Fi provisioning |
| C305 | `wifiListChar` | Wi-Fi provisioning |
| FEC7 / FEC8 / FEE7 / FED4 | provisioning-related | Wi-Fi provisioning |
| 1801 / 2A05 / 00002902 | standard GATT (GATT service / Service-Changed / CCCD) | — |

⇒ **Control target = characteristic `0000c303-0000-1000-8000-00805f9b34fb`** (write + notify).
Method `findCharacteristicBySN4NEP` locates it after service discovery (matched via device serial); no
hardcoded service UUID string ⇒ Python client should discover-all and select the char by UUID `c303`.
Near C303 in the pool: `protocolType`, `ble_receive_device_state_change`, EMS params `homeLoad`/`hls`/`rlp`.

## 5. Data model / what to look for on the wire **[C]**
Vocabulary confirms the fields we'll want to decode: `emsMode`, `Phase A/B/C Power`, default/load power,
charge/discharge, battery-level threshold ("discharge stops below this value"), grid import/export
(`Positive power: drawing from the grid` / `Negative power: surplus ... feeds into the grid`),
Boost-Charging / Energy-Saving / storm modes, `SN:` (serial). Home page classes:
`micro_storage_home2_page.dart`, `micro_inverter_home_chart*`. Note `inverter/power`, `inverter/daycount`
strings (likely REST endpoints, not BLE).

## Tooling verdict
- **Blutter (and all forks: termux/nix/docker):** arm64-only. The limitation is architectural — its
  object-pool/stack tracer is written for AArch64 register+instruction conventions — so it will **not**
  process this `armeabi-v7a` binary. Not worth attempting.
- **Ghidra ARM32:** would decompile, but Dart AOT accesses all constants via a pool-pointer register with
  no symbols; reading it by hand is slow. Deferred: a JEB `dart_aot_snapshots` name/offset map (which you
  offered) would make it worthwhile, but Phase-2 capture is cheaper and more certain for the immediate goal.

## Testable protocol hypothesis (to confirm in Phase 2)
- Connect BLE → discover services → use characteristic **`c303`** (write commands + subscribe notifications).
- Payload = **AES-128** (CBC or CTR), key **`hiflying12345678`** (ASCII), + a **CRC8** somewhere in the frame.
- Frame byte layout (header / length / command-id / payload / CRC8 offsets) is the one thing NOT recoverable
  from the strings-only pool — it needs the capture (or the raw disassembly, which these reports don't include).

## Recommendation → go to Phase 2 now
Remaining unknowns — exact frame byte layout, AES mode + IV convention, and confirming the key — all fall out
of a Bluetooth HCI snoop capture on characteristic **c303** (known-plaintext). Cheaper and more certain than
hand-decompiling stripped ARM32. See `PHASE2_CAPTURE_GUIDE.md`. A ready-to-run decrypt/correlate script is in
`analyze_capture.py`.
