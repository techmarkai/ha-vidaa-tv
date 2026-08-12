"""Plain-MQTT client for Hisense/Toshiba VIDAA TVs.

These TVs run an MQTT broker on port 36669. Older models — including the
Toshiba this was written against — speak *unencrypted* MQTT and reset any TLS
handshake, which is why the existing HACS integrations cannot talk to them.
"""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import paho.mqtt.client as mqtt

from .const import (
    CLIENT_ID,
    DEFAULT_PORT,
    LIVE_TV_MARKERS,
    MQTT_PASSWORD,
    MQTT_USERNAME,
    OFF_STATE_MARKERS,
)

_LOGGER = logging.getLogger(__name__)


class VidaaError(Exception):
    """The TV could not be reached."""


class VidaaAuthError(VidaaError):
    """The TV rejected the firmware credentials."""


def _new_client(client_id: str) -> mqtt.Client:
    """paho-mqtt 1.x and 2.x take different constructor arguments."""
    try:
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError:  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
    return mqtt.Client(
        CallbackAPIVersion.VERSION1, client_id=client_id, protocol=mqtt.MQTTv311
    )


def scan(hosts: list[str], port: int = DEFAULT_PORT, timeout: float = 1.0) -> list[str]:
    """Return the hosts with the VIDAA MQTT port open. Blocking.

    VIDAA TVs answer no SSDP/mDNS, so an active scan is the only way to find one
    on a network Home Assistant cannot see broadcasts from.
    """

    def probe(host: str) -> str | None:
        try:
            socket.create_connection((host, port), timeout=timeout).close()
        except OSError:
            return None
        return host

    with ThreadPoolExecutor(max_workers=64) as pool:
        return [host for host in pool.map(probe, hosts) if host]


def test_connection(host: str, port: int = DEFAULT_PORT) -> None:
    """Raise VidaaError/VidaaAuthError if the TV is not usable. Blocking."""
    # Check TCP first so a routing/firewall problem is reported as such rather
    # than surfacing as a confusing MQTT timeout.
    try:
        socket.create_connection((host, port), timeout=10).close()
    except OSError as err:
        raise VidaaError(f"no TCP route to {host}:{port} ({err})") from err

    client = _new_client(CLIENT_ID)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    codes: list[int] = []
    answered = threading.Event()

    def _on_connect(_client, _userdata, _flags, rc):
        codes.append(rc)
        answered.set()

    client.on_connect = _on_connect
    try:
        client.connect(host, port, 15)
        client.loop_start()
        if not answered.wait(15):
            raise VidaaError("TV accepted the socket but never sent an MQTT CONNACK")
        if codes[0] == 5:
            raise VidaaAuthError("TV rejected the credentials")
        if codes[0] != 0:
            raise VidaaError(mqtt.connack_string(codes[0]))
    except OSError as err:
        raise VidaaError(str(err)) from err
    finally:
        client.loop_stop()
        with contextlib.suppress(OSError):
            client.disconnect()


