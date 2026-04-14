#!/usr/bin/env python3
"""
1Control LTK Extractor — cloud API metoda
==========================================
Stáhne SecurityData (LTK, userID) přímo ze serveru 1Control
pomocí Firebase autentizace a jejich REST API.

NetworkController.java odhalil:
  BASE_URL = "https://onecontrolcloud.appspot.com/_ah/api/app1Control/v1/"
  getSecurityData(serial) → GET security/{serial}
  Auth: Firebase ID token jako Bearer

POUŽITÍ:
  python3 extract_ltk.py --email tvuj@email.cz --password heslo --serial 28524 --apk it.onecontrol.apk
  python3 extract_ltk.py --email tvuj@email.cz --password heslo --serial 28524 --firebase-key AIzaSy...
  python3 extract_ltk.py --token "eyJhbGci..." --serial 28524
  python3 extract_ltk.py --email ... --password ... --list   # discovery všech zařízení
"""

import argparse, base64, json, sys, zipfile
from pathlib import Path
import urllib.request, urllib.error

BASE_URL     = "https://onecontrolcloud.appspot.com/_ah/api/app1Control/v1/"
FIREBASE_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"

# Firebase API key — extrahovaný z 1Control_2.6.4_APKPure.xapk
KNOWN_FIREBASE_KEY = "AIzaSyBFP7OI81UWqm3aBjecFbTn7ossMx_l5Ow"


def extract_firebase_key_from_apk(apk_path):
    """Extrahuje Firebase API key z google-services.json uvnitř APK."""
    import re
    try:
        with zipfile.ZipFile(apk_path) as zf:
            if "google-services.json" in zf.namelist():
                data = json.loads(zf.read("google-services.json"))
                key = data["client"][0]["api_key"][0]["current_key"]
                print(f"[✓] Firebase API key z google-services.json: {key}")
                return key
            for name in zf.namelist():
                try:
                    content = zf.read(name).decode("utf-8", errors="ignore")
                    keys = re.findall(r'AIza[A-Za-z0-9_-]{35}', content)
                    if keys:
                        print(f"[✓] Firebase API key z {name}: {keys[0]}")
                        return keys[0]
                except Exception:
                    pass
    except Exception as e:
        print(f"[!] Chyba při čtení APK: {e}")
    return None


def firebase_sign_in(email, password, api_key):
    """Firebase email/password login → vrátí ID token."""
    payload = json.dumps({
        "email": email, "password": password, "returnSecureToken": True
    }).encode()
    try:
        req = urllib.request.Request(
            f"{FIREBASE_URL}?key={api_key}", data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            token = data.get("idToken")
            if token:
                print(f"[✓] Firebase přihlášení OK (UID: {data.get('localId')})")
                return token
    except urllib.error.HTTPError as e:
        print(f"[!] Firebase chyba {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"[!] Chyba přihlášení: {e}")
    return None


def api_get(path, token):
    """Volá 1Control REST API GET."""
    url = BASE_URL + path
    print(f"[*] GET {url}")
    try:
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[!] HTTP {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"[!] Chyba: {e}")
    return None


def parse_ltk(data):
    """Dekóduje LTK z různých formátů (base64, hex, byte array)."""
    ltk_raw = data.get("ltk") or data.get("sessionKey") or data.get("ltkKey")
    if ltk_raw is None:
        return None
    if isinstance(ltk_raw, list):
        return bytes([b & 0xFF for b in ltk_raw[:16]]).hex()
    if isinstance(ltk_raw, str):
        # zkus base64
        try:
            decoded = base64.b64decode(ltk_raw)
            if len(decoded) >= 16:
                return decoded[:16].hex()
        except Exception:
            pass
        # zkus hex
        cleaned = ltk_raw.strip().lower().replace(" ", "").replace(":", "")
        if len(cleaned) >= 32 and all(c in "0123456789abcdef" for c in cleaned):
            return cleaned[:32]
    return None


def main():
    ap = argparse.ArgumentParser(description="Stáhne LTK ze serverů 1Control")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--serial", type=int, default=0)
    ap.add_argument("--firebase-key", dest="firebase_key")
    ap.add_argument("--apk", help="Cesta k it.onecontrol.apk")
    ap.add_argument("--token", help="Existující Firebase ID token")
    ap.add_argument("--list", action="store_true", help="Vypiš všechna zařízení")
    ap.add_argument("--output", "-o", default="ltk_result.json")
    args = ap.parse_args()

    # ── ID token ─────────────────────────────────────────────────────
    token = args.token
    if not token:
        if not args.email or not args.password:
            print("[!] Potřebuješ --email + --password nebo --token")
            sys.exit(1)
        api_key = args.firebase_key or KNOWN_FIREBASE_KEY
        if not api_key and args.apk:
            api_key = extract_firebase_key_from_apk(args.apk)
        if not api_key:
            for f in ["it.onecontrol.apk", "onecontrol.apk"]:
                if Path(f).exists():
                    api_key = extract_firebase_key_from_apk(f)
                    if api_key:
                        break
        if not api_key:
            print("[!] Firebase API key nenalezen. Použij --apk nebo --firebase-key")
            print("    Extrakce z APK:  unzip it.onecontrol.apk google-services.json")
            print("    python3 -c \"import json; d=json.load(open('google-services.json'))\"")
            print("             \" ; print(d['client'][0]['api_key'][0]['current_key'])\"")
            sys.exit(1)
        token = firebase_sign_in(args.email, args.password, api_key)
        if not token:
            sys.exit(1)

    # ── Discovery ─────────────────────────────────────────────────────
    if args.list or not args.serial:
        devices = api_get("devices/solo", token) or {}
        items = devices.get("items", [])
        if items:
            print(f"\n[✓] {len(items)} Solo zařízení na účtu:")
            for d in items:
                print(f"    Serial: {d.get('serial', '?'):>8}  "
                      f"Name: {d.get('name', '?'):<20}  "
                      f"Type: {d.get('deviceType', '?')}")
        else:
            print("[!] Žádná zařízení nenalezena")
        if not args.serial:
            print("\nSpusť znovu s --serial <číslo>")
            sys.exit(0)

    # ── SecurityData ──────────────────────────────────────────────────
    data = api_get(f"security/{args.serial}", token)
    if not data:
        sys.exit(1)

    print("\n[*] Raw SecurityData:")
    print(json.dumps(data, indent=2))

    ltk_hex = parse_ltk(data)
    if not ltk_hex:
        print("[!] LTK nenalezeno nebo nelze dekódovat")
        print("    Klíče v odpovědi:", list(data.keys()))
        sys.exit(1)

    result = {
        "ltk":      ltk_hex,
        "user_id":  int(data.get("userId", 0) or data.get("user_id", 0) or 0),
        "last_cc":  int(data.get("lastCC", 0) or data.get("last_cc", 0) or 0),
        "serial":   int(data.get("deviceSerial", args.serial) or args.serial),
        "user_type": data.get("userType", "?"),
    }

    print(f"""
{'='*60}
  LTK PRO HOME ASSISTANT
{'='*60}
  Serial:    {result['serial']}
  LTK:       {result['ltk']}
  User ID:   {result['user_id']}
  User Type: {result['user_type']}

  V HA config flow zadej:
    Adresa:   EF:73:A3:39:3B:E4
    LTK:      {result['ltk']}
    User ID:  {result['user_id']}
{'='*60}
""")

    Path(args.output).write_text(json.dumps(result, indent=2))
    print(f"[✓] Uloženo: {args.output}")


if __name__ == "__main__":
    main()
