# VIDAA TV for Home Assistant

[![Validate](https://github.com/techmarkai/ha-vidaa-tv/actions/workflows/validate.yml/badge.svg)](https://github.com/techmarkai/ha-vidaa-tv/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local push integration for Hisense and Toshiba TVs running VIDAA OS that expose an
**unencrypted** MQTT broker on port `36669`. No cloud, no MQTT bridge, no polling.

## Why this exists

The established VIDAA integrations connect with TLS and expect a PIN pairing flow.
A large family of older sets — including Toshiba-branded VIDAA models — speak
**plain MQTT and actively reset every TLS handshake**, so those integrations can
never connect to them. This one talks to the TV the way the TV actually answers.

> **Which one do I need?** If pairing the phone remote app shows a PIN on the TV,
> use a PIN-capable integration instead. If it just connects, this is the one.

## Features

| | |
|---|---|
| **Power** | Off via the protocol; on via Wake-on-LAN (see caveats) |
| **Volume** | Absolute level, up/down, mute |
| **Sources** | TV, AV, HDMI1–3 — read live from the TV, not hard-coded |
| **Apps** | Netflix, YouTube, Plex, browser, Screen Mirroring, and anything else installed |
| **Play media** | Launch an app, open a URL, switch input, or tune a channel |
| **Media browser** | Browse apps, inputs and channels from HA's media browser |
| **Remote** | Every key, via a `remote` entity — arbitrary keys accepted |
| **Text entry** | Type into TV search boxes and login fields |
| **Channels** | Channel list and current channel, where the firmware provides them |
| **Raw access** | Publish any MQTT message to the TV |
| **State** | Push. The TV broadcasts app, input and volume changes as they happen |

- Survives the TV being switched off. The integration never fails setup on an
  unreachable TV; it retries every 30 seconds and picks the TV back up on its
  own, so no manual reload is ever needed.
- Channel up/down on the media player's next/previous track buttons while
  watching broadcast TV. Inside apps the same buttons seek as before.

Entities created: `media_player.<name>` and `remote.<name>_remote`.

## Installation

### HACS (recommended)

1. **HACS → three-dot menu → Custom repositories**
2. Add `https://github.com/techmarkai/ha-vidaa-tv`, category **Integration**
3. Install **VIDAA TV**, then restart Home Assistant

### Manual

Copy `custom_components/vidaa_tv/` into your Home Assistant `config/custom_components/`
directory and restart.

## Setup

**Settings → Devices & Services → Add Integration → VIDAA TV**

The integration finds TVs three ways:

1. **DHCP discovery** — when a TV with a known VIDAA MAC prefix or hostname joins
   the network, Home Assistant offers it automatically.
2. **Active scan** — on manual setup it scans Home Assistant's own subnets for the
   VIDAA port and lists what it finds. VIDAA TVs answer no SSDP or mDNS, so an
   active scan is the only way to find one.
3. **Manual entry** — choose *Enter IP address manually* and type the address.

The TV must be **switched on** during setup; the connection is verified before the
entry is created, so you never end up with a silently dead entity.

The MAC address field is optional and only used for Wake-on-LAN.

## Casting and `play_media`

**These TVs do not speak Google Cast.** VIDAA uses Anyview Cast (Miracast) and, on
newer sets, AirPlay — neither of which Home Assistant can send to. HA's `cast`
integration will never discover a VIDAA TV. What this integration offers instead is
app launching, which covers most of what people actually want from "cast this":

```yaml
# Launch an installed app, by name or by its internal url
action: media_player.play_media
target: { entity_id: media_player.living_room_tv }
data:
  media_content_type: app
  media_content_id: Netflix

# Open a web page in the TV browser
data:
  media_content_type: url
  media_content_id: https://example.com

# Tune a channel by number (keyed in like the physical remote)
data:
  media_content_type: channel
  media_content_id: "104"
```

For real screen mirroring, select the **Screen Mirroring** source to put the TV into
Miracast mode, then cast from your phone:

```yaml
action: media_player.select_source
target: { entity_id: media_player.living_room_tv }
data: { source: Screen Mirroring }
```

If your TV exposes a DLNA renderer, Home Assistant's built-in `dlna_dmr`
integration can push media to it directly — no custom code needed. Worth checking
before reaching for anything more complicated.

## Services

### `remote.send_command`

Sending keys uses the standard Home Assistant remote entity — no integration
specific service. You get targeting, repeats and delays for free. The `KEY_`
prefix is optional, and the TV silently ignores keys it does not implement, so
experimenting is safe.

```yaml
action: remote.send_command
target:
  entity_id: remote.living_room_tv_remote
data:
  command:
    - KEY_MENU
    - KEY_DOWN
    - KEY_OK
  delay_secs: 0.5
```

The keys in the `vidaa_tv.send_key` dropdown are the ones VIDAA remotes are
known to send — see `KEYS` in `custom_components/vidaa_tv/const.py` for the
canonical list. It is a starting point, **not** a whitelist: any string is
passed straight through, so unlisted keys still work.

### `vidaa_tv.send_key`

One key, with a dropdown of every known key in the UI — the discoverable way to
find out what you can send. Any value is still accepted, so unlisted keys work.

```yaml
action: vidaa_tv.send_key
data:
  key: KEY_CHANNELUP
```

Use `remote.send_command` instead when you want a sequence, repeats, delays, or
to target a specific TV by entity.

### `vidaa_tv.publish`

Escape hatch for anything this integration does not model. Use `service` +
`action` for the normal topic tree, or `topic` for a completely arbitrary topic.

```yaml
action: vidaa_tv.publish
data:
  service: ui_service
  action: changesource
  payload:
    sourceid: "4"
```

### `vidaa_tv.send_text`

Type into whatever field the TV has focused — a search box, a login form. Not
all firmware implements this; those TVs quietly ignore it.

```yaml
action: vidaa_tv.send_text
data:
  text: stranger things
```

### `vidaa_tv.refresh`

Ask the TV to resend its source list, app list, device info and channel list.

## What does my TV support?

Firmware varies a lot. To find out exactly what yours answers:

```bash
python tools/probe.py 192.168.1.50
```

It tries both plain and TLS transports, fires every action worth trying, and
prints which ones replied. Nothing it sends changes a setting. If your TV
answers something this integration does not model yet, that output is exactly
what to attach to an issue.

## Upgrading from 1.x

`vidaa_tv.send_key` was removed in 2.0.0 in favour of `remote.send_command`, and
returned in 2.3.0 with a dropdown of every known key. Both work: use
`vidaa_tv.send_key` for a single key, and `remote.send_command` when you want a
sequence, repeats, delays, or to target a specific TV by entity.

```yaml
# either
action: vidaa_tv.send_key
data: { key: KEY_SUBTITLE }

# or
action: remote.send_command
target: { entity_id: remote.living_room_tv_remote }
data: { command: KEY_SUBTITLE }
```

Nothing else changed. Entities, unique IDs and config entries are untouched, so
no reconfiguration is needed.

## Caveats

**Turn-on is unreliable across subnets.** When the TV is off its MQTT broker is
gone, so the only way back is a Wake-on-LAN packet. WoL is a broadcast, and
broadcasts do not cross subnets — if Home Assistant is not on the same subnet as
the TV, turn-on will most likely do nothing. Everything else works fine routed.

**No PIN support.** Newer VIDAA firmware requires pairing; setup reports
`invalid_auth` in that case.

**Mute is tracked optimistically.** The TV toggles mute but never reports the
state back, so the flag can drift if you also use the physical remote.

**The key list is a convenience, not a whitelist.** The TV never acknowledges
keys, so the list in `const.py` cannot be verified exhaustively. Any key string
you send is passed straight through.

**The media player stays "off", not "unavailable".** While the TV is off, the
media player reports `off` rather than `unavailable`, and its volume and
source read as unknown. This is deliberate: it keeps `turn_on` callable so
Wake-on-LAN automations still work.

## Development

```bash
python test_vidaa.py
```

Checks message parsing, state handling, topic construction and volume clamping
with no TV and no Home Assistant install required.

## Protocol

Credentials are baked into the firmware: `hisenseservice` / `multimqttservice`,
plain TCP on port `36669`. The client id must keep the `<mac>$normal` shape; the
MAC itself is arbitrary.

| Purpose | Topic (`ME` = client id) | Payload |
|---|---|---|
| Key press | `/remoteapp/tv/remote_service/{ME}/actions/sendkey` | `KEY_VOLUMEUP` |
| Set volume | `/remoteapp/tv/platform_service/{ME}/actions/changevolume` | `47` |
| Switch source | `/remoteapp/tv/ui_service/{ME}/actions/changesource` | `{"sourceid":"4"}` |
| Launch app | `/remoteapp/tv/ui_service/{ME}/actions/launchapp` | app object from `applist` |
| Query | `/remoteapp/tv/ui_service/{ME}/actions/{sourcelist,applist}` | empty |

Replies arrive on `/remoteapp/mobile/{ME}/ui_service/data/{action}`. Unsolicited
state arrives on `/remoteapp/mobile/broadcast/ui_service/state` and
`/remoteapp/mobile/broadcast/platform_service/actions/volumechange`.

Note that app state reports a `name` field while input switches report
`sourcename` instead — both must be handled.

Source ids: `TV=0`, `AV=1`, `HDMI1=4`, `HDMI2=5`, `HDMI3=6`.

## License

MIT
