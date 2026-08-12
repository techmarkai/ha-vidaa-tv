# Offline Tolerance and Full Key Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the VIDAA TV integration survive the TV being switched off without a manual reload, and expose the full remote key set through a discoverable service.

**Architecture:** Connection setup becomes fire-and-forget — `connect_async()` plus `loop_start()`, with paho owning a flat 30-second retry loop, so `async_setup_entry` never raises `ConfigEntryNotReady`. Entities stay available at all times and report `off` while disconnected, which keeps `turn_on` (Wake-on-LAN) callable. A canonical `KEYS` tuple in `const.py` feeds a new `vidaa_tv.send_key` service with a UI dropdown, and a new `is_live_tv` property on the client makes the media player's track buttons act as channel up/down while watching broadcast TV.

**Tech Stack:** Python 3.13, Home Assistant custom integration, paho-mqtt (1.x and 2.x compatible), voluptuous schemas, plain `assert`-based self-check script.

## Global Constraints

- **No test framework.** `test_vidaa.py` is a standalone script with a single `main()` full of `assert`s. Run it with `python test_vidaa.py`; it prints `all checks passed` on success. Do not introduce pytest, fixtures, or a `tests/` directory.
- **No Home Assistant import in tests.** `test_vidaa.py` loads `const.py` and `client.py` directly via `importlib`. Only logic that lives in those two files is unit-testable. Changes to `__init__.py`, `media_player.py` and `remote.py` are verified by running the self-check (to prove nothing regressed) plus a manual check in Home Assistant.
- **paho-mqtt must stay 1.x/2.x compatible.** Use the existing `_new_client` helper; do not import from `paho.mqtt.enums` at module level.
- **Never block a key.** Key validation is `cv.string` everywhere. `KEYS` is a discoverability list, never a whitelist.
- **Key normalization lives in one place:** `VidaaTV.send_key`. No caller re-implements the `KEY_` prefixing.
- **Marker tuples** in `const.py` are lowercase and matched case-insensitively, like the existing `OFF_STATE_MARKERS`. Note the one difference: `OFF_STATE_MARKERS` matches as substrings, `LIVE_TV_MARKERS` matches exactly — `"tv"` as a substring would wrongly match app names like "Apple TV".

---

### Task 1: Canonical key list and live-TV detection

**Files:**
- Modify: `custom_components/vidaa_tv/const.py`
- Modify: `custom_components/vidaa_tv/client.py:130-133` (next to the existing `is_on` property)
- Test: `test_vidaa.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `const.KEYS: tuple[str, ...]` — full key names including the `KEY_` prefix.
  - `const.LIVE_TV_MARKERS: tuple[str, ...]` — lowercase source names that mean broadcast TV.
  - `VidaaTV.is_live_tv -> bool` — property, no arguments.

- [ ] **Step 1: Write the failing test**

In `test_vidaa.py`, inside `main()`, immediately after the existing `is_on` block (the one ending with `assert not tv.is_on` around line 132), add:

```python
    # Live TV detection drives which keys the track buttons send.
    def live(state_type, name, channel=None):
        tv.state_type, tv.current_name, tv.current_channel = state_type, name, channel
        return tv.is_live_tv

    assert live("livetv", "BBC One")
    assert live("live_tv", None)
    assert live("sourceswitch", "TV")
    assert live("sourceswitch", " tv ")
    assert live("sourceswitch", "DTV")
    assert not live("app", "netflix")
    assert not live("app", "Apple TV")          # an app whose name ends in "TV"
    assert not live("sourceswitch", "HDMI1")
    assert not live(None, None)
    assert live(None, None, {"channel_num": "104"})

    # The key list is a discoverability aid, not a whitelist.
    assert "KEY_CHANNELUP" in const.KEYS and "KEY_CHANNELDOWN" in const.KEYS
    assert all(k.startswith("KEY_") for k in const.KEYS), const.KEYS
    assert len(set(const.KEYS)) == len(const.KEYS), "duplicate key"
    for digit in "0123456789":
        assert f"KEY_{digit}" in const.KEYS
