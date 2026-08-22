"""The VIDAA TV integration."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

from .client import VidaaTV
from .const import CONF_MAC, DEFAULT_PORT, DOMAIN, SERVICES

PLATFORMS = [Platform.BUTTON, Platform.MEDIA_PLAYER, Platform.REMOTE]

ATTR_ENTRY_ID = "entry_id"

# The Lovelace card ships inside the integration and is served from here, so
# there is no resource for the user to add by hand. The version query busts the
# browser cache when the card changes; bump it with the manifest version.
CARD_URL = "/vidaa_tv/vidaa-remote-card.js"
CARD_FILE = "vidaa-remote-card.js"
CARD_VERSION = "2.5.1"
CARD_REGISTERED = f"{DOMAIN}_card_registered"

# Watchdog cadence. Ordinary reconnects are paho's job, and ping() bails out
# unless paho's network thread is actually dead — a disconnected TV on its own
# is not enough, since reconnect() racing that thread is unsafe.
# Also the tick that retires a stale grace window, so it has to be shorter than
# the wait a user would accept before a switched-off TV stops reading "on".
WATCHDOG_INTERVAL = timedelta(seconds=30)

SERVICE_NAMES = ("publish", "send_key", "send_text", "refresh")

SEND_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required("text"): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)

# cv.string, deliberately not vol.In(KEYS): KEYS drives the UI dropdown, but a
# key must never be blocked just because this integration has not heard of it.
SEND_KEY_SCHEMA = vol.Schema(
    {
        vol.Required("key"): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)

PUBLISH_SCHEMA = vol.Schema(
    {
        vol.Exclusive("topic", "target"): cv.string,
        vol.Exclusive("service", "target"): vol.In(SERVICES),
        vol.Optional("action"): cv.string,
        vol.Optional("payload", default=""): vol.Any(cv.string, dict, list),
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a TV from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    # Setup never fails on an unreachable TV. A TV that is off, unplugged or
    # behind a dead switch is a normal state, not a broken config entry — the
    # client retries in the background and the entities report "off" meanwhile.
    tv = VidaaTV(hass, host, port, entry.data.get(CONF_MAC))
    await tv.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = tv

    async def _watchdog(_now) -> None:
        await hass.async_add_executor_job(tv.ping)

    entry.async_on_unload(
        async_track_time_interval(hass, _watchdog, WATCHDOG_INTERVAL)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    await _async_register_card(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        tv = hass.data[DOMAIN].pop(entry.entry_id)
        await tv.async_stop()
        if not hass.data[DOMAIN]:
            for name in SERVICE_NAMES:
                hass.services.async_remove(DOMAIN, name)
    return unloaded


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the remote card and load it into the frontend.

    Registering the static path and the script URL is global rather than
    per-entry, so a second TV must not do it again: registering the same static
    path twice raises, and a duplicate script URL would fetch the card twice.
    """
    # Its own key, NOT inside hass.data[DOMAIN]: that dict maps entry_id to
    # VidaaTV and _resolve() counts and iterates it, so a flag parked in there
    # would read as a second TV and break single-TV service calls.
    if hass.data.get(CARD_REGISTERED):
        return
    hass.data[CARD_REGISTERED] = True

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL, str(Path(__file__).parent / "www" / CARD_FILE), False
            )
        ]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={CARD_VERSION}")


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the raw-protocol services once.

    send_key exists for discoverability — its dropdown lists every known key.
    remote.send_command on the remote entity remains the richer path: it takes
    a sequence of keys with repeats and delays, and supports entity targeting.
    """
    if hass.services.has_service(DOMAIN, "publish"):
        return

    def _resolve(call: ServiceCall) -> VidaaTV:
        entries: dict[str, VidaaTV] = hass.data[DOMAIN]
        entry_id = call.data.get(ATTR_ENTRY_ID)
        if entry_id:
            if entry_id not in entries:
                raise ServiceValidationError(f"No VIDAA TV with entry_id {entry_id}")
            return entries[entry_id]
        if len(entries) != 1:
            raise ServiceValidationError(
                "More than one VIDAA TV is configured; pass entry_id to choose one."
            )
        return next(iter(entries.values()))

    async def _publish(call: ServiceCall) -> None:
        tv = _resolve(call)
        payload = call.data.get("payload", "")
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        if topic := call.data.get("topic"):
            await hass.async_add_executor_job(tv.publish_raw, topic, payload)
            return
        service = call.data.get("service")
        action = call.data.get("action")
        if not service or not action:
            raise ServiceValidationError(
                "Provide either 'topic', or both 'service' and 'action'."
            )
        await hass.async_add_executor_job(tv.publish_action, service, action, payload)

    async def _refresh(call: ServiceCall) -> None:
        await hass.async_add_executor_job(_resolve(call).refresh)

    async def _send_text(call: ServiceCall) -> None:
        tv = _resolve(call)
        await hass.async_add_executor_job(tv.send_text, call.data["text"])

    async def _send_key(call: ServiceCall) -> None:
        tv = _resolve(call)
        await hass.async_add_executor_job(tv.send_key, call.data["key"])

    hass.services.async_register(DOMAIN, "publish", _publish, PUBLISH_SCHEMA)
    hass.services.async_register(DOMAIN, "send_key", _send_key, SEND_KEY_SCHEMA)
    hass.services.async_register(DOMAIN, "send_text", _send_text, SEND_TEXT_SCHEMA)
    hass.services.async_register(
        DOMAIN, "refresh", _refresh, vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})
    )
