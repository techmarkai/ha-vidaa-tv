"""Self-check for the VIDAA message parsing. Run: python test_vidaa.py

Loads client.py directly so Home Assistant does not need to be installed.
"""

import asyncio
import importlib.util
import json
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

    # Watchdog only reconnects while disconnected, and swallows a racing paho.
    reconnects = []
    tv._client.reconnect = lambda: reconnects.append(1)
    tv.connected = True
    tv.ping()
    assert reconnects == [], reconnects
    tv.connected = False
    tv.ping()
    assert reconnects == [1], reconnects
    tv._client.reconnect = lambda: (_ for _ in ()).throw(OSError("in flight"))
    tv.ping()  # must not raise

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

    print("all checks passed")


if __name__ == "__main__":
    main()
