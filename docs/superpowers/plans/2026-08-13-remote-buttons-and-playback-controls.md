# Remote Buttons and Playback Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the remote's navigation keys, channel keys and number pad pressable from a Home Assistant dashboard, and make the media control card draw its playback row.

**Architecture:** A `BUTTONS` table in `const.py` names 21 curated keys with a display name and an mdi icon; a new `button.py` platform turns each row into a `ButtonEntity` whose press calls the existing `VidaaTV.send_key`. Separately, `VidaaMediaPlayer.state` changes from `ON` to `PLAYING` while the TV is awake, which is what makes Home Assistant's media control card render previous/play/pause/stop/next.

**Tech Stack:** Python 3.13, Home Assistant custom integration (button + media_player platforms), plain `assert`-based self-check script.

## Global Constraints

- **No test framework.** `test_vidaa.py` is a standalone script with a single `main()` full of `assert`s. Run it with `python test_vidaa.py`; it prints `all checks passed` on success. Do not introduce pytest, fixtures, or a `tests/` directory.
- **No Home Assistant import in tests.** `test_vidaa.py` loads only `const.py` and `client.py` via `importlib`, binding them as `client` and `const`. `button.py`, `media_player.py`, `__init__.py` and `remote.py` import Home Assistant and are NOT unit-testable here. Verify those by reading and by `python -m py_compile`.
- **Key normalization lives in one place:** `VidaaTV.send_key`. No button, service or entity re-implements the `KEY_` prefixing.
- **Never block a key.** `KEYS` is a discoverability list, never a whitelist. Nothing may validate a key against it at runtime. The `BUTTONS`-vs-`KEYS` check in Task 1 is a build-time consistency check on our own table, not runtime validation.
- **`const.KEYS` and the `services.yaml` dropdown are pinned equal and in order** by an existing check in `test_vidaa.py`. This plan does not change `KEYS` or `services.yaml` — leave both alone.
- **Entity conventions:** `_attr_has_entity_name = True`; unique ids built from `base = entry.unique_id or entry.entry_id`; device attachment via `DeviceInfo(identifiers={(DOMAIN, base)})`. Follow `remote.py` as the reference.
- **Entities stay available while the TV is off.** Do not add an `available` property to anything — `Entity.available` already defaults to `True`, and a disconnected TV reporting `off` is deliberate so `turn_on` stays callable.

---

### Task 1: The `BUTTONS` table

**Files:**
- Modify: `custom_components/vidaa_tv/const.py` (append after `KEYS`)
- Test: `test_vidaa.py`

**Interfaces:**
- Consumes: `const.KEYS`, which already exists.
- Produces: `const.BUTTONS: tuple[tuple[str, str, str], ...]` — 21 rows of `(key, display_name, icon)`, where `key` is a full `KEY_`-prefixed name present in `KEYS`, and `icon` is an `mdi:` name.

- [ ] **Step 1: Write the failing test**

In `test_vidaa.py`, inside `main()`, immediately before the `services.yaml` dropdown check near the end, add:

```python
    # The button table drives one entity each; a typo here is a dead button.
    keys = [key for key, _name, _icon in const.BUTTONS]
    names = [name for _key, name, _icon in const.BUTTONS]
    icons = [icon for _key, _name, icon in const.BUTTONS]
    assert len(const.BUTTONS) == 21, len(const.BUTTONS)
    assert set(keys) <= set(const.KEYS), sorted(set(keys) - set(const.KEYS))
    assert len(set(keys)) == len(keys), "duplicate key in BUTTONS"
    # Duplicate names would collide into the same entity id.
    assert len(set(names)) == len(names), "duplicate name in BUTTONS"
    assert all(icon.startswith("mdi:") for icon in icons), icons
    for digit in "0123456789":
        assert f"KEY_{digit}" in keys, digit
    assert "KEY_CHANNELUP" in keys and "KEY_CHANNELDOWN" in keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_vidaa.py`
Expected: `AttributeError: module 'vt.const' has no attribute 'BUTTONS'`

- [ ] **Step 3: Add the table**

In `custom_components/vidaa_tv/const.py`, append after the closing `)` of `KEYS`:

