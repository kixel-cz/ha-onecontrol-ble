# 1Control SoloMini BLE pro Home Assistant

[![HACS Custom][hacs-badge]][hacs-url]
[![License: MIT][license-badge]][license-url]
[![HA Version][ha-badge]][ha-url]

Lokální Home Assistant integrace pro garážové ovladače **1Control SoloMini RE** přes Bluetooth. Žádný cloud, žádná závislost na aplikaci 1Control — vše funguje přímo přes BLE.

> **Čeština / English:** This README is in Czech. [English version below.](#english)

---

## Funkce

- ✅ Otevírání garážových vrat / brány jedním kliknutím
- ✅ Automatické BLE párování — není potřeba žádný klíč ani účet
- ✅ Zcela lokální provoz — bez cloudu, bez internetu
- ✅ Funguje na Home Assistant s Bluetooth adaptérem (vestavěný nebo USB dongle)
- ✅ Instalace přes HACS

---

## Požadavky

- Home Assistant 2023.12 nebo novější
- Bluetooth adaptér dostupný pro HA (vestavěný v Raspberry Pi, nebo USB dongle jako ASUS BT-500)
- 1Control SoloMini RE v dosahu Bluetooth (obvykle do 10 m)

---

## Instalace přes HACS

1. Otevřete **HACS** → **Integrace**
2. Klikněte na ⋮ (tři tečky vpravo nahoře) → **Vlastní repozitáře**
3. Zadejte URL: `https://github.com/alexejsidorenko/ha-onecontrol-ble`
4. Kategorie: **Integrace** → **Přidat**
5. Vyhledejte **1Control SoloMini BLE** a nainstalujte
6. Restartujte Home Assistant

---

## Konfigurace

1. Přejděte do **Nastavení → Zařízení a služby → Přidat integraci**
2. Vyhledejte **1Control SoloMini BLE**
3. Vyplňte BLE adresu zařízení (např. `EF:73:A3:39:3B:E4`)
4. Pole **LTK klíč nechte prázdné** — integrace se zařízením spáruje automaticky
5. Klikněte **Odeslat**

Po uložení se v HA vytvoří entita typu **Cover** (garážová vrata), kterou můžete přidat na dashboard nebo použít v automatizacích.

### Kde najdu BLE adresu?

- V aplikaci 1Control: detail zařízení → informace
- Na štítku přímo na zařízení SoloMini
- V HA: **Nastavení → Systém → Bluetooth** → seznam viditelných zařízení

### Párování

Při prvním použití (stisk tlačítka **Otevřít** v HA) integrace automaticky:

1. Vygeneruje kryptografický klíč (ECDH secp256r1)
2. Spáruje se se zařízením přes BLE
3. Uloží klíč — příště se připojí rovnou bez párování

Pokud párování selže, ujistěte se že SoloMini je v dosahu Bluetooth a že na zařízení není nastaven PIN omezující párování nových telefonů (výchozí stav je bez PINu).

---

## Pokročilá konfigurace

Pokud chcete zadat LTK klíč ručně (např. exportovaný z jiné instalace), zadejte ho jako 32 hexadecimálních znaků do pole **LTK klíč** při konfiguraci.

Pro extrakci LTK z cloudového účtu 1Control (pokud bylo zařízení spárováno přes cloudový účet) použijte skript `tools/extract_ltk.py`:

```bash
python3 tools/extract_ltk.py \
  --email vas@email.cz \
  --password vase_heslo \
  --serial 28524
```

---

## Automatizace

Příklad automatizace pro otevření brány při příjezdu domů:

```yaml
automation:
  - alias: "Otevřít bránu při příjezdu"
    trigger:
      - platform: zone
        entity_id: person.ja
        zone: zone.home
        event: enter
    action:
      - service: cover.open_cover
        target:
          entity_id: cover.solumini_brana
```

---

## Řešení problémů

| Problém | Řešení |
|---|---|
| Zařízení není vidět v HA | Zkontrolujte Bluetooth adaptér v HA, restartujte integraci |
| Párování selže | Ujistěte se že SoloMini je v dosahu a zkuste znovu |
| Brána se neotevře po párování | Zkuste jiné číslo akce (0 místo 1) v nastavení integrace |
| Integrace se odpojí | Normální chování — SoloMini BLE je wake-on-demand, připojuje se jen při akci |

---

## Technické detaily

<details>
<summary>Protokol BLE (pro nadšence)</summary>

Integrace byla vytvořena reverse engineeringem aplikace `it.onecontrol.apk` v2.6.4.

### BLE charakteristiky

| UUID | Směr | Typ |
|---|---|---|
| `D973F2E1-B19E-11E2-9E96-0800200C9A66` | HA → zařízení | Write |
| `D973F2E2-B19E-11E2-9E96-0800200C9A66` | zařízení → HA | Indicate |

### Průběh komunikace

```
1. PÁROVÁNÍ (jednou, výsledek se uloží):
   HA → zařízení:  [00][42][90][01][phone_pubkey_64B]
   zařízení → HA:  [device_pubkey_64B]
   LTK = SHA256(ECDH(phone_privkey, device_pubkey))[0:16]

2. SESSION (každé připojení):
   HA → zařízení:  [00][0A][90][02][randomA_8B]
   zařízení → HA:  [randomB_8B]
   sessionID  = SHA256(randomA || randomB)[0:8]
   sessionKey = SHA256(LTK || sessionID)[0:16]

3. GREETING (zařízení → HA, automaticky po připojení):
   [00][11][01][sessionID_8B][2B][userID_2B][CC_lo][CC_hi][00][00]

4. OPEN (HA → zařízení):
   nonce   = sessionID || CC+1 jako uint32 LE        (12 B)
   aad     = [userID 2B] || [CC+1 uint32 LE] || [01] ( 7 B)
   CCM_out = AES-CCM-128(sessionKey, nonce, aad,
               plaintext=action_2B, mac_len=6)        ( 8 B)
   paket:  [00][0F][01][CCM_out_8B][userID_2B][CC+1_2B][00][00]
```

### Klíčové zdrojové soubory APK

| Soubor | Popis |
|---|---|
| `x2.java` | ECDH pairing worker |
| `w2.java` | StartSession — derivace session klíče |
| `d9/e.java` | AES-CCM packet builder (`e.h()`) |
| `d9/j.java` | SHA256 KDF helpery, ECDH funkce |
| `StartPairingRequest.java` | Formát párovacího paketu |
| `StartSessionRequest.java` | Formát session paketu |
| `ControlSecurityRequest.java` | Základ všech šifrovaných příkazů |

</details>

---

## Licence

MIT — viz [LICENSE](LICENSE)

---

<a name="english"></a>

## English

Local Home Assistant integration for **1Control SoloMini RE** garage door openers via Bluetooth. No cloud, no dependency on the 1Control app — everything works directly over BLE.

### Features

- ✅ Open garage door / gate with one tap
- ✅ Automatic BLE pairing — no key or account needed
- ✅ Fully local — no cloud, no internet required
- ✅ Works with any HA Bluetooth adapter
- ✅ HACS installation

### Installation

1. HACS → Integrations → ⋮ → Custom repositories
2. URL: `https://github.com/alexejsidorenko/ha-onecontrol-ble`, Category: Integration
3. Install **1Control SoloMini BLE** and restart HA
4. Settings → Devices & Services → Add Integration → **1Control SoloMini BLE**
5. Enter BLE address (e.g. `EF:73:A3:39:3B:E4`), leave LTK empty → Submit

The integration pairs automatically on first use — no account or manual key extraction needed.

### Troubleshooting

| Issue | Solution |
|---|---|
| Device not visible | Check HA Bluetooth adapter, restart integration |
| Pairing fails | Ensure SoloMini is in range and try again |
| Gate doesn't open after pairing | Try action number 0 instead of 1 |
| Integration disconnects | Normal — SoloMini is wake-on-demand over BLE |

---

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://hacs.xyz
[license-badge]: https://img.shields.io/badge/License-MIT-blue.svg
[license-url]: LICENSE
[ha-badge]: https://img.shields.io/badge/HA-2023.12%2B-green.svg
[ha-url]: https://www.home-assistant.io
