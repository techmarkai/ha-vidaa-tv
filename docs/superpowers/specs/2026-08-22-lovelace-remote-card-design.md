# Lovelace remote card

An interactive remote in the dashboard, laid out after the Toshiba CT-8547
handset these TVs ship with, installed by the integration itself.

## Why

The integration exposes 21 button entities and a `remote` entity, but building a
usable remote out of them means hand-assembling a grid card and remembering
which key code does what. The handset already solves that layout problem, and
the muscle memory for it is already in the user's thumb.

## Decisions

**Faithful layout, own styling.** Button positions and groupings copy the
handset so it is recognisable at a glance. The styling does not: it uses Home
Assistant theme variables, so the card follows light and dark dashboards. The
handset's black shell, Toshiba wordmark and CT-8547 model text are deliberately
not reproduced — shipping another company's trademarks in a public repository
is a risk the card does not need to take, and a fixed dark shell looks wrong on
a light dashboard.

**Keys go out over `remote.send_command`.** The obvious alternative,
`vidaa_tv.send_key`, targets a *config entry* via `entry_id`. A card is placed
against an entity, so with two TVs configured `send_key` could not tell them
apart without the user finding an entry id by hand. `remote.send_command` takes
`entity_id` directly, `remote.py` already implements it, and no new backend code
is needed.

**The integration serves its own card.** `async_setup_entry` registers a static
path at `/vidaa_tv/vidaa-remote-card.js` and calls `add_extra_js_url`, so the
card loads with no Lovelace resource to add by hand — "installs with the
integration", which is the point. Registration is guarded by a flag in
`hass.data`, because registering the same static path twice raises and a
duplicate script URL fetches the card twice.

That flag lives under its own `hass.data` key, *not* inside `hass.data[DOMAIN]`.
That dict maps `entry_id` to `VidaaTV`, and `_resolve()` both counts and
iterates it — a flag parked in there would read as a second TV and break every
single-TV service call.

**Availability, not connectivity.** Buttons grey out only when the remote entity
is `unavailable`. They deliberately do not track the MQTT link: this firmware
drops the session every ~271s and `link_ok` keeps entities available across the
~22s gap, so binding the buttons to the socket would grey the whole card out
roughly eleven times an hour for no reason.

## Layout

Top to bottom, after the handset: source and power; picture and sound mode and
info; apps, media and TV; the numeric keypad with menu and teletext; volume,
list, home and channel; back and exit; the direction pad with OK; guide and
subtitle; the four colour keys; two rows of transport controls; Netflix and
YouTube.

Two deviations, both forced by the medium:

- The handset's volume and channel **rockers** are single physical keys. A card
  has no rocker, so each becomes two buttons in the same position.
- `GUIDE` and `SUBTITLE` sit below the direction pad rather than flanking it,
  which keeps the grid to three even columns.

## Unverified key codes

Five buttons on the handset have no key code confirmed against a real TV:
`KEY_TEXT`, `KEY_APPS`, `KEY_MEDIA`, `KEY_PREVIOUS`, `KEY_NEXT`. They follow the
VIDAA naming pattern and are listed in `const.KEYS` with a comment saying so.

This firmware silently ignores actions it does not implement, so a wrong guess
does nothing rather than erroring — the failure mode is a dead button, not a
broken card. Each must be pressed against the TV and any that stay dead removed
from both the card and `KEYS`.

## Testing

The card is browser JavaScript the self-check cannot execute, so the check
pins the parts that fail silently:

- every `KEY_*` code the card sends exists in `const.KEYS`, so a typo is caught
  at commit time rather than becoming a button that quietly does nothing
- the custom element is defined and pushed to `window.customCards`, or Lovelace
  never finds the card
- the card calls `remote.send_command`, guarding the entity-targeting decision
  above against a future refactor back to `send_key`

Everything else — that it renders, that presses reach the TV — is verified in
the real dashboard.

## Files

| File | Change |
| --- | --- |
| `www/vidaa-remote-card.js` | new — the card |
| `__init__.py` | serve the static path, load the script, guard flag |
| `const.py` | five handset key codes, marked unverified |
| `services.yaml` | same five in the `send_key` dropdown |
| `manifest.json` | `frontend` and `http` dependencies |
| `test_vidaa.py` | card/`KEYS` sync checks |
