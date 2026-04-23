# 1Control SoloMini BLE for Home Assistant

[![HACS Custom][hacs-badge]][hacs-url]
[![License: MIT][license-badge]][license-url]
[![HA Version][ha-badge]][ha-url]

Local Home Assistant integration for **1Control SoloMini RE** garage door openers via Bluetooth. No cloud dependency during operation — everything works directly over BLE.

## Features

- ✅ Open garage door / gate with one tap
- ✅ Fully local operation — no cloud, no internet required after setup
- ✅ Works with any HA Bluetooth adapter (built-in or USB dongle)
- ✅ HACS installation

---

## Prerequisites

To set up the integration, you need to extract security keys from the 1Control cloud **once** during initial configuration. This requires capturing a mitmproxy log while the 1Control app opens your gate. The keys are permanent and do not change — you will not need to repeat this process.

---

## Installation via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=kixel-cz&repository=ha-onecontrol-ble&category=integration)

Or manually:

1. Open **HACS** → **Integrations**
2. Click ⋮ (top right) → **Custom repositories**
3. URL: `https://github.com/kixel-cz/ha-onecontrol-ble`, Category: **Integration**
4. Click **Add** → find **1Control SoloMini BLE** → **Install**
5. Restart Home Assistant

---

## Getting security keys (one-time setup)

The integration requires three keys extracted from the 1Control cloud: **LTK**, **Session Key**, and **Session ID**. These are permanent and tied to your device pairing.

### Method: mitmproxy

1. Install [mitmproxy](https://mitmproxy.org/) on your computer - see [installation documentation](https://docs.mitmproxy.org/stable/overview/installation/)
2. Configure your phone to use your computer as an HTTP/HTTPS proxy (Settings -> Wi-Fi -> current network -> HTTP proxy: manual ...). Turn the WiFi off and on again to make sure new settings were applied (turn off any VPN if enabled).
3. Install the mitmproxy CA certificate on your phone - [instructions](https://docs.mitmproxy.org/stable/concepts/certificates/)
4. Start `mitmdump -w onecontrol.log` on your computer
5. Open the 1Control app and trigger a gate open
6. Stop mitmproxy — the log file `onecontrol.log` now contains the keys

You can then either:
- **Paste the log directly** into the integration setup (it will extract the keys automatically), or
- **Use the extraction script** from the `tools/` folder:

```bash
python3 tools/parse_mitm_log.py onecontrol.log
```

Output:
```
LTK:         xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Session Key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Session ID:  xxxxxxxxxxxxxxxx
```

---

## Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for **1Control SoloMini BLE**
3. **Step 1 — mitmproxy log** (optional): paste the log contents for automatic key extraction, or leave empty to enter keys manually
4. **Step 2 — Device data**: enter the BLE address and security keys
5. Click **Submit**

A **Cover** entity is created which you can add to your dashboard or use in automations.

### Where do I find the BLE address?

- In the 1Control app: device detail → info
- On the label on the SoloMini device itself
- In HA: **Settings → System → Bluetooth** → list of visible devices

---

## Automation example

```yaml
automation:
  - alias: "Open gate on arrival"
    trigger:
      - platform: zone
        entity_id: person.me
        zone: zone.home
        event: enter
    action:
      - service: cover.open_cover
        target:
          entity_id: cover.solomini_gate
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Device not visible in HA | Check HA Bluetooth adapter, restart integration |
| Gate doesn't open | Verify the security keys — they must match the paired device |
| Integration disconnects | Normal — SoloMini is wake-on-demand over BLE |
| Wrong action number | Try action number 1 instead of 0 in integration settings |

---

## Technical details

<details>
<summary>BLE protocol (for enthusiasts)</summary>

Reverse-engineered from `it.onecontrol.apk` v2.6.4 and iOS btsnoop captures.

### BLE characteristics

| UUID | Direction | Type |
|---|---|---|
| `D973F2E1-B19E-11E2-9E96-0800200C9A66` | HA → device | Write |
| `D973F2E2-B19E-11E2-9E96-0800200C9A66` | device → HA | Indicate |

### Communication flow

```
1. SESSION (every connection):
   HA → device:  [00][0A][90][02][randomA_8B]        (StartSession)
   device → HA:  [00][0A][90][00][randomB_8B]
   our_sessionID  = SHA256(randomA || randomB)[0:8]
   our_sessionKey = SHA256(LTK || our_sessionID)[0:16]

2. PROBE (discover current device CC counter):
   HA → device:  [00][0F][01][AES-CCM(our_sk,cc=1)][uid_2B][0001000000]
   device → HA:  [00][0E][01][...][uid_2B][current_CC_4B]

3. OPEN (using server session key + current CC):
   server_sessionKey = SHA256(LTK || server_sessionID)[0:16]
   nonce   = server_sessionID || (current_CC+1) as uint32 LE   (12 B)
   aad     = [userID 2B] || [(CC+1) uint32 LE] || [0x01]       (7 B)
   CCM_out = AES-CCM-128(server_sessionKey, nonce, aad,
               plaintext=[0x01, action], mac_len=6)             (8 B)
   packet: [00][0F][01][CCM_out_8B][userID_2B][CC+1_4B]
```

### Key insight

The device stores a permanent **Session ID** from the initial cloud pairing. It only accepts open commands encrypted with `SHA256(LTK || stored_sessionID)`. This key is available from the 1Control cloud API (`/security/{serial}`) and does not change.

### Key APK source files

| File | Description |
|---|---|
| `w2.java` | StartSession — session key derivation |
| `d9/e.java` | AES-CCM packet builder (`e.h()`) |
| `StartSessionRequest.java` | Session packet format |
| `OpenAccessRequest.java` | Open command format |
| `ControlSecurityRequest.java` | Base class for all encrypted commands |

</details>

---

## License

MIT — see [LICENSE](LICENSE)

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://hacs.xyz
[license-badge]: https://img.shields.io/badge/License-MIT-blue.svg
[license-url]: LICENSE
[ha-badge]: https://img.shields.io/badge/HA-2023.12%2B-green.svg
[ha-url]: https://www.home-assistant.io
