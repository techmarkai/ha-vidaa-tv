"""The VIDAA TV integration."""

from __future__ import annotations

import json

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .client import VidaaError, VidaaTV
from .const import CONF_MAC, DEFAULT_PORT, DOMAIN, SERVICES

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.REMOTE]

ATTR_ENTRY_ID = "entry_id"

SERVICE_NAMES = ("publish", "send_text", "refresh")

SEND_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required("text"): cv.string,
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

    # async_start verifies the CONNACK on the connection it already opens, so a
    # firewall or a sleeping TV fails here with a reason instead of sitting in a
    # silent reconnect loop.
    tv = VidaaTV(hass, host, port, entry.data.get(CONF_MAC))
    try:
        await tv.async_start()
    except VidaaError as err:
        raise ConfigEntryNotReady(f"Cannot reach VIDAA TV at {host}:{port}: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = tv
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
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


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the raw-protocol services once.

    Key sending is deliberately not a service here — remote.send_command on the
    remote entity is the Home Assistant native way, and supports targeting,
    repeats and delays for free.
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

    hass.services.async_register(DOMAIN, "publish", _publish, PUBLISH_SCHEMA)
    hass.services.async_register(DOMAIN, "send_text", _send_text, SEND_TEXT_SCHEMA)
    hass.services.async_register(
        DOMAIN, "refresh", _refresh, vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})
    )
