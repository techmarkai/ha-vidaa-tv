"""Self-check for the VIDAA message parsing. Run: python test_vidaa.py

Loads client.py directly so Home Assistant does not need to be installed.
"""

import asyncio
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

DIR = Path(__file__).parent / "custom_components" / "vidaa_tv"


def _load():
    pkg = types.ModuleType("vt")
    pkg.__path__ = [str(DIR)]
    sys.modules["vt"] = pkg
    for name in ("const", "client"):
        spec = importlib.util.spec_from_file_location(f"vt.{name}", DIR / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"vt.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules["vt.client"]


client = _load()
const = sys.modules["vt.const"]


class FakeLoop:
    def call_soon_threadsafe(self, cb, *a):
        cb(*a)


class FakeHass:
    loop = FakeLoop()


class FakeClient:
    """Swallows subscribe/publish so _on_connect can run without a socket."""

    def __init__(self):
        self.published = []

    def subscribe(self, *_a, **_k):
        pass

    def publish(self, topic, payload=None, *a, **k):
        self.published.append((topic, payload))


class Msg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload.encode() if isinstance(payload, str) else payload


def main():
    tv = client.VidaaTV(FakeHass(), "192.168.27.20")
    updates = []
    tv.add_listener(lambda: updates.append(1))

    # Volume broadcast (the TV sends tab-indented JSON).
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/platform_service/actions/volumechange",
        '{\n\t"volume_type":\t0,\n\t"volume_value":\t49\n}'))
    assert tv.volume == 49, tv.volume

    # Current app / source.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/ui_service/state",
        '{"statetype":"app","name":"youtube","url":"youtube"}'))
    assert tv.state_type == "app" and tv.current_name == "youtube"

    # Input switches use "sourcename", not "name" — regression guard.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/ui_service/state",
        '{"statetype":"sourceswitch","sourceid":"4","sourcename":"HDMI1",'
        '"displayname":"HDMI1"}'))
    assert tv.state_type == "sourceswitch", tv.state_type
    assert tv.current_name == "HDMI1", tv.current_name

    # Source and app lists.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/x/ui_service/data/sourcelist",
        '[{"sourceid":"4","sourcename":"HDMI1"},{"sourceid":"0","sourcename":"TV"}]'))
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/x/ui_service/data/applist",
        '[{"name":"Netflix","url":"netflix","urlType":37,"storeType":0}]'))
    assert [s["sourcename"] for s in tv.sources] == ["HDMI1", "TV"]
    assert tv.apps[0]["name"] == "Netflix"

    # Every handled message must notify listeners, or HA never updates.
    assert len(updates) == 5, updates

    # Garbage must not raise (it would kill the paho network thread).
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/ui_service/state", "not json"))
    tv._on_message(None, None, Msg("/remoteapp/mobile/broadcast/unknown/thing", "{}"))

    # Channel list: plain list, and the object-wrapped variant.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/x/ui_service/data/gettvchannellist",
        '[{"channel_num":"104","channel_name":"BBC One"}]'))
    assert tv.channels[0]["channel_name"] == "BBC One"
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/x/ui_service/data/gettvchannellist",
        '{"list":[{"channel_num":"7","channel_name":"Alt"}]}'))
    assert tv.channels[0]["channel_num"] == "7", tv.channels
    # A shape we do not understand must not leave a non-list behind.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/x/ui_service/data/gettvchannellist", '"nonsense"'))
    assert isinstance(tv.channels, list)

    # Device info accumulates rather than replacing.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/x/ui_service/data/getdeviceinfo",
        '{"model":"43QA4163DB"}'))
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/x/platform_service/data/getdeviceinfo",
        '{"firmware":"V0000.01.00b"}'))
    assert tv.device_info == {"model": "43QA4163DB", "firmware": "V0000.01.00b"}

    # Mute, if this firmware ever reports it.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/platform_service/actions/mutechange",
        '{"mute":"1"}'))
    assert tv.muted is True
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/platform_service/actions/mutechange",
        '{"mute":"0"}'))
    assert tv.muted is False

    # Sleep states must read as off even while MQTT stays connected. Matched as
    # substrings because firmware wording varies.
    tv.connected = True
    for awake in ("app", "sourceswitch", "livetv"):
        tv.state_type = awake
        assert tv.is_on, awake
    for asleep in ("fake_sleep_0", "sleep", "standby", "POWEROFF", "power_off"):
        tv.state_type = asleep
        assert not tv.is_on, asleep
    tv.connected = False
    tv.state_type = "app"
    assert not tv.is_on

    # Live TV detection drives which keys the track buttons send.
    def live(state_type, name, channel=None):
        tv.state_type, tv.current_name, tv.current_channel = state_type, name, channel
        tv.state_has_channel = False
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

    # Firmware that reports the tuner via channel_name on a non-livetv
    # statetype: parser and property together, through a real message.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/ui_service/state",
        '{"statetype":"sourceswitch","channel_name":"BBC One","channel_num":"104"}'))
    assert tv.state_has_channel is True
    assert tv.current_name == "BBC One", tv.current_name
    assert tv.is_live_tv, (tv.state_type, tv.current_name)

    # Switching to an app clears it, even though current_channel is stale.
    tv._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/ui_service/state",
        '{"statetype":"app","name":"netflix","url":"netflix"}'))
    assert tv.state_has_channel is False
    assert not tv.is_live_tv, (tv.state_type, tv.current_channel)

    # The key list is a discoverability aid, not a whitelist.
    assert "KEY_CHANNELUP" in const.KEYS and "KEY_CHANNELDOWN" in const.KEYS
    assert all(k.startswith("KEY_") for k in const.KEYS), const.KEYS
    assert len(set(const.KEYS)) == len(const.KEYS), "duplicate key"
    for digit in "0123456789":
        assert f"KEY_{digit}" in const.KEYS

    # App and source lookup: by name or url, case-insensitive, no false hits.
    assert tv.find_app("Netflix")["url"] == "netflix"
    assert tv.find_app("netflix")["name"] == "Netflix"
    assert tv.find_app("NETFLIX")["name"] == "Netflix"
    assert tv.find_app("  netflix  ")["name"] == "Netflix"
    assert tv.find_app("Disney+") is None
    assert tv.find_source("HDMI1")["sourceid"] == "4"
    assert tv.find_source("hdmi1")["sourceid"] == "4"
    assert tv.find_source("HDMI9") is None

    # Topic shape must match what the TV actually answers on.
    assert tv._topic("remote_service", "sendkey") == \
        "/remoteapp/tv/remote_service/00:11:22:33:44:55$normal/actions/sendkey"

    # Volume must be clamped before it reaches the TV.
    sent = []
    tv._client.publish = lambda topic, payload: sent.append((topic, payload))
    tv.set_volume(150)
    tv.set_volume(-10)
    tv.set_volume(47)
    assert [p for _, p in sent] == ["100", "0", "47"], sent

    # send_key normalises for every caller, so remote.py and the services do
    # not each need their own copy of this.
    sent.clear()
    for raw in ("KEY_MUTE", "mute", " Mute ", "key_mute"):
        tv.send_key(raw)
    assert [p for _, p in sent] == ["KEY_MUTE"] * 4, sent
    assert sent[0][0].endswith("/remote_service/00:11:22:33:44:55$normal/actions/sendkey")

    # open_url must go out as a browser-type app launch.
    sent.clear()
    tv.open_url("https://example.com")
    topic, payload = sent[0]
    assert topic.endswith("/actions/launchapp"), topic
    assert json.loads(payload) == {
        "name": "https://example.com", "url": "https://example.com",
        "urlType": 36, "storeType": 0,
    }, payload

    # A dropped publish must warn, not raise — and a stub with no rc (as used
    # throughout this file) must still count as success.
    class _Dropped:
        rc = 4  # MQTT_ERR_NO_CONN

    class _Collector(logging.Handler):
        records = []

        def emit(self, record):
            self.records.append(record)

    handler = _Collector()
    client._LOGGER.addHandler(handler)
    client._LOGGER.setLevel(logging.DEBUG)
    try:
        tv._client.publish = lambda topic, payload: _Dropped()
        tv.send_key("KEY_MUTE")  # must not raise
        assert len(handler.records) == 1, handler.records
        record = handler.records[0]
        assert record.levelno == logging.WARNING, record.levelname
        assert "not delivered" in record.getMessage(), record.getMessage()
        assert "/actions/sendkey" in record.getMessage(), record.getMessage()

        # After an auth rejection the real cause was already logged at ERROR;
        # every later drop is noise, so it must fall to DEBUG.
        handler.records.clear()
        tv.auth_failed = True
        tv.send_key("KEY_MUTE")
        assert [r.levelno for r in handler.records] == [logging.DEBUG], handler.records
        tv.auth_failed = False
    finally:
        client._LOGGER.removeHandler(handler)
    tv._client.publish = lambda topic, payload: sent.append((topic, payload))

    # The watchdog restarts paho's network loop only when its thread is gone.
    # reconnect() cannot help there: it sends CONNECT with nobody left to read
    # the CONNACK, so the loop must be stopped (to clear paho's stale _thread)
    # and started again.
    loop_calls = []
    tv._client.loop_stop = lambda: loop_calls.append("stop")
    tv._client.loop_start = lambda: loop_calls.append("start")

    # A live paho network thread is already retrying; racing it is unsafe, so
    # the watchdog must keep its hands off.
    class _AliveThread:
        def is_alive(self):
            return True

    tv.connected = False
    tv._client._thread = _AliveThread()
    tv.ping()
    assert loop_calls == [], loop_calls

    # Connected: nothing to do either.
    tv._client._thread = None
    tv.connected = True
    tv.ping()
    assert loop_calls == [], loop_calls

    # Disconnected with a dead thread: stop then start, in that order.
    tv.connected = False
    tv.ping()
    assert loop_calls == ["stop", "start"], loop_calls

    # A racing paho must not propagate out of the watchdog.
    loop_calls.clear()
    tv._client.loop_stop = lambda: (_ for _ in ()).throw(OSError("in flight"))
    tv.ping()  # must not raise
    assert loop_calls == [], loop_calls
    tv._client.loop_stop = lambda: loop_calls.append("stop")

    # A rejected credential (rc=5) is terminal: give up instead of retrying
    # forever and writing an ERROR every 30 seconds.
    rejected = client.VidaaTV(FakeHass(), "10.0.0.8")
    disconnects = []
    rejected._client.disconnect = lambda: disconnects.append(1)
    rejected._client.loop_stop = lambda: loop_calls.append("nope")
    rejected._client.loop_start = lambda: loop_calls.append("nope")
    rejected._on_connect(rejected._client, None, None, 5)
    assert rejected.auth_failed is True
    assert not rejected.connected
    assert disconnects == [1], disconnects
    # Its thread was stopped on purpose; the watchdog must not restart it.
    loop_calls.clear()
    rejected.ping()
    assert loop_calls == [], loop_calls

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

    # A drop while the TV is on must not read as off: this firmware closes the
    # MQTT socket every few minutes (rc=7) and paho is back seconds later.
    flappy = client.VidaaTV(FakeHass(), "10.0.0.10")
    flappy._client = fake = FakeClient()
    flappy._on_connect(fake, None, None, 0)
    flappy._on_message(None, None, Msg(
        "/remoteapp/mobile/broadcast/ui_service/state",
        b'{"statetype": "livetv", "channel_name": "Nat Geo"}'))
    assert flappy.is_on, "should be on while connected"
    flappy._on_disconnect(None, None, 7)
    assert not flappy.connected, "the link is down"
    assert flappy.is_on, "a fresh drop must keep the last known state"
    assert flappy.current_name == "Nat Geo", "state must survive the gap"
    flappy._dropped_at -= const.DISCONNECT_GRACE + 1
    assert not flappy.is_on, "past the grace the TV is genuinely unavailable"
    flappy._on_connect(fake, None, None, 0)
    assert flappy._dropped_at is None and flappy.is_on, "reconnect clears the grace"

    # A TV that never came up has no last state to hold on to.
    never = client.VidaaTV(FakeHass(), "10.0.0.11")
    never._on_disconnect(None, None, 7)
    assert not never.is_on, "never-connected TV must stay off"

    print("all checks passed")


if __name__ == "__main__":
    main()
