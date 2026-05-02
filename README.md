# 1Control SoloMini BLE for Home Assistant

[![HACS Custom][hacs-badge]][hacs-url]
[![License: MIT][license-badge]][license-url]
[![HA Version][ha-badge]][ha-url]

Local Home Assistant integration for **1Control SoloMini** garage door openers via Bluetooth. No cloud dependency during operation — everything works directly over BLE.

## Features

- ✅ Open garage door / gate with one tap
- ✅ Battery level sensor with device info
- ✅ Learn new remotes directly from HA
- ✅ Clone existing remotes (rolling code)
- ✅ Fully local operation — no cloud, no internet required after setup
- ✅ Works with any HA Bluetooth adapter (built-in or USB dongle)
- ✅ HACS installation

---

## Prerequisites

To set up the integration you need to obtain security keys from the 1Control cloud **once**. The keys are permanent and do not change.

**Two methods are available:**

1. **mitmproxy** — capture the 1Control app communication (works with existing paired device)
2. **ECDH pairing** — pair directly from HA (requires device in factory reset state)

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

## Getting security keys

### Method 1: mitmproxy (existing device)

1. Install [mitmproxy](https://mitmproxy.org/) on your computer
2. Configure your phone to use your computer as an HTTP/HTTPS proxy
3. Install the mitmproxy CA certificate on your phone
4. Start `mitmdump -w onecontrol.log` on your computer
5. Open the 1Control app and trigger a gate open
6. Stop mitmproxy

You can then either:
- **Paste the log directly** into the integration setup (keys extracted automatically), or
- **Use the extraction script**:

```bash
python3 tools/parse_mitm_log.py onecontrol.log
```

### Method 2: ECDH pairing (factory reset device)

If your device is in factory reset state (no existing pairing), the integration can pair directly without the 1Control app. Select **"Pair device"** during setup — the integration will perform ECDH key exchange over BLE and derive the LTK automatically.

Note: after pairing you still need to obtain the **Session Key** and **Session ID** via mitmproxy, as these come from the 1Control cloud.

---

## Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for **1Control SoloMini BLE**
3. **Step 1** — Select key entry method: mitmproxy log or pairing
4. **Step 2** — Paste mitmproxy log (optional, for automatic key extraction)
5. **Step 3** — Enter BLE address and security keys
6. Click **Submit**

### Where do I find the BLE address?

- In HA: **Settings → System → Bluetooth** → list of visible devices
- Using a BLE scanner app (e.g. nRF Connect) — search for service UUID `D973F2E0-B19E-11E2-9E96-0800200C9A66`

---

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| Gate | Cover | Open the gate |
| Battery | Sensor | Battery level (%) |
| Device Name | Sensor | Name configured in the 1Control app |
| Firmware Version | Sensor | Device firmware version |
| Production Date | Sensor | Manufacturing date |
| Serial Number | Sensor | Device serial number |
| Max Actions | Sensor | Number of configured actions |
| Max Users | Sensor | Maximum number of users |
| Clone remote | Button | Clone rolling code remote |
| 1. Start learning | Button | Begin learning a new remote |
| 2. Test remote | Button | Send test signal to verify |
| 3. Save remote | Button | Save the learned remote |
| Cancel learning | Button | Cancel without saving |
| Opening time | Number | Gate opening duration (seconds) |

---

## Learning a new remote

To teach the SoloMini a new physical remote:

1. Press **"1. Start learning"** in HA
2. Press the button on your physical remote
3. Press **"2. Test remote"** — the gate should activate
4. Verify physically that the gate responded
5. Press **"3. Save remote"** to store the remote
6. Or press **"Cancel learning"** to abort without saving

To clone a rolling code remote, press **"Clone remote"** and then press the button on your physical remote.

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
| Gate doesn't open | Verify the security keys — they must match the paired device |
| Integration disconnects | Normal — SoloMini is wake-on-demand over BLE |
| Wrong action number | Try action number 1 instead of 0 in integration settings |
| Battery shows unknown | Trigger a gate open first — battery is read from the device greeting |

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
   nonce   = server_sessionID || (CC+1) as uint32 LE   (12 B)
   aad     = [userID 2B] || [(CC+1) uint32 LE] || [0x01] (7 B)
   CCM_out = AES-CCM-128(server_sessionKey, nonce, aad,
               plaintext=[0x01, action], mac_len=6)
   packet: [00][0F][01][CCM_out_8B][userID_2B][CC+1_4B]

4. TRANSMIT commands (same format, different plaintext[0]):
   Open:           [0x01, action]
   CloneRemote:    [0x02, action]
   StartScanner:   [0x0C, action]
   ConfirmScanner: [0x0D, action]
   CompleteScanner:[0x0E, action]
   UndoScanner:    [0x0F, action]

5. GET SYSTEM INFO (cmd=0x14):
   Request:  [0x14][AES-CCM([0xFF])][uid_2B][CC_4B]
   Response: fragmented packets (type 4), assembled and decrypted
   Contains: serial, battery_raw, firmware version, device name, etc.

6. PAIRING (factory reset device):
   HA → device:  [00][42][90][01][phone_pubkey_64B]
   device → HA:  [00][42][90][00][device_pubkey_64B]
   LTK = SHA256(ECDH(phone_privkey, device_pubkey))[0:16]
   curve: secp256r1
```

### Key APK source files

| File | Description |
|---|---|
| `w2.java` | StartSession — session key derivation |
| `x2.java` | ECDH pairing |
| `d9/e.java` | AES-CCM packet builder |
| `d9/j.java` | SHA256 KDF, ECDH helpers |
| `request/solo/TransmitRequest.java` | Open/Clone/Scanner commands |
| `request/solo/GetSystemInfoRequest.java` | System info including battery |
| `request/StartPairingRequest.java` | Pairing packet format |

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
