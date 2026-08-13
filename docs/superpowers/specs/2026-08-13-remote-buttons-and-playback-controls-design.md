# VIDAA TV: remote buttons and playback controls

Date: 2026-08-13

## Problem

Version 2.3.0 exposed the full key set through a `vidaa_tv.send_key` service with a UI
dropdown. That made the keys *discoverable* but not *pressable*: a service call is not a
dashboard control, so a number pad and channel buttons still cannot be put on a card.

Two concrete gaps the user reported:

1. **No number buttons, no channel buttons.** Nothing exists to place on a dashboard. The
   2.3.0 design chose a service dropdown over button entities; that was the wrong call for
   the stated goal of having every remote feature available.
2. **Next/Previous do not appear on the media control card.** The features are declared in
   `media_player.py`, but Home Assistant's media control card only draws the playback row
   for a playing-like state. The entity reports `on`, so the row stays hidden.

## Design

### 1. A `button` platform

`const.py` gains a `BUTTONS` table mapping each key to a display name and an icon.
`button.py` turns each row into one entity. Twenty-one buttons:

| Group | Keys |
| --- | --- |
| Navigation | Up, Down, Left, Right, OK |
| Return and menu | Back, Home, Menu, Exit |
| Channel | Channel up, Channel down |
| Digits | 0, 1, 2, 3, 4, 5, 6, 7, 8, 9 |

This is a curated subset, not the whole of `KEYS`. The remaining keys — colours, app
launchers, picture and sound settings — stay reachable through `vidaa_tv.send_key` and
`remote.send_command`. Fifty-two entities per TV would clutter every entity picker to serve
keys nobody puts on a dashboard.

Each entity uses `_attr_has_entity_name` with the display name, producing ids like
`button.living_room_tv_channel_up` and `button.living_room_tv_5`. Unique ids follow the
existing convention: `f"{base}_key_{KEY_NAME}"`, where `base` is `entry.unique_id or
entry.entry_id`. They attach to the existing device via the same
`DeviceInfo(identifiers={(DOMAIN, base)})`, so they appear on the device page with no YAML
and drag onto any dashboard.

Each row carries an mdi icon (`mdi:arrow-up`, `mdi:numeric-5`, `mdi:television-guide`) so a
grid of them reads as a remote rather than a list of words.

`async_press` calls `tv.send_key(key)` — the same single normalization path every other
caller uses. No button re-implements the `KEY_` prefix.

Buttons stay available while the TV is off, matching the media player and remote entities.
A press in that state is logged as undelivered by the existing `_publish` wrapper rather
than silently dropped.

### 2. Media player sets `assumed_state`

`VidaaMediaPlayer` gains `_attr_assumed_state = True`. `state` is unchanged: it still returns
`MediaPlayerState.ON` when the TV is awake and `MediaPlayerState.OFF` otherwise.

Home Assistant's media control card draws the previous/next transport buttons whenever
`assumed_state` is true, regardless of the reported state — and in that branch it renders
play, pause and stop as three separate buttons plus a power button, rather than the single
context-dependent toggle it draws for a normal state. So `assumed_state` produces the fuller
transport row without touching `state` at all. Since 2.3.0 the track buttons already send
channel down/up while `is_live_tv` is true, so this is what puts channel control on the card
itself.

This is also the more truthful model. The TV reports no distinction between playing and
paused, and every command goes out fire-and-forget at QoS 0 with no acknowledgement, so the
entity never actually knows what the TV is doing — it can only assume. `assumed_state` says
so directly instead of picking a specific playback state to stand in for that ignorance.

No breaking change. `state` still reports `on`/`off` exactly as before 2.4.0, so every
automation, script and template testing `state == 'on'` against `media_player.<tv>` keeps
working unmodified.

## Testing

`test_vidaa.py` gains checks on the `BUTTONS` table, which is the only new logic reachable
without Home Assistant:

- every key in `BUTTONS` also exists in `KEYS`, so no button sends a key the integration
  does not otherwise know about
- no duplicate keys and no duplicate display names, either of which would collide entity ids
- all ten digits are present

`button.py` imports Home Assistant and is therefore not unit-testable in this repo, the same
as `media_player.py` and `remote.py`. Its correctness rests on the table it consumes being
verified and on a manual check in Home Assistant.

## Out of scope

- Button entities for the remaining keys in `KEYS`.
- A prebuilt dashboard card or Lovelace YAML. The device page and manual card composition
  cover it.
- Distinguishing `paused` from `playing`.

## Files touched

`const.py`, `button.py` (new), `__init__.py` (add `Platform.BUTTON`), `media_player.py`,
`test_vidaa.py`, `README.md`, `manifest.json` (version 2.4.0).
