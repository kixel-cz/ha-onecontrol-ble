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
- ✅ User management (view, add, delete, rename)
- ✅ Device settings (name, daylight saving time)
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

### Testing a development branch

If you want to test a pre-release branch before it's merged, the easiest way is via SSH:

1. Install the **SSH & Terminal** add-on in HA
2. Connect and run:

```bash
cd /config/custom_components
rm -rf onecontrol_ble
git clone --branch improvements --single-branch \
  https://github.com/kixel-cz/ha-onecontrol-ble.git /tmp/oc
mv /tmp/oc/custom_components/onecontrol_ble .
```

3. Restart Home Assistant

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

## Options

After setup, you can adjust the integration options via **Settings → Devices & Services → 1Control SoloMini BLE → Configure**:

| Option | Default | Description |
|--------|---------|-------------|
| Keep BLE connection open | On | Keeps the Bluetooth connection active between commands for faster response (~200 ms vs ~1–2 s). Disable if you suspect it affects device battery life. |
| Full battery (mV) | 3200 | Raw millivolt reading at full charge. The device uses 2× 1.5V alkaline batteries. |
| Empty battery (mV) | 1800 | Raw millivolt reading at empty. Lower this value if the battery sensor drops to 0% too early. |

Changes take effect immediately after saving (the integration reloads automatically).

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
| Users | Sensor | Number of users + list as attributes |
| Clone remote | Button | Clone rolling code remote |
| 1. Start learning | Button | Begin learning a new remote |
| 2. Test remote | Button | Send test signal to verify |
| 3. Save remote | Button | Save the learned remote |
| Cancel learning | Button | Cancel without saving |
| Opening time | Number | Gate opening duration (seconds) |
| Device name | Text | Set device name (max 4 chars, BLE limit) |
| Daylight saving time | Switch | Enable/disable DST |

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

## User management

Users stored on the device can be viewed in the **Users** sensor attributes. User management is available via HA services in **Developer Tools → Actions**:

| Service | Description |
|---------|-------------|
| `onecontrol_ble.add_user` | Add a new user — returns uid and LTK in the HA log |
| `onecontrol_ble.delete_user` | Delete a user by uid |
| `onecontrol_ble.set_user_name` | Rename a user |

> **Note:** When adding a user, the new user's LTK is logged as a WARNING in the HA log. Save it — it cannot be retrieved again.

> **Limitation:** User access restrictions (days, time slots) require a server-signed token which cannot be generated locally. Users added via HA will have default permissions as assigned by the device.

User types:
- **type 1** — admin (permanent access, no restrictions)
- **type 0** — standard user (time-limited access with day/time restrictions)

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
| Wrong action number | Try action number 1 instead of 0 in integration settings |
| Battery shows unknown | Trigger a gate open first — battery is read from the device response |
| Sensors show unknown after restart | Wait for coordinator refresh (up to 1 hour) or trigger manually via Developer Tools |

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
1. SESSION (on connect):
   HA → device:  [00][0A][90][02][randomA_8B]        (StartSession)
   device → HA:  [00][0A][90][00][randomB_8B]
   sessionID  = SHA256(randomA || randomB)[0:8]
   sessionKey = SHA256(LTK || sessionID)[0:16]

2. PROBE (discover current device CC counter):
   HA → device:  [00][0F][01][AES-CCM(our_sk,cc=1)][uid_2B][CC_4B]
   device → HA:  [00][0E][01][...][uid_2B][current_CC_4B]

3. OPEN (using server session key + current CC):
   nonce   = server_sessionID || (CC+1) as uint32 LE   (12 B)
   aad     = [userID 2B] || [(CC+1) uint32 LE] || [0x01] (7 B)
   CCM_out = AES-CCM-128(server_sessionKey, nonce, aad,
               plaintext=[0x01, action], mac_len=6)
   packet: [00][0F][01][CCM_out_8B][userID_2B][CC+1_4B]

4. PAIRING (factory reset device only):
   HA → device:  [00][42][90][01][phone_pubkey_64B]
   device → HA:  [00][42][90][00][device_pubkey_64B]
   LTK = SHA256(ECDH(phone_privkey, device_pubkey))[0:16]
   curve: secp256r1
```

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
