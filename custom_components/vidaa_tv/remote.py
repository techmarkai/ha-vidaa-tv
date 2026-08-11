"""Remote entity — sends any VIDAA key, including ones not in the known list."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from homeassistant.components.remote import ATTR_DELAY_SECS, ATTR_NUM_REPEATS, RemoteEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import VidaaTV
from .const import DOMAIN

DEFAULT_DELAY = 0.4


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the remote."""
    async_add_entities([VidaaRemote(hass.data[DOMAIN][entry.entry_id], entry)])


class VidaaRemote(RemoteEntity):
    """Exposes the full VIDAA key set through remote.send_command."""

    _attr_has_entity_name = True
    _attr_name = "Remote"

    def __init__(self, tv: VidaaTV, entry: ConfigEntry) -> None:
        self._tv = tv
        base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base}_remote"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, base)})

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._tv.add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return self._tv.connected

    @property
    def is_on(self) -> bool:
        return self._tv.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self._tv.wake)
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_POWER")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_POWER")

    async def async_send_command(self, command: Iterable[str], **kwargs: Any) -> None:
        """Send one or more keys. Any key string is accepted."""
        repeats = kwargs.get(ATTR_NUM_REPEATS) or 1
        delay = kwargs.get(ATTR_DELAY_SECS)
        if delay is None:
            delay = DEFAULT_DELAY

        # send_key normalises "mute" into "KEY_MUTE" for every caller.
        for _ in range(repeats):
            for cmd in command:
                await self.hass.async_add_executor_job(self._tv.send_key, cmd)
                await asyncio.sleep(delay)
