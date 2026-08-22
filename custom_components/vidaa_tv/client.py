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
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import paho.mqtt.client as mqtt

from .const import (
    CLIENT_ID,
    DEFAULT_PORT,
    DISCONNECT_GRACE,
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


def clean_mac(mac: str | None) -> str:
    """Bare lowercase hex, so "10:C7:53:8E:B3:86" and "10c7538eb386" compare equal.

    Discovery hands the MAC over in whichever shape the source used, so every
    comparison has to go through here or a TV that changed address is treated
    as a new device.
    """
    return "".join(c for c in (mac or "").lower() if c in "0123456789abcdef")


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
        # Whether the *latest* state broadcast named a channel. current_channel
        # cannot answer that: it also holds the getcurrentchannel reply, which
        # is never cleared when you switch to an app.
        self.state_has_channel = False
        self.device_info: dict = {}
        self.auth_failed = False
        self._last_connack_rc: int | None = None
        # When the link went down while it had been up; None while connected.
        self._dropped_at: float | None = None
        # Diagnostics only: how many times this client has come up, and how
        # long the last outage lasted. Without these the log shows drops but
        # never recoveries, so a slow reconnect looks identical to a fast one.
        self._connects = 0
        self.last_downtime: float | None = None

        self._listeners: list[Callable[[], None]] = []
        self._client = _new_client(CLIENT_ID)
        self._client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        # Backoff 1s -> 5s. Measured against the real TV: after it ends a
        # session it also refuses new connections for somewhere between 15 and
        # 31 seconds, so paho's default doubling (1,2,4,8,16) spent its 16s
        # sleep waiting past the point the TV was ready again and took 31.1s
        # every single time. Capping the delay keeps retrying across that
        # window instead of sleeping through it. The link is down for real
        # until it succeeds -- commands published meanwhile are dropped at QoS
        # 0 -- so the retries buy back control latency, not just a status dot.
        # ponytail: one TCP connect per 5s to a switched-off TV is the price;
        # raise the cap if that ever shows up on the network.
        self._client.reconnect_delay_set(min_delay=1, max_delay=5)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    # ---------------------------------------------------------------- state

    @property
    def link_ok(self) -> bool:
        """True while our view of the TV is still trustworthy.

        This firmware closes the MQTT socket on its own every few minutes
        (paho reports rc=7) even though the TV stays switched on, and paho
        reconnects seconds later. Reporting the TV as off for that gap is what
        made the entity look unstable, so a drop that follows a live
        connection keeps the last known state for DISCONNECT_GRACE seconds.
        A TV that was never up, or that has been down longer than the grace,
        is genuinely unavailable.
        """
        if self.connected:
            return True
        if self._dropped_at is None or not self.state_type:
            return False
        return (time.monotonic() - self._dropped_at) < DISCONNECT_GRACE

    @property
    def is_on(self) -> bool:
        state = (self.state_type or "").lower()
        return self.link_ok and not any(m in state for m in OFF_STATE_MARKERS)

    @property
    def is_live_tv(self) -> bool:
        """True when the foreground is broadcast TV rather than an app or input.

        Decides whether the media player's track buttons mean channel up/down
        or fast-forward/rewind.
        """
        state = (self.state_type or "").lower()
        if "livetv" in state or "live_tv" in state:
            return True
        if self.state_has_channel:
            # The last state broadcast named a channel, so the tuner is in the
            # foreground even if the statetype is something like "sourceswitch".
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
        self._connects += 1
        if self._dropped_at is not None:
            self.last_downtime = time.monotonic() - self._dropped_at
            # INFO, not DEBUG: this is the line that proves a drop recovered,
            # and how fast. One line per outage on a TV that drops every few
            # minutes is a handful an hour, not noise.
            _LOGGER.info(
                "TV %s reconnected after %.1fs down (connection #%s)",
                self.host, self.last_downtime, self._connects,
            )
        else:
            _LOGGER.info("TV %s connected (connection #%s)", self.host, self._connects)
        self._dropped_at = None
        client.subscribe("/remoteapp/mobile/broadcast/#")
        client.subscribe(f"/remoteapp/mobile/{CLIENT_ID}/#")
        self.refresh()
        self._notify()

    def _on_disconnect(self, _client, _userdata, rc):
        if self.connected:
            self._dropped_at = time.monotonic()
        self.connected = False
        # rc=7 is this firmware ending the session on its own roughly every
        # 300s; rc=16 would be a keepalive timeout and rc=0 a clean local
        # disconnect. Naming it here saves looking the number up later.
        _LOGGER.info(
            "TV %s disconnected: %s (rc=%s); reconnecting",
            self.host, mqtt.error_string(rc), rc,
        )
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
                channel_name = data.get("channel_name") or data.get("channelname")
                self.state_has_channel = bool(channel_name)
                if channel_name:
                    self.current_channel = data
                    self.current_name = channel_name
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

    def _publish(self, topic: str, payload: str = "") -> None:
        """Publish and say so when it went nowhere.

        Entities stay available while the TV is off, so without this a service
        call against a sleeping TV succeeds silently and does nothing: at QoS 0
        with no connection paho drops the message and only reports it here.
        """
        result = self._client.publish(topic, payload)
        rc = getattr(result, "rc", mqtt.MQTT_ERR_SUCCESS)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            # Not necessarily a fault: async_turn_on deliberately sends KEY_POWER
            # after Wake-on-LAN, which is always dropped. And once auth_failed is
            # set the real problem was already reported at ERROR, so every drop
            # after that is noise.
            level = logging.DEBUG if self.auth_failed else logging.WARNING
            _LOGGER.log(
                level,
                "Command to %s was not delivered: the client is not connected (%s)",
                topic, mqtt.error_string(rc),
            )

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
        self._publish(topic, payload)

    def publish_action(self, service: str, action: str, payload: str = "") -> None:
        """Publish to /remoteapp/tv/<service>/<client>/actions/<action>."""
        self._publish(self._topic(service, action), payload)

    def refresh(self) -> None:
        """Ask for everything the TV is willing to describe about itself.

        Unsupported actions are simply ignored by the TV, so asking costs
        nothing on firmware that lacks them.
        """
        for action in (
            "sourcelist", "applist", "getdeviceinfo",
            "gettvchannellist", "getcurrentchannel",
        ):
            self._publish(self._topic("ui_service", action), "")
        self._publish(self._topic("platform_service", "getdeviceinfo"), "")

    def send_text(self, text: str) -> None:
        """Type into whatever field the TV has focused (search boxes, logins)."""
        self._publish(
            self._topic("ui_service", "sendtext"), json.dumps({"text": text})
        )

    def send_key(self, key: str) -> None:
        """Send a remote key. Accepts "mute" as well as "KEY_MUTE"."""
        key = key.strip().upper()
        if not key.startswith("KEY_"):
            key = f"KEY_{key}"
        self._publish(self._topic("remote_service", "sendkey"), key)

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, int(volume)))
        self._publish(self._topic("platform_service", "changevolume"), str(volume))

    def launch_app(self, app: dict) -> None:
        self._publish(self._topic("ui_service", "launchapp"), json.dumps(app))

    def select_source(self, source_id: str) -> None:
        self._publish(
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
        """Watchdog tick: restart paho's network loop if its thread has died.

        A disconnected TV is the normal steady state here, so "not connected"
        alone is no reason to act — paho is already retrying every 30s. The one
        failure this exists to catch is that thread being gone (an exception
        escaping a callback kills it permanently), which leaves nothing
        retrying at all. `_thread` is private, but it *is* the invariant; there
        is no public equivalent.

        loop_stop() joins the dead thread and clears paho's stale `_thread`
        reference — without it loop_start() returns MQTT_ERR_INVAL and does
        nothing. loop_start() then re-enters loop_forever(), which
        re-establishes the connection itself, so no explicit reconnect() is
        needed (reconnect() alone would never help: it sends CONNECT but leaves
        nobody to read the CONNACK). A TV that rejected our credentials is
        deliberately left alone entirely — its thread was stopped on purpose.
        Blocking, briefly, in the join.
        """
        if self.connected or self.auth_failed:
            return
        thread = getattr(self._client, "_thread", None)
        if thread is not None and thread.is_alive():
            return  # paho's own retry loop is running; leave it alone.
        _LOGGER.debug(
            "Watchdog: paho's thread is gone for %s, restarting its loop", self.host
        )
        with contextlib.suppress(OSError, ValueError):
            self._client.loop_stop()
            self._client.loop_start()

    async def async_stop(self) -> None:
        self._client.loop_stop()
        await self.hass.async_add_executor_job(self._client.disconnect)
