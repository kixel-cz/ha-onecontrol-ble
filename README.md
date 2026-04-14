# 1Control SoloMini BLE for Home Assistant - work in progress, it's not working yet!

[![HACS Custom][hacs-badge]][hacs-url]
[![License: MIT][license-badge]][license-url]
[![HA Version][ha-badge]][ha-url]

Local Home Assistant integration for **1Control SoloMini RE** garage door openers via Bluetooth. No cloud, no dependency on the 1Control app — everything works directly over BLE.

## Features

- ✅ Open garage door / gate with one tap
- ✅ Automatic BLE pairing — no key or account needed
- ✅ Fully local — no cloud, no internet required
- ✅ Works with any HA Bluetooth adapter (built-in or USB dongle)
- ✅ HACS installation

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

## Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for **1Control SoloMini BLE**
3. Enter the BLE address of your device (e.g. `EF:73:A3:39:3B:E4`)
4. Leave the **LTK key empty** — the integration pairs automatically on first use
5. Click **Submit**

A **Cover** entity is created which you can add to your dashboard or use in automations.

### Where do I find the BLE address?

- In the 1Control app: device detail → info
- On the label on the SoloMini device itself
- In HA: **Settings → System → Bluetooth** → list of visible devices

### Pairing

On first use (pressing **Open** in HA), the integration automatically:

1. Generates a cryptographic keypair (ECDH secp256r1)
2. Pairs with the device over BLE
3. Saves the key — subsequent connections skip pairing

If pairing fails, make sure the SoloMini is in Bluetooth range and that no PIN is set on the device (default is no PIN).

---

## Advanced configuration

If you want to provide an LTK key manually (e.g. exported from another installation), enter it as 32 hex characters in the **LTK key** field during setup.

To extract the LTK from a 1Control cloud account (if the device was paired via the cloud), use `tools/extract_ltk.py`:

```bash
python3 tools/extract_ltk.py \
  --email your@email.com \
  --password your_password \
  --serial 28524
```

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
          entity_id: cover.solumini_gate
```

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Device not visible in HA | Check HA Bluetooth adapter, restart integration |
| Pairing fails | Make sure SoloMini is in range and try again |
| Gate doesn't open after pairing | Try action number 0 instead of 1 in integration settings |
| Integration disconnects | Normal — SoloMini is wake-on-demand over BLE |

---

## Technical details

<details>
<summary>BLE protocol (for enthusiasts)</summary>

Reverse-engineered from `it.onecontrol.apk` v2.6.4.

### BLE characteristics

| UUID | Direction | Type |
|---|---|---|
| `D973F2E1-B19E-11E2-9E96-0800200C9A66` | HA → device | Write |
| `D973F2E2-B19E-11E2-9E96-0800200C9A66` | device → HA | Indicate |

### Communication flow

```
1. PAIRING (once, result is saved):
   HA → device:  [00][42][90][01][phone_pubkey_64B]
   device → HA:  [device_pubkey_64B]
   LTK = SHA256(ECDH(phone_privkey, device_pubkey))[0:16]

2. SESSION (every connection):
   HA → device:  [00][0A][90][02][randomA_8B]
   device → HA:  [randomB_8B]
   sessionID  = SHA256(randomA || randomB)[0:8]
   sessionKey = SHA256(LTK || sessionID)[0:16]

3. GREETING (device → HA, sent on connect):
   [00][11][01][sessionID_8B][2B][userID_2B][CC_lo][CC_hi][00][00]

4. OPEN (HA → device):
   nonce   = sessionID || CC+1 as uint32 LE        (12 B)
   aad     = [userID 2B] || [CC+1 uint32 LE] || [01] (7 B)
   CCM_out = AES-CCM-128(sessionKey, nonce, aad,
               plaintext=action_2B, mac_len=6)       (8 B)
   packet: [00][0F][01][CCM_out_8B][userID_2B][CC+1_2B][00][00]
```

### Key APK source files

| File | Description |
|---|---|
| `x2.java` | ECDH pairing worker |
| `w2.java` | StartSession — session key derivation |
| `d9/e.java` | AES-CCM packet builder (`e.h()`) |
| `d9/j.java` | SHA256 KDF helpers, ECDH functions |
| `StartPairingRequest.java` | Pairing packet format |
| `StartSessionRequest.java` | Session packet format |
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