class VidaaTV:
    """Live connection to one TV. State arrives by broadcast, so no polling."""

    def __init__(self, hass, host: str, port: int = DEFAULT_PORT, mac: str | None = None):
        self.hass = hass
        self.host = host
        self.port = port
        self.mac = mac

        self.connected = False
        self.volume: int | None = None
        self.muted = False
        self.state_type: str | None = None
        self.current_name: str | None = None
        self.sources: list[dict] = []
        self.apps: list[dict] = []
        self.channels: list[dict] = []
        self.current_channel: dict | None = None
        self.device_info: dict = {}
        self.auth_failed = False
        self._last_connack_rc: int | None = None

        self._listeners: list[Callable[[], None]] = []
        self._client = _new_client(CLIENT_ID)
        self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        # Flat 30s, no backoff: a TV switched back on appears within 30 seconds
        # instead of waiting out a growing delay. One cheap LAN connect per 30s.
        self._client.reconnect_delay_set(min_delay=30, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ---------------------------------------------------------------- state

    @property
    def is_on(self) -> bool:
        state = (self.state_type or "").lower()
        return self.connected and not any(m in state for m in OFF_STATE_MARKERS)

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

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def _notify(self) -> None:
        # Called on the paho network thread; hop to the event loop.
        for callback in list(self._listeners):
            self.hass.loop.call_soon_threadsafe(callback)

    # ------------------------------------------------------------ callbacks

    def _on_connect(self, client, _userdata, _flags, rc):
        if rc != 0:
            if rc == 5:
                # Not recoverable: the firmware now wants PIN pairing, which we
                # do not implement. Log once and stop, rather than 2,880 ERROR
                # lines a day against a TV that will never let us in.
                if not self.auth_failed:
                    self.auth_failed = True
                    _LOGGER.error(
                        "TV %s rejected our credentials. This firmware requires PIN "
                        "pairing, which this integration does not support. Giving up; "
                        "remove the VIDAA TV config entry for %s.",
                        self.host, self.host,
                    )
                with contextlib.suppress(OSError, ValueError):
                    client.disconnect()
                return
            # Log a persistent failure only when it changes; otherwise every
            # 30s reconnect writes the same ERROR forever.
            if rc != self._last_connack_rc:
                _LOGGER.error(
                    "TV %s rejected connection: %s", self.host, mqtt.connack_string(rc)
                )
            self._last_connack_rc = rc
            return
        self._last_connack_rc = 0
        self.connected = True
        client.subscribe("/remoteapp/mobile/broadcast/#")
        client.subscribe(f"/remoteapp/mobile/{CLIENT_ID}/#")
        self.refresh()
        self._notify()

    def _on_disconnect(self, _client, _userdata, rc):
        self.connected = False
        _LOGGER.debug("TV %s disconnected (rc=%s); paho will retry", self.host, rc)
        self._notify()

    def _on_message(self, _client, _userdata, msg):
        topic, payload = msg.topic, msg.payload
        low = topic.lower()
        try:
            if topic.endswith("/ui_service/state"):
                data = json.loads(payload)
                self.state_type = data.get("statetype")
                # Apps report "name"; input switches report "sourcename" instead.
                self.current_name = data.get("name") or data.get("sourcename")
                # Live TV reports the channel inline on some firmware.
                if data.get("channel_name") or data.get("channelname"):
                    self.current_channel = data
                    self.current_name = (
                        data.get("channel_name") or data.get("channelname")
                    )
            elif "volumechange" in low:
                self.volume = int(json.loads(payload)["volume_value"])
            elif low.endswith("/data/sourcelist"):
                self.sources = json.loads(payload)
            elif low.endswith("/data/applist"):
                self.apps = json.loads(payload)
            elif "channellist" in low:
                channels = json.loads(payload)
                # Some firmware wraps the list in an object.
                if isinstance(channels, dict):
                    channels = channels.get("list") or channels.get("channels") or []
                self.channels = channels if isinstance(channels, list) else []
            elif "currentchannel" in low:
                self.current_channel = json.loads(payload)
            elif "deviceinfo" in low:
                info = json.loads(payload)
                if isinstance(info, dict):
                    self.device_info.update(info)
            elif "mute" in low:
                data = json.loads(payload)
                if isinstance(data, dict):
                    for key in ("mute", "is_mute", "mute_status", "mute_value"):
                        if key in data:
                            self.muted = str(data[key]).lower() in ("1", "true", "on")
                            break
            else:
                return
        except (ValueError, TypeError, KeyError) as err:
            _LOGGER.debug("Ignoring unparsable message on %s: %s", topic, err)
            return
        self._notify()

    # ------------------------------------------------------------- commands

    def _topic(self, service: str, action: str) -> str:
        return f"/remoteapp/tv/{service}/{CLIENT_ID}/actions/{action}"

    def find_app(self, wanted: str) -> dict | None:
        """Match an app by display name or url, case-insensitively."""
        target = wanted.strip().lower()
        for app in self.apps:
            if target in (
                str(app.get("name", "")).lower(),
                str(app.get("url", "")).lower(),
            ):
                return app
        return None

    def find_source(self, wanted: str) -> dict | None:
        """Match an input by source name or display name."""
        target = wanted.strip().lower()
        for source in self.sources:
            if target in (
                str(source.get("sourcename", "")).lower(),
                str(source.get("displayname", "")).lower(),
            ):
                return source
        return None

    def open_url(self, url: str) -> None:
        """Open a web address in the TV browser. urlType 36 is the web-app type."""
        self.launch_app({"name": url, "url": url, "urlType": 36, "storeType": 0})

    def publish_raw(self, topic: str, payload: str = "") -> None:
        """Escape hatch: publish any topic, for protocol bits not modelled here."""
        _LOGGER.debug("Publishing raw to %s: %s", topic, payload)
        self._client.publish(topic, payload)

    def publish_action(self, service: str, action: str, payload: str = "") -> None:
        """Publish to /remoteapp/tv/<service>/<client>/actions/<action>."""
        self._client.publish(self._topic(service, action), payload)

    def refresh(self) -> None:
        """Ask for everything the TV is willing to describe about itself.

        Unsupported actions are simply ignored by the TV, so asking costs
        nothing on firmware that lacks them.
        """
        for action in (
            "sourcelist", "applist", "getdeviceinfo",
            "gettvchannellist", "getcurrentchannel",
        ):
            self._client.publish(self._topic("ui_service", action), "")
        self._client.publish(self._topic("platform_service", "getdeviceinfo"), "")

    def send_text(self, text: str) -> None:
        """Type into whatever field the TV has focused (search boxes, logins)."""
        self._client.publish(
            self._topic("ui_service", "sendtext"), json.dumps({"text": text})
        )

    def send_key(self, key: str) -> None:
        """Send a remote key. Accepts "mute" as well as "KEY_MUTE"."""
        key = key.strip().upper()
        if not key.startswith("KEY_"):
            key = f"KEY_{key}"
        self._client.publish(self._topic("remote_service", "sendkey"), key)

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, int(volume)))
        self._client.publish(self._topic("platform_service", "changevolume"), str(volume))

    def launch_app(self, app: dict) -> None:
        self._client.publish(self._topic("ui_service", "launchapp"), json.dumps(app))

    def select_source(self, source_id: str) -> None:
        self._client.publish(
            self._topic("ui_service", "changesource"),
            json.dumps({"sourceid": str(source_id)}),
        )

    def wake(self) -> None:
        """Wake-on-LAN. Needs the MAC; only works if the packet can reach the TV."""
        if not self.mac:
            return
        mac = self.mac.replace(":", "").replace("-", "").lower()
        packet = bytes.fromhex("ff" * 6 + mac * 16)
        # ponytail: broadcast WoL only lands if HA shares the TV's subnet or the
        # router forwards directed broadcast. If turn_on stays dead across
        # subnets, run a small relay on the TV's own subnet instead.
        for target in ("255.255.255.255", self.host.rsplit(".", 1)[0] + ".255"):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(packet, (target, 9))
                sock.close()
            except OSError as err:
                _LOGGER.debug("WoL to %s failed: %s", target, err)

    # ------------------------------------------------------------ lifecycle

    async def async_start(self) -> None:
        """Begin connecting. Returns immediately and never raises.

        connect_async only records the address — no I/O happens here — and the
        network thread retries every 30s forever. A TV that is off is a normal
        state, not a setup failure, so nothing here reports one.
        """
        self._client.connect_async(self.host, self.port, 30)
        self._client.loop_start()

    def ping(self) -> None:
        """Watchdog tick: restart paho only if its network thread has died.

        A disconnected TV is the normal steady state here, so "not connected"
        alone is no reason to act — paho is already retrying every 30s, and
        reconnect() is not thread-safe against its own network thread. The one
        failure this exists to catch is that thread being gone, which leaves
        nothing retrying at all. `_thread` is private, but it *is* the
        invariant; there is no public equivalent. A TV that rejected our
        credentials is deliberately left alone entirely. Blocking.
        """
        if self.connected or self.auth_failed:
            return
        thread = getattr(self._client, "_thread", None)
        if thread is not None and thread.is_alive():
            return  # paho's own retry loop is running; leave it alone.
        _LOGGER.debug("Watchdog: paho's thread is gone for %s, reconnecting", self.host)
        with contextlib.suppress(OSError, ValueError):
            self._client.reconnect()

    async def async_stop(self) -> None:
        self._client.loop_stop()
        await self.hass.async_add_executor_job(self._client.disconnect)
