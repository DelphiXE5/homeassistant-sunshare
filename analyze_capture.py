#!/usr/bin/env python3
"""
Phase-2 helper: parse a Bluetooth HCI snoop log, pull the ATT writes/notifications
on the Sunshare control characteristic (c303), and try to decrypt them with the
static hypothesis from Phase 1 (AES-128, key "hiflying12345678", CBC or CTR).

Usage:
    pip install pyshark pycryptodome     # pyshark needs tshark installed (brew install wireshark)
    python3 analyze_capture.py btsnoop_hci.log

If pyshark/tshark is unavailable, run tshark manually and feed the hex in via
--hexfile (one "handle,hexbytes" per line); see parse notes at bottom.
"""
import sys, argparse, binascii
from Crypto.Cipher import AES  # pycryptodome

KEY = b"hiflying12345678"          # Phase-1 candidate (Hi-Flying module default)
CONTROL_UUID_SUFFIX = "c303"       # 0000c303-0000-1000-8000-00805f9b34fb

def crc8(data, poly=0x07, init=0x00):
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if (crc & 0x80) else (crc << 1) & 0xFF
    return crc

def try_decrypt(payload: bytes):
    """Try the handful of AES conventions worth testing against known plaintext."""
    out = []
    ivs = {"zero": b"\x00"*16, "key": KEY}
    for mode_name, factory in [
        ("CBC", lambda iv: AES.new(KEY, AES.MODE_CBC, iv)),
        ("CTR", lambda iv: AES.new(KEY, AES.MODE_CTR, nonce=b"", initial_value=iv)),
        ("ECB", lambda iv: AES.new(KEY, AES.MODE_ECB)),
    ]:
        for iv_name, iv in ivs.items():
            if mode_name == "ECB" and iv_name != "zero":
                continue
            body = payload[:len(payload)//16*16]
            if not body:
                continue
            try:
                pt = factory(iv).decrypt(body)
                out.append((f"AES-{mode_name}/iv={iv_name}", pt))
            except Exception as e:
                out.append((f"AES-{mode_name}/iv={iv_name}", f"<err {e}>".encode()))
    return out

def show(direction, handle, data):
    print(f"\n[{direction}] handle={handle} len={len(data)}")
    print("  raw :", data.hex())
    # CRC8 sanity: does last byte == crc8 of the rest? (test a couple conventions)
    if len(data) >= 2:
        print(f"  crc8(all-but-last)={crc8(data[:-1]):#04x}  last-byte={data[-1]:#04x}")
    for label, pt in try_decrypt(data):
        printable = "".join(chr(c) if 32 <= c < 127 else "." for c in pt)
        print(f"  {label}: {pt.hex()}  | {printable}")

def via_pyshark(path):
    import pyshark
    # btatt.value carries the characteristic payload; filter to our UUID handle set.
    cap = pyshark.FileCapture(path, display_filter="btatt.value")
    for pkt in cap:
        try:
            att = pkt.btatt
            val = att.value.replace(":", "")
            data = binascii.unhexlify(val)
            uuid = getattr(att, "uuid128", "") or getattr(att, "uuid16", "")
            opcode = getattr(att, "opcode", "?")
            handle = getattr(att, "handle", "?")
            direction = "TX(write)" if "12" in str(opcode) or "52" in str(opcode) else "RX(notify)"
            if CONTROL_UUID_SUFFIX in str(uuid).lower() or True:  # show all, tag matches
                tag = "  <-- c303" if CONTROL_UUID_SUFFIX in str(uuid).lower() else ""
                print(f"=== uuid={uuid} opcode={opcode}{tag}", end="")
                show(direction, handle, data)
        except AttributeError:
            continue
    cap.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("logfile", nargs="?", help="btsnoop_hci.log")
    ap.add_argument("--hexfile", help="fallback: lines of 'label,hexbytes'")
    args = ap.parse_args()
    if args.hexfile:
        for line in open(args.hexfile):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            label, hx = line.split(",", 1)
            show(label, "?", binascii.unhexlify(hx.strip()))
    elif args.logfile:
        via_pyshark(args.logfile)
    else:
        ap.print_help()

# --- Manual tshark fallback (no pyshark) ---
# tshark -r btsnoop_hci.log -Y "btatt.value" \
#        -T fields -e btatt.handle -e btatt.uuid128 -e btatt.opcode -e btatt.value
# then reformat the c303 rows into 'label,hex' lines and use --hexfile.