```python
# The keys worth a dashboard button, as (key, display name, icon). A curated
# subset of KEYS on purpose: one entity per key across all 52 would clutter
# every entity picker to serve keys nobody puts on a card. Everything else
# stays reachable through the send_key service and remote.send_command.
BUTTONS = (
    ("KEY_UP", "Up", "mdi:arrow-up"),
    ("KEY_DOWN", "Down", "mdi:arrow-down"),
    ("KEY_LEFT", "Left", "mdi:arrow-left"),
    ("KEY_RIGHT", "Right", "mdi:arrow-right"),
    ("KEY_OK", "OK", "mdi:check-circle-outline"),
    ("KEY_BACK", "Back", "mdi:arrow-u-left-top"),
    ("KEY_HOME", "Home", "mdi:home"),
    ("KEY_MENU", "Menu", "mdi:menu"),
    ("KEY_EXIT", "Exit", "mdi:exit-to-app"),
    ("KEY_CHANNELUP", "Channel up", "mdi:chevron-up-box"),
    ("KEY_CHANNELDOWN", "Channel down", "mdi:chevron-down-box"),
    ("KEY_0", "0", "mdi:numeric-0"),
    ("KEY_1", "1", "mdi:numeric-1"),
    ("KEY_2", "2", "mdi:numeric-2"),
    ("KEY_3", "3", "mdi:numeric-3"),
    ("KEY_4", "4", "mdi:numeric-4"),
    ("KEY_5", "5", "mdi:numeric-5"),
    ("KEY_6", "6", "mdi:numeric-6"),
    ("KEY_7", "7", "mdi:numeric-7"),
    ("KEY_8", "8", "mdi:numeric-8"),
    ("KEY_9", "9", "mdi:numeric-9"),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_vidaa.py`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add custom_components/vidaa_tv/const.py test_vidaa.py
git commit -m "Add the button table naming the keys worth a dashboard button"
```

---

### Task 2: The `button` platform

**Files:**
- Create: `custom_components/vidaa_tv/button.py`
- Modify: `custom_components/vidaa_tv/__init__.py` (the `PLATFORMS` list)
- Test: `test_vidaa.py` (regression run only — `button.py` imports Home Assistant)

**Interfaces:**
- Consumes: `const.BUTTONS` from Task 1; `const.DOMAIN`; `VidaaTV.send_key(key: str)`, which already normalizes the `KEY_` prefix; `hass.data[DOMAIN][entry.entry_id]`, which holds the `VidaaTV` instance.
- Produces: `VidaaButton`, one entity per `BUTTONS` row, with unique id `f"{base}_key_{key}"`.

- [ ] **Step 1: Create the platform**

Create `custom_components/vidaa_tv/button.py` with exactly this content:

```python
"""Button entities for the keys people actually put on a dashboard.

Every key is already reachable through remote.send_command and the send_key
service. These exist because a service call is not a control: a button entity
lands on the device page and drags onto a dashboard with no YAML.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import VidaaTV
from .const import BUTTONS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one button per curated key."""
    tv = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        VidaaButton(tv, entry, key, name, icon) for key, name, icon in BUTTONS
    )


class VidaaButton(ButtonEntity):
    """One remote key, pressable from a dashboard."""

    _attr_has_entity_name = True

    def __init__(
        self, tv: VidaaTV, entry: ConfigEntry, key: str, name: str, icon: str
    ) -> None:
        self._tv = tv
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base}_key_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, base)})

    async def async_press(self) -> None:
        # send_key is the one place that normalises key names, and the client
        # logs a press that could not be delivered rather than dropping it
        # silently, so a press while the TV is off is honest about failing.
        await self.hass.async_add_executor_job(self._tv.send_key, self._key)
```

A button carries no state, so it needs no listener registration and no `available` override — the default `True` is what keeps it pressable while the TV is off, matching the other entities.

- [ ] **Step 2: Register the platform**

In `custom_components/vidaa_tv/__init__.py`, change:

```python
PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE]
```

to:

```python
PLATFORMS = [Platform.BUTTON, Platform.MEDIA_PLAYER, Platform.REMOTE]
```

`async_unload_entry` already unloads whatever is in `PLATFORMS`, so teardown needs no change.

- [ ] **Step 3: Verify it compiles and nothing regressed**

Run:

```bash
python -m py_compile custom_components/vidaa_tv/button.py custom_components/vidaa_tv/__init__.py
python test_vidaa.py
```

Expected: no output from `py_compile` (exit 0), then `all checks passed`.

- [ ] **Step 4: Commit**

```bash
git add custom_components/vidaa_tv/button.py custom_components/vidaa_tv/__init__.py
git commit -m "Add a button entity per curated remote key"
```

---

### Task 3: Playback controls on the media card, docs, and version

**Files:**
- Modify: `custom_components/vidaa_tv/media_player.py` (the `state` property, around line 115)
- Modify: `README.md`
- Modify: `custom_components/vidaa_tv/manifest.json`
- Test: `test_vidaa.py` (regression run only)

**Interfaces:**
- Consumes: `VidaaTV.is_on`, unchanged.
- Produces: no new symbols. `VidaaMediaPlayer.state` now returns `MediaPlayerState.PLAYING` where it previously returned `MediaPlayerState.ON`.

- [ ] **Step 1: Report `playing` while awake**

In `custom_components/vidaa_tv/media_player.py`, replace:

```python
    def state(self) -> MediaPlayerState:
        # is_on already requires a live connection.
        return MediaPlayerState.ON if self._tv.is_on else MediaPlayerState.OFF
