"""Plain-MQTT client for Hisense/Toshiba VIDAA TVs.

These TVs run an MQTT broker on port 36669. Older models — including the
Toshiba this was written against — speak *unencrypted* MQTT and reset any TLS
handshake, which is why the existing HACS integrations cannot talk to them.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import paho.mqtt.client as mqtt

from .const import CLIENT_ID, DEFAULT_PORT, MQTT_PASSWORD, MQTT_USERNAME, OFF_STATE_TYPES

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
        try:
            client.disconnect()
        except OSError:
            pass


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

        self._listeners: list[Callable[[], None]] = []
        self._client = _new_client(CLIENT_ID)
        self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ---------------------------------------------------------------- state

    @property
    def available(self) -> bool:
        return self.connected

    @property
    def is_on(self) -> bool:
        return self.connected and self.state_type not in OFF_STATE_TYPES

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
            _LOGGER.error("TV %s rejected connection: %s", self.host, mqtt.connack_string(rc))
            return
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
        try:
            if topic.endswith("/ui_service/state"):
                data = json.loads(payload)
                self.state_type = data.get("statetype")
                # Apps report "name"; input switches report "sourcename" instead.
                self.current_name = data.get("name") or data.get("sourcename")
            elif topic.endswith("platform_service/actions/volumechange"):
                self.volume = int(json.loads(payload)["volume_value"])
            elif topic.endswith("/ui_service/data/sourcelist"):
                self.sources = json.loads(payload)
            elif topic.endswith("/ui_service/data/applist"):
                self.apps = json.loads(payload)
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
        for action in ("sourcelist", "applist"):
            self._client.publish(self._topic("ui_service", action), "")

    def send_key(self, key: str) -> None:
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
        await self.hass.async_add_executor_job(self._client.connect, self.host, self.port, 30)
        self._client.loop_start()

    async def async_stop(self) -> None:
        self._client.loop_stop()
        await self.hass.async_add_executor_job(self._client.disconnect)
