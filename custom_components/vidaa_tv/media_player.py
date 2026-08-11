"""Media player entity for a VIDAA TV."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import VidaaTV
from .const import DOMAIN

SUPPORT = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.PLAY_MEDIA
)

# Delay between digit presses when tuning a channel; the TV drops keys sent
# back to back.
DIGIT_DELAY = 0.3


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the media player."""
    async_add_entities([VidaaMediaPlayer(hass.data[DOMAIN][entry.entry_id], entry)])


class VidaaMediaPlayer(MediaPlayerEntity):
    """A VIDAA TV as a media player."""

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_supported_features = SUPPORT
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, tv: VidaaTV, entry: ConfigEntry) -> None:
        self._tv = tv
        self._attr_unique_id = entry.unique_id or entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=entry.title,
            manufacturer="VIDAA",
            model="Smart TV",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._tv.add_listener(self.async_write_ha_state))

    # ----------------------------------------------------------------- state

    @property
    def available(self) -> bool:
        return self._tv.available

    @property
    def state(self) -> MediaPlayerState:
        if not self._tv.connected:
            return MediaPlayerState.OFF
        return MediaPlayerState.ON if self._tv.is_on else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        if self._tv.volume is None:
            return None
        return self._tv.volume / 100

    @property
    def is_volume_muted(self) -> bool:
        return self._tv.muted

    @property
    def source_list(self) -> list[str]:
        names = [s["sourcename"] for s in self._tv.sources if s.get("sourcename")]
        names += [a["name"] for a in self._tv.apps if a.get("name")]
        return names

    @property
    def source(self) -> str | None:
        return self._tv.current_name

    # -------------------------------------------------------------- commands

    async def async_turn_on(self) -> None:
        # If the TV kept its MQTT link alive in standby the keypress works;
        # otherwise the magic packet is the only way back.
        await self.hass.async_add_executor_job(self._tv.wake)
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_POWER")

    async def async_turn_off(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_POWER")

    async def async_set_volume_level(self, volume: float) -> None:
        await self.hass.async_add_executor_job(self._tv.set_volume, round(volume * 100))

    async def async_volume_up(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_VOLUMEUP")

    async def async_volume_down(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_VOLUMEDOWN")

    async def async_mute_volume(self, mute: bool) -> None:
        # The TV only toggles; it never reports mute back, so we track it here.
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_MUTE")
        self._tv.muted = mute
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_PLAY")

    async def async_media_pause(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_PAUSE")

    async def async_media_stop(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_STOP")

    async def async_media_next_track(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_FORWARDS")

    async def async_media_previous_track(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_BACKS")

    async def async_select_source(self, source: str) -> None:
        if src := self._tv.find_source(source):
            await self.hass.async_add_executor_job(self._tv.select_source, src["sourceid"])
            return
        if app := self._tv.find_app(source):
            await self.hass.async_add_executor_job(self._tv.launch_app, app)
            return
        raise ServiceValidationError(f"Unknown source: {source}")

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Launch an app, open a URL, or tune a channel.

        This is app launching rather than true casting — VIDAA sets speak no
        Google Cast, so there is no stream to hand over.
        """
        kind = str(media_type).lower().removeprefix("vidaa_tv/")

        if kind in (MediaType.APP, "app", "application"):
            app = self._tv.find_app(media_id)
            if app is None:
                known = ", ".join(a.get("name", "?") for a in self._tv.apps)
                raise ServiceValidationError(
                    f"Unknown app '{media_id}'. Installed apps: {known}"
                )
            await self.hass.async_add_executor_job(self._tv.launch_app, app)
            return

        if kind in (MediaType.URL, "url", "web"):
            await self.hass.async_add_executor_job(self._tv.open_url, media_id)
            return

        if kind in (MediaType.CHANNEL, "channel"):
            digits = str(media_id).strip()
            if not digits.isdigit():
                raise ServiceValidationError(f"Channel must be numeric, got '{media_id}'")
            # No verified "tune to channel" action exists, so key in the number
            # the way the physical remote does.
            for digit in digits:
                await self.hass.async_add_executor_job(self._tv.send_key, f"KEY_{digit}")
                await asyncio.sleep(DIGIT_DELAY)
            await self.hass.async_add_executor_job(self._tv.send_key, "KEY_OK")
            return

        raise ServiceValidationError(
            f"Unsupported media type '{media_type}'. Use app, url or channel."
        )
