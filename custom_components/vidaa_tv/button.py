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
