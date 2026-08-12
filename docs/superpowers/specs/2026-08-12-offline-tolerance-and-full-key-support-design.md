# VIDAA TV: offline tolerance and full key support

Date: 2026-08-12

## Problem

Two defects, one report.

1. **A powered-off TV is treated as a setup failure.** `async_setup_entry` raises
   `ConfigEntryNotReady` when the initial connect fails, so the config entry lands in
   `setup_retry`. Home Assistant's own retry backoff grows to 15 minutes, so a TV
   switched on again is not picked up for a long time — in practice the user reloads
   the integration by hand every time.

2. **The full remote key set is undiscoverable.** `remote.send_command` already accepts
   any key string, but nothing in the UI says which keys exist, and channel up/down has
   no home on the media player at all.

## Design

### 1. Connection: fire-and-forget, flat 30s retry

`VidaaTV.async_start()` stops blocking on CONNACK. It calls `connect_async()` followed by
`loop_start()` and returns immediately. paho owns the retry loop, configured with
`reconnect_delay_set(min_delay=30, max_delay=30)` — a flat 30 seconds with no backoff, so
a TV that comes back on appears in Home Assistant within 30 seconds.

The existing 90-second watchdog stays. Its scope narrows to the one case paho cannot
handle: a network thread that has died or wedged, leaving nothing retrying at all.

`test_connection` is unchanged and still blocking — it serves the config flow, not runtime.

### 2. Setup never fails

`ConfigEntryNotReady` is removed from `async_setup_entry`, which always returns `True`. A
TV that is off, unplugged, or behind a dead switch yields a working config entry whose
entities report `off`.

The config flow still requires the TV to be reachable when it is first added, so a typo in
the host is caught at add time. Only the ongoing runtime tolerates an absent TV.

### 3. Entity state semantics

| Property | Before | After |
| --- | --- | --- |
| `available` | `tv.connected` | always `True` |
| `state` | `off` only when connected and a sleep marker is set | `off` when disconnected **or** a sleep marker is set; `on` otherwise |
| `volume_level`, `source`, `is_volume_muted` | last known value, stale | `None` / `False` while disconnected |

The remote entity gets the same treatment: `available` becomes always `True`, and its `is_on`
follows the same rule as the media player's `state` — false while disconnected.

`turn_on` remains callable while the TV is off — that is the point of the change. It fires
Wake-on-LAN and a power keypress; when the TV's MQTT broker comes up, `_on_connect` already
calls `refresh()`, which repopulates apps, sources, channels and device info without any
further work.

### 4. Canonical key list

`const.py` gains a `KEYS` tuple naming every key this firmware generation is known to
accept:

```
POWER SOURCE INPUTS HOME MENU BACK EXIT SETTINGS
UP DOWN LEFT RIGHT OK
VOLUMEUP VOLUMEDOWN MUTE
CHANNELUP CHANNELDOWN LIST FAV GUIDE EPG
0 1 2 3 4 5 6 7 8 9
PLAY PAUSE STOP FORWARDS BACKS RECORD
RED GREEN YELLOW BLUE
INFO SUBTITLE SLEEP PICTURE SOUND
NETFLIX YOUTUBE AMAZON
```

The TV ignores actions it does not implement, so listing a key absent from a given firmware
costs nothing. During implementation the list is probed against the real TV with
`test_vidaa.py` and any key that produces no response is removed.

### 5. `vidaa_tv.send_key` service

A new service makes the key set discoverable. `services.yaml` declares a `select` selector
listing `KEYS` with `custom_value: true`, so the dropdown guides the common case while any
string still passes through.

The voluptuous schema validates the key as `cv.string`, deliberately **not** `vol.In(KEYS)`.
A key must never be blocked merely because this integration has not heard of it.

The service takes the same optional `entry_id` as the existing services and resolves the
target through the existing `_resolve` helper.

### 6. Context-aware channel up/down

`VidaaTV` gains an `is_live_tv` property, true when either:

- the current source or app name matches a live-TV marker (`tv`, `live tv`, `atv`, `dtv`,
  `antenna`, `cable`, `tuner`), or
- the TV is reporting a current channel and no app is running.

The markers live in `const.py` as `LIVE_TV_MARKERS`, matched as case-insensitive substrings
in the same style as `OFF_STATE_MARKERS`.

`async_media_next_track` sends `KEY_CHANNELUP` when `is_live_tv` is true and `KEY_FORWARDS`
otherwise; `async_media_previous_track` sends `KEY_CHANNELDOWN` or `KEY_BACKS` on the same
condition. Home Assistant has no dedicated channel control, so the track buttons are the
only native home for this.

Numeric tuning already works through `play_media` with `media_type: channel`, which keys the
digits in the way the physical remote does. The digits also appear in the new dropdown.

## Testing

`test_vidaa.py` gains assert-based checks for the two pieces of real logic:

- **Key normalization**: `mute` → `KEY_MUTE`, `KEY_OK` → `KEY_OK`, `  volumeup  ` →
  `KEY_VOLUMEUP`.
- **`is_live_tv`**: true for a live-TV source name, true for a reported channel with no app,
  false while a named app is in the foreground, false when nothing is known.

No framework and no Home Assistant import — the file stays a standalone script runnable
against the TV or offline.

## Out of scope

- Button entities per key. `remote.send_command` and the new service cover both dashboards
  and automations; forty entities per TV would clutter every picker to save a few lines of
  card YAML.
- Any change to the config flow beyond leaving it as-is.
- Picture, sound or other settings beyond sending the corresponding key.

## Files touched

`const.py`, `client.py`, `__init__.py`, `media_player.py`, `remote.py`, `services.yaml`,
`translations/en.json`, `test_vidaa.py`, `README.md`.
