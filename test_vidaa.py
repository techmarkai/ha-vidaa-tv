"""Self-check for the VIDAA message parsing. Run: python test_vidaa.py

Loads client.py directly so Home Assistant does not need to be installed.
"""

import importlib.util
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

    # Sleep states must read as off even while MQTT stays connected.
    tv.connected = True
    tv.state_type = "app"
    assert tv.is_on
    tv.state_type = "fake_sleep_0"
    assert not tv.is_on
    tv.connected = False
    assert not tv.is_on

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

    print("all checks passed")


if __name__ == "__main__":
    main()
