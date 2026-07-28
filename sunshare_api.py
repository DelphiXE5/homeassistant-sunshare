#!/usr/bin/env python3
"""
Black-box prober for the Sunshare (Sunsharetek) cloud REST API.

Credentials are read from a local JSON file that YOU create yourself
(never pasted into chat, never printed by this script). Default path:
    ~/.sunshare_credentials.json
Format:
    {"username": "your-email-or-account", "password": "your-password"}

Usage:
    python3 sunshare_api.py login              # try to log in, print token status
    python3 sunshare_api.py call <path> [json] # authenticated call to app/<path>
    python3 sunshare_api.py raw <method> <path> [json]  # call with any HTTP method

Examples:
    python3 sunshare_api.py login
    python3 sunshare_api.py call sysDeviceInfo/findDeviceListByUserId '{}'
    python3 sunshare_api.py call sysDeviceInfo/findDeviceRealStatusByDeviceId '{"deviceId": 123}'
"""
import json
import os
import sys
from pathlib import Path

import requests

CRED_PATH = Path(os.environ.get("SUNSHARE_CRED_FILE", "~/.sunshare_credentials.json")).expanduser()
TOKEN_CACHE = Path(__file__).parent / ".sunshare_token.json"

# Candidate base hosts, in the order we found them (web = production per the live capture)
BASE_HOSTS = [
    "https://web.sunsharetek.com/app/",
    "https://iot.sunsharetek.com/app/",
    "https://dev.sunsharetek.com/app/",
]

COMMON_HEADERS = {
    "Content-Type": "application/json",
    "language": "en",
    "localeName": "en",
}


def load_credentials():
    if not CRED_PATH.exists():
        print(f"[!] Credentials file not found: {CRED_PATH}")
        print("    Create it yourself with: {\"username\": \"...\", \"password\": \"...\"}")
        sys.exit(1)
    with open(CRED_PATH) as f:
        creds = json.load(f)
    if "username" not in creds or "password" not in creds:
        print("[!] Credentials file must contain 'username' and 'password' keys.")
        sys.exit(1)
    return creds


def save_token(base_host, token, raw_response):
    TOKEN_CACHE.write_text(json.dumps({"base_host": base_host, "token": token, "raw": raw_response}, indent=2))
    os.chmod(TOKEN_CACHE, 0o600)


def load_token():
    if not TOKEN_CACHE.exists():
        print(f"[!] No cached token at {TOKEN_CACHE}. Run 'login' first.")
        sys.exit(1)
    return json.loads(TOKEN_CACHE.read_text())


def try_login():
    creds = load_credentials()
    username = creds["username"]
    password = creds["password"]

    # Field-name candidates to try for the login body, based on pool strings
    # (userAccount/username/loginEmail all appeared near login-related fields).
    field_candidates = [
        {"username": username, "password": password},
        {"userAccount": username, "password": password},
        {"loginEmail": username, "password": password},
        {"email": username, "password": password},
    ]

    for base_host in BASE_HOSTS:
        url = base_host + "auth/login"
        print(f"\n=== Trying {url} ===")
        for body in field_candidates:
            field_used = list(body.keys())[0]
            try:
                resp = requests.post(url, json=body, headers=COMMON_HEADERS, timeout=10)
            except requests.RequestException as e:
                print(f"  [{field_used}] request failed: {e}")
                continue

            print(f"  [{field_used}] -> HTTP {resp.status_code}")
            try:
                data = resp.json()
            except ValueError:
                print(f"    (non-JSON body, {len(resp.content)} bytes)")
                continue

            # Print response but redact anything that looks like it echoes the password
            redacted = redact(data)
            print(f"    body: {json.dumps(redacted, ensure_ascii=False)[:1500]}")

            token = extract_token(data)
            if token:
                print(f"\n[+] Got token via {base_host} with field '{field_used}'")
                save_token(base_host, token, redacted)
                return

    print("\n[!] No login attempt returned a usable token. Inspect the response bodies above")
    print("    for validation error messages (they usually reveal the expected field names).")


def redact(obj):
    """Recursively redact any dict value whose key looks like a credential/password."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and "password" in k.lower():
                out[k] = "***REDACTED***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def extract_token(data):
    """Look for a token in common locations in the response JSON."""
    if not isinstance(data, dict):
        return None
    for key in ("token", "access_token", "accessToken"):
        if key in data and data[key]:
            return data[key]
    # Sometimes wrapped in a "data"/"result" envelope
    for wrapper in ("data", "result"):
        if wrapper in data and isinstance(data[wrapper], dict):
            found = extract_token(data[wrapper])
            if found:
                return found
    return None


def authenticated_call(method, path, body=None):
    cached = load_token()
    url = cached["base_host"] + path.lstrip("/")
    headers = dict(COMMON_HEADERS)
    headers["Authorization"] = cached["token"]

    print(f"=== {method} {url} ===")
    if body is not None:
        print(f"body: {json.dumps(body, ensure_ascii=False)}")

    try:
        resp = requests.request(method, url, json=body, headers=headers, timeout=10)
    except requests.RequestException as e:
        print(f"request failed: {e}")
        return

    print(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
    except ValueError:
        print(f"(non-JSON body, {len(resp.content)} bytes): {resp.text[:1000]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "login":
        try_login()
    elif cmd == "call":
        if len(sys.argv) < 3:
            print("usage: call <path> [json-body]")
            sys.exit(1)
        path = sys.argv[2]
        body = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
        authenticated_call("POST", path, body)
    elif cmd == "raw":
        if len(sys.argv) < 4:
            print("usage: raw <method> <path> [json-body]")
            sys.exit(1)
        method, path = sys.argv[2], sys.argv[3]
        body = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        authenticated_call(method, path, body)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
