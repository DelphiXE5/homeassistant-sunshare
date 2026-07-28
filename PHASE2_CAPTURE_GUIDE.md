# Phase 2 — Bluetooth HCI capture guide

Goal: get the real on-the-wire BLE bytes for a few known actions, so we can lock down the service/
characteristic UUIDs, the frame format, and the crypto (known-plaintext).

## A. Enable HCI snoop logging on the Android phone
1. Settings → About phone → tap **Build number** 7× to unlock Developer options.
2. Settings → System → **Developer options** → enable **"Enable Bluetooth HCI snoop log"**
   (some phones: value `Enabled` / `Filtered`; pick **Enabled**).
3. Toggle Bluetooth **off then on** (some OEMs only start the log after a BT restart).

## B. Reproduce specific, labelled actions in the Sunshare app
Do these in order and **write down the wall-clock time + what the screen showed** for each — we correlate
timestamps to packets. Keep it minimal so the log is easy to read.

1. Open the app, connect to the inverter over Bluetooth, land on the device **status/home** page.
   Note the live values shown (e.g. current power in W, battery %, phase powers).
2. Sit on the status page ~15 s (captures the periodic status poll/notify).
3. Change **one** setting we can identify, e.g. toggle the **EMS / energy mode**, or change the
   **default load power** / discharge-cutoff %. Note old value → new value.
4. (Optional) Toggle device **on/off** once.
5. Disconnect / close.

## C. Pull the log
Older Android logs to `/sdcard/btsnoop_hci.log`; newer Android (11+) logs under
`/data/misc/bluetooth/logs/btsnoop_hci.log` and is best retrieved via a **bug report**:
```
# Simple case (older phones / if readable):
adb pull /sdcard/btsnoop_hci.log

# Robust case (Android 11+): generate a bug report zip, snoop log is inside it
adb bugreport btreport      # produces btreport.zip
#   unzip and look under FS/data/misc/bluetooth/logs/ for btsnoop_hci*.log
```
If neither path exists, tell me your Android version and OEM and I'll give the exact location.

## D. Hand it back
Drop `btsnoop_hci.log` (or the `btreport.zip`) into this folder and tell me your action timeline
(the notes from step B). I'll parse it with tshark/a Python HCI parser and correlate:
- ATT service/characteristic discovery → the real **UUIDs**
- `Write Command/Request` + `Handle Value Notification` payloads → the **frame format**
- known plaintext (the value you changed) → confirm **cipher/mode/key/IV** against the 3 candidate keys

## Notes
- The log contains your BLE traffic only; no account credentials needed. If anything sensitive appears
  I'll flag it rather than echo it.
- If the device requires BLE **bonding/pairing** (PIN/passkey), we'll see it in the HCI log — that changes
  the Python (`bleak`) side, so I'll flag it early.