```

with:

```python
    def state(self) -> MediaPlayerState:
        # PLAYING rather than ON so the media control card draws its playback
        # row — previous/play/pause/stop/next, which is where channel up/down
        # lives. The TV reports no play/pause distinction, so every awake state
        # is PLAYING. is_on already requires a live connection.
        return MediaPlayerState.PLAYING if self._tv.is_on else MediaPlayerState.OFF
```

`MediaPlayerState` is already imported. `MediaPlayerState.ON` becomes unused in this file — confirm no other reference to it remains before committing.

- [ ] **Step 2: Verify it compiles and nothing regressed**

Run:

```bash
python -m py_compile custom_components/vidaa_tv/media_player.py
python test_vidaa.py
grep -n "MediaPlayerState.ON" custom_components/vidaa_tv/media_player.py
```

Expected: no output from `py_compile` (exit 0), `all checks passed`, and no output from `grep` (exit 1) — proving no stale `ON` reference survives.

- [ ] **Step 3: Document the buttons in the README**

In `README.md`, under `## Features`, add this bullet to the existing list:

```markdown
- A button entity per remote key worth pressing — arrows, OK, back, home, menu,
  exit, channel up/down and the digits 0-9. They appear on the device page with
  no YAML and drag straight onto a dashboard.
```

Then, in the `## Services` section, insert this subsection immediately before `### vidaa_tv.send_key`:

````markdown
### Buttons

Twenty-one keys are exposed as button entities, so a number pad and channel
controls can go on a dashboard without writing service calls:

| Group | Buttons |
| --- | --- |
| Navigation | Up, Down, Left, Right, OK |
| Return and menu | Back, Home, Menu, Exit |
| Channel | Channel up, Channel down |
| Digits | 0 – 9 |

They are named `button.<your_tv>_up`, `button.<your_tv>_channel_up`,
`button.<your_tv>_5` and so on, and are listed on the device page. Every other
key stays available through `vidaa_tv.send_key` and `remote.send_command`.
````

- [ ] **Step 4: Document the breaking state change**

In `README.md`, add a new section immediately before `## Caveats`:

````markdown
## Upgrading to 2.4.0

**Breaking:** the media player now reports `playing` instead of `on` while the
TV is awake. This is what makes Home Assistant's media control card draw the
playback row — previous, play, pause, stop, next — which is where channel
up/down lives while watching broadcast TV.

Any automation, script or template testing `state == 'on'` against
`media_player.<your_tv>` needs updating:

```yaml
# before
condition: state
entity_id: media_player.living_room_tv
state: "on"

# after — either match the new state
condition: state
entity_id: media_player.living_room_tv
state: playing

# or key off the remote entity, which still reports on/off
condition: state
entity_id: remote.living_room_tv_remote
state: "on"
```

`off` is unchanged, so anything checking for `off` keeps working.
````

- [ ] **Step 5: Bump the version**

In `custom_components/vidaa_tv/manifest.json`, change:

```json
  "version": "2.3.0"
```

to:

```json
  "version": "2.4.0"
```

- [ ] **Step 6: Final verification**

Run:

```bash
python test_vidaa.py
python -m py_compile custom_components/vidaa_tv/*.py
python -c "import json,pathlib; d=json.loads(pathlib.Path('custom_components/vidaa_tv/manifest.json').read_text()); print(d['version'])"
```

Expected: `all checks passed`, no output from `py_compile`, then `2.4.0`.

- [ ] **Step 7: Commit**

```bash
git add custom_components/vidaa_tv/media_player.py custom_components/vidaa_tv/manifest.json README.md
git commit -m "Report playing so the card shows playback controls, bump to 2.4.0"
```

---

## Notes for the implementer

**What cannot be verified here.** `button.py`, `media_player.py` and `__init__.py` import Home Assistant, which is not installed in this repo. `python -m py_compile` catches syntax errors and nothing more. Two things need a running Home Assistant and the physical TV, and are the human's to check after install:

1. The 21 buttons appear on the device page, and pressing a digit or channel button moves the TV.
2. The media control card now shows previous/play/pause/stop/next, and previous/next change channel while on a broadcast channel.

**Icon names.** The mdi names in `BUTTONS` are checked only for the `mdi:` prefix, not for existence — Home Assistant renders an unknown icon as a blank square rather than erroring. If any button shows blank in the UI, the icon name is wrong and the fix is a one-line edit to that row.

**Why `MediaPlayerState.PLAYING` and not a feature flag.** `NEXT_TRACK` and `PREVIOUS_TRACK` are already declared in `SUPPORT` and always have been. The card hides them purely on state, so the state is the only lever.
