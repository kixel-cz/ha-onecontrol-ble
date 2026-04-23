#!/usr/bin/env python3
"""
Extract 1Control security keys from a mitmproxy log file.
"""
import re, json, sys

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <mitmproxy_log_file>", file=sys.stderr)
    sys.exit(1)

try:
    log = open(sys.argv[1], "rb").read().decode("utf-8", errors="ignore")
except FileNotFoundError:
    print(f"Error: file '{sys.argv[1]}' not found", file=sys.stderr)
    sys.exit(1)

sk  = re.search(r'"sessionKey":"([0-9A-Fa-f]+)"', log)
sid = re.search(r'"sessionID":"([0-9A-Fa-f]+)"', log)
ltk = re.search(r'"ltk":"([0-9A-Fa-f]+)"', log)
cc  = re.search(r'"lastCC":(\d+)', log)

if not all([sk, sid, ltk]):
    print("Error: could not find security data in log.", file=sys.stderr)
    print("Make sure the log contains a /security/{serial} API call.", file=sys.stderr)
    sys.exit(1)

result = {
    "ltk":        ltk.group(1).upper(),
    "sessionKey": sk.group(1).upper(),
    "sessionID":  sid.group(1).upper(),
    "lastCC":     int(cc.group(1)) if cc else None,
}

print(json.dumps(result, indent=2))
print(f"\nLTK:         {result['ltk']}", file=sys.stderr)
print(f"Session Key: {result['sessionKey']}", file=sys.stderr)
print(f"Session ID:  {result['sessionID']}", file=sys.stderr)
