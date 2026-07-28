#!/usr/bin/env python3
"""
Sunshare BLE explorer / status reader (Phase 2+3, live against the device).

We act as the BLE client instead of capturing the phone. It:
  1. scans for the device by name,
  2. connects and prints the full GATT table,
  3. subscribes to every notify characteristic (esp. c303 = controlChar),
  4. for each frame: prints raw hex + tries to decrypt (AES-128, key "hiflying12345678",
     CBC/CTR/ECB, zero-IV & key-IV, at several header offsets) + a CRC8 check.

Run the phone app CLOSED (BLE peripherals usually allow one connection).

Setup:
    python3 -m pip install bleak pycryptodome
    python3 sunshare_ble.py            # scan + connect + listen
    python3 sunshare_ble.py --scan     # just list nearby devices
macOS will prompt once to allow Bluetooth for your terminal (not sudo).
"""
import asyncio, argparse, datetime, sys
from bleak import BleakScanner, BleakClient
from Crypto.Cipher import AES

DEVICE_NAME = "SS-2-020225I1903A0"
KEY = b"hiflying12345678"                 # Phase-1 candidate (Hi-Flying default)
CONTROL = "c303"                          # controlChar; 0000c303-0000-1000-8000-00805f9b34fb
short = lambda u: str(u).lower().replace("0000", "", 1)[:4] if str(u).lower().startswith("0000") else str(u).lower()

def crc8(data, poly=0x07, init=0x00):
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc

def printable(b):
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)

def try_decrypt(payload):
    """Try AES conventions at a few header offsets; return (label, plaintext) list."""
    results = []
    ivs = {"zeroIV": b"\x00" * 16, "keyIV": KEY}
    # try trimming 0..4 header bytes and 0..2 trailing (CRC) bytes, keep 16-aligned
    for h in range(0, 5):
        for t in range(0, 3):
            body = payload[h: len(payload) - t if t else None]
            n = (len(body) // 16) * 16
            if n == 0:
                continue
            body = body[:n]
            for mode, mk in [
                ("CBC", lambda iv: AES.new(KEY, AES.MODE_CBC, iv)),
                ("CTR", lambda iv: AES.new(KEY, AES.MODE_CTR, nonce=b"", initial_value=iv)),
                ("ECB", lambda iv: AES.new(KEY, AES.MODE_ECB)),
            ]:
                for ivn, iv in ivs.items():
                    if mode == "ECB" and ivn != "zeroIV":
                        continue
                    try:
                        pt = mk(iv).decrypt(body)
                    except Exception:
                        continue
                    # heuristic: keep results that look like text/structured (many printable or PKCS7-ish)
                    pr = printable(pt)
                    dots = pr.count(".")
                    if dots < len(pr) * 0.5:      # >50% printable
                        results.append((f"AES-{mode}/{ivn} h={h} t={t}", pt, pr))
    return results

def dump(direction, uuid, data):
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\n[{ts}] {direction} {short(uuid)} len={len(data)}")
    print(f"  raw : {data.hex()}")
    if len(data) >= 2:
        print(f"  crc8? crc8(all-but-last)={crc8(data[:-1]):#04x} last={data[-1]:#04x}"
              f"  | crc8(all)={crc8(data):#04x}")
    hits = try_decrypt(data)
    if not hits:
        print("  (no >50%-printable decryption with hiflying key — mode/IV/offset differs, or not this key)")
    for label, pt, pr in hits[:6]:
        print(f"  {label}: {pt.hex()}  | {pr}")

async def do_scan():
    print("Scanning 8s ...")
    devs = await BleakScanner.discover(timeout=8.0)
    for d in sorted(devs, key=lambda x: (x.name or "~")):
        print(f"  {d.address}  rssi={getattr(d,'rssi','?'):>4}  {d.name!r}")

async def main(args):
    if args.scan:
        await do_scan()
        return

    print(f"Looking for {DEVICE_NAME!r} ...")
    dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=15.0)
    if not dev:
        print("Not found. Is the phone app closed and the device advertising? Try --scan.")
        return
    print(f"Found {dev.address}. Connecting ...")

    async with BleakClient(dev) as client:
        print(f"Connected: {client.is_connected}\n=== GATT table ===")
        notify_chars, read_chars = [], []
        control_char = None
        for svc in client.services:
            print(f"[service] {short(svc.uuid)}  ({svc.uuid})")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                descs = ",".join(short(d.uuid) for d in ch.descriptors) or "-"
                print(f"   [char] {short(ch.uuid)}  {props}  desc=[{descs}]  ({ch.uuid})")
                if "notify" in ch.properties or "indicate" in ch.properties:
                    notify_chars.append(ch)
                if "read" in ch.properties:
                    read_chars.append(ch)
                if CONTROL in str(ch.uuid).lower():
                    control_char = ch

        def cb(sender, data):
            dump("RX(notify)", getattr(sender, "uuid", sender), bytes(data))

        # 1) Read every readable characteristic — forces descriptor discovery AND may
        #    hand us status data outright (c304 is read-only; c301/c305/c306 readable).
        print("\n=== reading readable characteristics ===")
        for ch in read_chars:
            try:
                val = await client.read_gatt_char(ch)
                dump("READ", ch.uuid, bytes(val))
            except Exception as e:
                print(f"  read {short(ch.uuid)} failed: {e}")

        # 2) Subscribe one at a time, with a small delay (CoreBluetooth needs this).
        print(f"\n=== subscribing (control char {'FOUND' if control_char else 'NOT found'}: {CONTROL}) ===")
        subscribed = []
        for ch in notify_chars:
            try:
                await client.start_notify(ch, cb)
                subscribed.append(short(ch.uuid))
                print(f"  subscribed {short(ch.uuid)}")
            except Exception as e:
                print(f"  subscribe {short(ch.uuid)} failed: {str(e).splitlines()[0]}")
            await asyncio.sleep(0.4)
        print(f"Subscribed: {subscribed or 'NONE'}. Listening {args.listen:.0f}s...\n")

        # Optional: send a probe write to nudge the device to stream status.
        # Uncomment and edit once we know the request frame:
        # if control_char and "write" in control_char.properties or "write-without-response" in control_char.properties:
        #     await client.write_gatt_char(control_char, bytes.fromhex("...."), response=False)

        try:
            await asyncio.sleep(args.listen)
        except asyncio.CancelledError:
            pass
        print("\nDone listening.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="just list nearby BLE devices")
    ap.add_argument("--listen", type=float, default=60.0, help="seconds to listen (default 60)")
    asyncio.run(main(ap.parse_args()))