```

`const` is not yet in scope in this file. Add it next to the existing `client = _load()` line near the top, so both modules `_load()` already put in `sys.modules` are reachable:

```python
client = _load()
const = sys.modules["vt.const"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_vidaa.py`
Expected: `AttributeError: 'VidaaTV' object has no attribute 'is_live_tv'`

- [ ] **Step 3: Add the constants**

In `custom_components/vidaa_tv/const.py`, append after `OFF_STATE_MARKERS`:

```python
# Source names that mean broadcast TV rather than an app or an HDMI input.
# Matched exactly (after strip/lower), not as substrings, because "tv" as a
# substring would also match app names like "Apple TV".
LIVE_TV_MARKERS = ("tv", "live tv", "livetv", "atv", "dtv", "antenna", "cable", "tuner")

# Every key this firmware generation is known to accept. The TV silently
# ignores actions it does not implement, so listing a key a given model lacks
# costs nothing. This exists to populate the send_key dropdown — it is NOT a
# whitelist, and any string is still passed through.
KEYS = (
    "KEY_POWER", "KEY_SOURCE", "KEY_INPUT", "KEY_TV",
    "KEY_HOME", "KEY_MENU", "KEY_BACK", "KEY_RETURNS", "KEY_EXIT", "KEY_SETTINGS",
    "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_OK",
    "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE",
    "KEY_CHANNELUP", "KEY_CHANNELDOWN", "KEY_LIST", "KEY_FAV", "KEY_GUIDE", "KEY_EPG",
    "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
    "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9",
    "KEY_PLAY", "KEY_PAUSE", "KEY_STOP", "KEY_FORWARDS", "KEY_BACKS", "KEY_RECORD",
    "KEY_RED", "KEY_GREEN", "KEY_YELLOW", "KEY_BLUE",
    "KEY_INFO", "KEY_SUBTITLE", "KEY_AUDIO", "KEY_SLEEP", "KEY_PICTURE", "KEY_SOUND",
    "KEY_NETFLIX", "KEY_YOUTUBE", "KEY_AMAZON",
)
```

- [ ] **Step 4: Add the property**

In `custom_components/vidaa_tv/client.py`, extend the existing import at line 20 to bring in `LIVE_TV_MARKERS`:

```python
from .const import (
    CLIENT_ID,
    DEFAULT_PORT,
    LIVE_TV_MARKERS,
    MQTT_PASSWORD,
    MQTT_USERNAME,
    OFF_STATE_MARKERS,
)
```

`KEYS` is deliberately **not** imported here — `client.py` has no use for it. Its consumers are `__init__.py` (Task 4) and `test_vidaa.py`, both of which read it from `const` directly.

Then add the property in `client.py` directly below the existing `is_on` property:

```python
    @property
    def is_live_tv(self) -> bool:
        """True when the foreground is broadcast TV rather than an app or input.

        Decides whether the media player's track buttons mean channel up/down
        or fast-forward/rewind.
        """
        state = (self.state_type or "").lower()
        if "livetv" in state or "live_tv" in state:
            return True
        if (self.current_name or "").strip().lower() in LIVE_TV_MARKERS:
            return True
        if state or self.current_name:
            # The TV told us it is on something else — an app or an input.
            return False
        # Nothing known yet; a reported channel is the only remaining evidence.
        return self.current_channel is not None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python test_vidaa.py`
Expected: `all checks passed`

- [ ] **Step 6: Commit**

```bash
git add custom_components/vidaa_tv/const.py custom_components/vidaa_tv/client.py test_vidaa.py
git commit -m "Add a canonical key list and live-TV detection"
```

---

### Task 2: Non-blocking connect with a flat 30s retry

**Files:**
- Modify: `custom_components/vidaa_tv/client.py:118-126` (constructor), `:309-331` (lifecycle)
- Test: `test_vidaa.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `VidaaTV.async_start()` — still `async`, now returns immediately and **never raises**. `VidaaTV._connect_and_verify` is deleted; nothing may call it.

- [ ] **Step 1: Write the failing test**

Add `import asyncio` to the imports at the top of `test_vidaa.py`. Then, at the end of `main()` just before `print("all checks passed")`, add:

```python
    # Startup must not block on the TV. connect_async performs no I/O, so a
    # TV that is off or unplugged costs nothing at setup time.
    calls = []
    offline = client.VidaaTV(FakeHass(), "10.0.0.9")
    offline._client.connect_async = lambda h, p, k: calls.append(("connect", h, p, k))
    offline._client.loop_start = lambda: calls.append(("loop",))
    asyncio.run(offline.async_start())
    assert calls == [("connect", "10.0.0.9", 36669, 30), ("loop",)], calls

    # The blocking verify path is gone; nothing may still reference it.
    assert not hasattr(offline, "_connect_and_verify")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_vidaa.py`
Expected: `AssertionError` on the `calls == [...]` line (the current `async_start` calls `connect`, not `connect_async`), or on the `hasattr` line.

- [ ] **Step 3: Change the retry cadence**

In `custom_components/vidaa_tv/client.py`, in `__init__`, replace:

```python
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
```

with:

```python
        # Flat 30s, no backoff: a TV switched back on appears within 30 seconds
        # instead of waiting out a growing delay. One cheap LAN connect per 30s.
        self._client.reconnect_delay_set(min_delay=30, max_delay=30)
```

Also delete these two now-unused lines from `__init__`:

```python
        self._connack: int | None = None
        self._answered = threading.Event()
```

And in `_on_connect`, delete these two lines:

```python
        self._connack = rc
        self._answered.set()
```

- [ ] **Step 4: Replace the lifecycle methods**

In `custom_components/vidaa_tv/client.py`, replace the whole `async_start` / `_connect_and_verify` pair with:

```python
    async def async_start(self) -> None:
        """Begin connecting. Returns immediately and never raises.

        connect_async only records the address — no I/O happens here — and the
        network thread retries every 30s forever. A TV that is off is a normal
        state, not a setup failure, so nothing here reports one.
        """
        self._client.connect_async(self.host, self.port, 30)
        self._client.loop_start()
```

`threading` is still used by `test_connection`, so leave that import alone.

- [ ] **Step 5: Run test to verify it passes**

Run: `python test_vidaa.py`
Expected: `all checks passed`

- [ ] **Step 6: Commit**

```bash
git add custom_components/vidaa_tv/client.py test_vidaa.py
git commit -m "Connect without blocking and retry at a flat 30s"
```

---

### Task 3: Setup never fails, entities never go unavailable

**Files:**
- Modify: `custom_components/vidaa_tv/__init__.py:17` (import), `:48-73` (setup)
- Modify: `custom_components/vidaa_tv/media_player.py:80-107`
- Modify: `custom_components/vidaa_tv/remote.py:43-45`
- Test: `test_vidaa.py` (regression run only — these files cannot be imported without Home Assistant)

**Interfaces:**
- Consumes: `VidaaTV.async_start()` from Task 2, which no longer raises.
- Produces: no new symbols. `VidaaError` is no longer imported by `__init__.py`.

- [ ] **Step 1: Make setup unconditional**

In `custom_components/vidaa_tv/__init__.py`, change the import on line 17 from:

```python
from .client import VidaaError, VidaaTV
```

to:

```python
from .client import VidaaTV
```

Then replace the try/except block in `async_setup_entry`:

```python
    # async_start verifies the CONNACK on the connection it already opens, so a
    # firewall or a sleeping TV fails here with a reason instead of sitting in a
    # silent reconnect loop.
    tv = VidaaTV(hass, host, port, entry.data.get(CONF_MAC))
    try:
        await tv.async_start()
    except VidaaError as err:
        raise ConfigEntryNotReady(f"Cannot reach VIDAA TV at {host}:{port}: {err}") from err
```

with:

```python
    # Setup never fails on an unreachable TV. A TV that is off, unplugged or
    # behind a dead switch is a normal state, not a broken config entry — the
    # client retries in the background and the entities report "off" meanwhile.
    tv = VidaaTV(hass, host, port, entry.data.get(CONF_MAC))
    await tv.async_start()
```

Then remove `ConfigEntryNotReady` from the exceptions import on line 13, leaving:

```python
from homeassistant.exceptions import ServiceValidationError
```

- [ ] **Step 2: Correct the now-stale watchdog comment**

Still in `custom_components/vidaa_tv/__init__.py`, the comment above `WATCHDOG_INTERVAL` justifies 90 seconds against paho's old 60-second maximum backoff, which Task 2 replaced with a flat 30. Replace:

```python
# Longer than paho's own 60s max backoff, so the watchdog only ever fires when
# paho's retry loop has genuinely stopped rather than racing it every tick.
WATCHDOG_INTERVAL = timedelta(seconds=90)
```

with:

```python
# Comfortably longer than paho's flat 30s retry, so the watchdog only fires
# when paho's retry loop has genuinely stopped rather than racing it. Its one
# job is a network thread that died or wedged; ordinary reconnects are paho's.
WATCHDOG_INTERVAL = timedelta(seconds=90)
```

- [ ] **Step 3: Keep the media player available while the TV is off**

In `custom_components/vidaa_tv/media_player.py`, delete the `available` property entirely (the default is `True`):

```python
    @property
    def available(self) -> bool:
        return self._tv.connected
```

Then replace the three state properties below it so stale values are not reported while disconnected:

```python
    @property
    def volume_level(self) -> float | None:
        if not self._tv.connected or self._tv.volume is None:
            return None
        return self._tv.volume / 100

    @property
    def is_volume_muted(self) -> bool:
        return self._tv.connected and self._tv.muted

    @property
    def source(self) -> str | None:
        return self._tv.current_name if self._tv.connected else None
```

The `state` property already reads correctly — `is_on` requires `self.connected`, so a disconnected TV reports `MediaPlayerState.OFF` with no change needed.

- [ ] **Step 5: Same for the remote entity**

In `custom_components/vidaa_tv/remote.py`, delete the `available` property:

```python
    @property
    def available(self) -> bool:
        return self._tv.connected
```

`is_on` already returns `self._tv.is_on`, which is false while disconnected. Leave it.

- [ ] **Step 6: Run the self-check for regressions**

Run: `python test_vidaa.py`
Expected: `all checks passed`

- [ ] **Step 7: Verify against the real TV**

This is the behaviour the whole plan exists for, and no unit test can prove it. Copy `custom_components/vidaa_tv/` to the Home Assistant config directory, restart Home Assistant, then:

1. With the TV **off**, confirm the integration page shows the device as configured — **not** "Failed to set up" or "Retrying setup".
2. Confirm `media_player.<your_tv>` exists with state `off`, not `unavailable`.
3. Switch the TV on with its physical remote. Within 30 seconds the state must flip to `on` without any reload.
4. Switch the TV off. The state must return to `off` and stay there.
5. Restart Home Assistant while the TV is **off**, then switch the TV on. It must come up within 30 seconds with no reload.

- [ ] **Step 8: Commit**

```bash
git add custom_components/vidaa_tv/__init__.py custom_components/vidaa_tv/media_player.py custom_components/vidaa_tv/remote.py
git commit -m "Treat a powered-off TV as off rather than a setup failure"
```

---

### Task 4: The `vidaa_tv.send_key` service

**Files:**
- Modify: `custom_components/vidaa_tv/__init__.py:18` (import), `:28` (`SERVICE_NAMES`), `:30-45` (schemas), `:127-138` (handlers and registration)
- Modify: `custom_components/vidaa_tv/services.yaml`
- Modify: `custom_components/vidaa_tv/translations/en.json`

**Interfaces:**
- Consumes: `const.KEYS` from Task 1; `VidaaTV.send_key(key: str)` which already normalizes the `KEY_` prefix.
- Produces: service `vidaa_tv.send_key` with fields `key` (required string) and `entry_id` (optional string).

- [ ] **Step 1: Add the schema and the service name**

In `custom_components/vidaa_tv/__init__.py`, change the const import on line 18 to include `KEYS`:

```python
from .const import CONF_MAC, DEFAULT_PORT, DOMAIN, KEYS, SERVICES
```

Change `SERVICE_NAMES` on line 28 to:

```python
SERVICE_NAMES = ("publish", "send_key", "send_text", "refresh")
```

Add this schema next to `SEND_TEXT_SCHEMA`:

```python
# cv.string, deliberately not vol.In(KEYS): KEYS drives the UI dropdown, but a
# key must never be blocked just because this integration has not heard of it.
SEND_KEY_SCHEMA = vol.Schema(
    {
        vol.Required("key"): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)
```

- [ ] **Step 2: Add the handler and register it**

In `_async_register_services`, add this handler next to `_send_text`:

```python
    async def _send_key(call: ServiceCall) -> None:
        tv = _resolve(call)
        await hass.async_add_executor_job(tv.send_key, call.data["key"])
```

And register it alongside the others:

```python
    hass.services.async_register(DOMAIN, "send_key", _send_key, SEND_KEY_SCHEMA)
```

Then update the docstring of `_async_register_services`, which currently claims key sending is deliberately absent. Replace:

```python
    """Register the raw-protocol services once.

    Key sending is deliberately not a service here — remote.send_command on the
    remote entity is the Home Assistant native way, and supports targeting,
    repeats and delays for free.
    """
```

with:

```python
    """Register the raw-protocol services once.

    send_key exists for discoverability — its dropdown lists every known key.
    remote.send_command on the remote entity remains the richer path: it takes
    a sequence of keys with repeats and delays, and supports entity targeting.
    """
```

- [ ] **Step 3: Document the service for the UI**

In `custom_components/vidaa_tv/services.yaml`, insert this block between `publish` and `send_text`:

```yaml
send_key:
  name: Send key
  description: >-
    Send a single remote key to the TV. The dropdown lists every key VIDAA
    remotes are known to send, but any value is accepted — the TV silently
    ignores keys it does not implement, so experimenting is safe. The KEY_
    prefix is optional. For sequences with repeats and delays, use
    remote.send_command on the remote entity instead.
  fields:
    key:
      name: Key
      description: The key to send, for example KEY_CHANNELUP.
      required: true
      example: KEY_CHANNELUP
      selector:
        select:
          custom_value: true
          mode: dropdown
          options:
            - KEY_POWER
            - KEY_SOURCE
            - KEY_INPUT
            - KEY_TV
            - KEY_HOME
            - KEY_MENU
            - KEY_BACK
            - KEY_RETURNS
            - KEY_EXIT
            - KEY_SETTINGS
            - KEY_UP
            - KEY_DOWN
            - KEY_LEFT
            - KEY_RIGHT
            - KEY_OK
            - KEY_VOLUMEUP
            - KEY_VOLUMEDOWN
            - KEY_MUTE
            - KEY_CHANNELUP
            - KEY_CHANNELDOWN
            - KEY_LIST
            - KEY_FAV
            - KEY_GUIDE
            - KEY_EPG
            - KEY_0
            - KEY_1
            - KEY_2
            - KEY_3
            - KEY_4
            - KEY_5
            - KEY_6
            - KEY_7
            - KEY_8
            - KEY_9
            - KEY_PLAY
            - KEY_PAUSE
            - KEY_STOP
            - KEY_FORWARDS
            - KEY_BACKS
            - KEY_RECORD
            - KEY_RED
            - KEY_GREEN
            - KEY_YELLOW
            - KEY_BLUE
            - KEY_INFO
            - KEY_SUBTITLE
            - KEY_AUDIO
            - KEY_SLEEP
            - KEY_PICTURE
            - KEY_SOUND
            - KEY_NETFLIX
            - KEY_YOUTUBE
            - KEY_AMAZON
    entry_id:
      name: Entry ID
      description: Only needed when more than one TV is configured.
      required: false
      selector:
        text:
```

This list must match `const.KEYS` exactly, in the same order. `services.yaml` cannot read Python, so this duplication is unavoidable — Step 4 of Task 6 adds a check that keeps the two in sync.

- [ ] **Step 4: Add the translations**

In `custom_components/vidaa_tv/translations/en.json`, insert this entry into the `services` object between `publish` and `send_text`:

```json
    "send_key": {
      "name": "Send key",
      "description": "Send a single remote key to the TV.",
      "fields": {
        "key": { "name": "Key", "description": "The key to send, for example KEY_CHANNELUP. Any value is accepted." },
        "entry_id": { "name": "Entry ID", "description": "Only needed when more than one TV is configured." }
      }
    },
```

- [ ] **Step 5: Verify the JSON and YAML parse**

Run:

```bash
python -c "import json,pathlib; json.loads(pathlib.Path('custom_components/vidaa_tv/translations/en.json').read_text()); print('json ok')"
python -c "import yaml,pathlib; d=yaml.safe_load(pathlib.Path('custom_components/vidaa_tv/services.yaml').read_text()); print(sorted(d))"
```

Expected: `json ok`, then `['publish', 'refresh', 'send_key', 'send_text']`

- [ ] **Step 6: Commit**

```bash
git add custom_components/vidaa_tv/__init__.py custom_components/vidaa_tv/services.yaml custom_components/vidaa_tv/translations/en.json
git commit -m "Add a send_key service with a dropdown of every known key"
```

---

### Task 5: Context-aware channel up/down on the track buttons

**Files:**
- Modify: `custom_components/vidaa_tv/media_player.py:145-149`

**Interfaces:**
- Consumes: `VidaaTV.is_live_tv` from Task 1.
- Produces: no new symbols.

**No new test.** `media_player.py` cannot be imported without Home Assistant, and the only logic here is a ternary over `is_live_tv`, which Task 1 already covers exhaustively. A test that re-implemented the same ternary in `test_vidaa.py` would pass even if the entity were wired up wrong, so Step 3 below is the real gate.

- [ ] **Step 1: Wire it into the media player**

In `custom_components/vidaa_tv/media_player.py`, replace:

```python
    async def async_media_next_track(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_FORWARDS")

    async def async_media_previous_track(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_BACKS")
```

with:

```python
    # Home Assistant has no dedicated channel control, so the track buttons are
    # the only native home for channel up/down. Seek still wins inside apps.
    async def async_media_next_track(self) -> None:
        key = "KEY_CHANNELUP" if self._tv.is_live_tv else "KEY_FORWARDS"
        await self.hass.async_add_executor_job(self._tv.send_key, key)

    async def async_media_previous_track(self) -> None:
        key = "KEY_CHANNELDOWN" if self._tv.is_live_tv else "KEY_BACKS"
        await self.hass.async_add_executor_job(self._tv.send_key, key)
```

- [ ] **Step 2: Run the self-check**

Run: `python test_vidaa.py`
Expected: `all checks passed`

- [ ] **Step 3: Verify against the real TV**

With the TV on a broadcast channel, press next/previous track on the media player card and confirm the channel changes. Switch to Netflix or YouTube and confirm the same buttons now seek instead.

- [ ] **Step 4: Commit**

```bash
git add custom_components/vidaa_tv/media_player.py
git commit -m "Make the track buttons change channel while watching live TV"
```

---

### Task 6: Documentation, key/dropdown sync check, and version bump

**Files:**
- Modify: `README.md:20-37` (Features), `:108-168` (Services), `:202-218` (Caveats)
- Modify: `custom_components/vidaa_tv/manifest.json:18`
- Test: `test_vidaa.py`

**Interfaces:**
- Consumes: `const.KEYS` from Task 1; the `services.yaml` dropdown from Task 4.
- Produces: no new symbols.

- [ ] **Step 1: Write the failing sync check**

The `KEYS` tuple and the `services.yaml` dropdown are the same list in two languages, and they will drift. Add to `test_vidaa.py` in `main()`, just before `print("all checks passed")`:

```python
    # services.yaml cannot read Python, so the dropdown duplicates KEYS. Pin
    # them together or the UI silently falls behind const.py.
    yaml_text = (Path(__file__).parent / "custom_components" / "vidaa_tv"
                 / "services.yaml").read_text(encoding="utf-8")
    dropdown = [line.strip().lstrip("- ") for line in yaml_text.splitlines()
                if line.strip().startswith("- KEY_")]
    assert dropdown == list(const.KEYS), (
        f"services.yaml dropdown is out of sync with const.KEYS\n"
        f"  only in yaml: {sorted(set(dropdown) - set(const.KEYS))}\n"
        f"  only in KEYS: {sorted(set(const.KEYS) - set(dropdown))}"
    )
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python test_vidaa.py`
Expected: `all checks passed`. If it fails, the two lists genuinely diverged in Task 4 — fix `services.yaml` to match `const.KEYS` exactly, in order.

- [ ] **Step 3: Document the new behaviour in the README**

In `README.md`, under `## Services`, insert this section between `### remote.send_command` and `### vidaa_tv.publish`:

````markdown
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
````

Then replace the key list paragraph under `### remote.send_command` (the one starting "Keys reported by VIDAA remotes") with:

````markdown
The keys in the `vidaa_tv.send_key` dropdown are the ones VIDAA remotes are
known to send — see `KEYS` in `custom_components/vidaa_tv/const.py` for the
canonical list. It is a starting point, **not** a whitelist: any string is
passed straight through, so unlisted keys still work.
````

- [ ] **Step 4: Document the offline behaviour**

In `README.md`, under `## Features`, add these two bullets to the existing list:

```markdown
- Survives the TV being switched off. The integration never fails setup on an
  unreachable TV; it retries every 30 seconds and picks the TV back up on its
  own, so no manual reload is ever needed.
- Channel up/down on the media player's next/previous track buttons while
  watching broadcast TV. Inside apps the same buttons seek as before.
```

Then, under `## Caveats`, add:

```markdown
- While the TV is off, the media player reports `off` rather than
  `unavailable`, and its volume and source read as unknown. This is deliberate:
  it keeps `turn_on` callable so Wake-on-LAN automations still work.
```

- [ ] **Step 5: Bump the version**

In `custom_components/vidaa_tv/manifest.json`, change:

```json
  "version": "2.2.0"
```

to:

```json
  "version": "2.3.0"
```

- [ ] **Step 6: Final verification**

Run:

```bash
python test_vidaa.py
python -c "import json,pathlib; json.loads(pathlib.Path('custom_components/vidaa_tv/manifest.json').read_text()); print('manifest ok')"
git diff --stat HEAD~5
```

Expected: `all checks passed`, `manifest ok`, and a diff touching `const.py`, `client.py`, `__init__.py`, `media_player.py`, `remote.py`, `services.yaml`, `translations/en.json`, `test_vidaa.py`.

- [ ] **Step 7: Commit**

```bash
git add README.md custom_components/vidaa_tv/manifest.json test_vidaa.py
git commit -m "Document offline tolerance and send_key, bump to 2.3.0"
```

---

## Notes for the implementer

**Probing the real key list.** The spec calls for pruning keys the TV does not answer. `tools/probe.py` and `python test_vidaa.py` do not cover this — it needs the physical TV. If you have access, send each key from `KEYS` via `vidaa_tv.send_key` and watch the screen. Remove anything inert from **both** `const.KEYS` and the `services.yaml` dropdown (the Task 6 check enforces that they stay equal). Leaving the full list in place is also fine: the TV ignores what it does not implement.

**Why `available` is deleted rather than set to `True`.** `Entity.available` already defaults to `True`. An overridden property returning a constant is noise.

**What is not tested and why.** `__init__.py`, `media_player.py` and `remote.py` import Home Assistant, which is not installed here. Their logic is deliberately thin — the decisions live in `client.py`, which is fully covered. Task 3 Step 5 and Task 5 Step 5 are the manual gates that cover what the script cannot.
