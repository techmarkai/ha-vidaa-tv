"""Media player entity for a VIDAA TV."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
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
    | MediaPlayerEntityFeature.BROWSE_MEDIA
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
            # Setup no longer waits for the TV, so with the TV off this is all
            # we have. _handle_update corrects the registry once the real
            # values arrive.
            model=tv.device_info.get("model") or "Smart TV",
            sw_version=tv.device_info.get("firmware") or tv.device_info.get("version"),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._tv.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self._sync_device_registry()
        self.async_write_ha_state()

    def _sync_device_registry(self) -> None:
        """Push a late-arriving model/firmware into the device registry.

        DeviceInfo is only read when the entity is added, so a TV that was off
        at startup would otherwise show "Smart TV" until the next restart.
        """
        info = self._tv.device_info
        if not info:
            return
        model = info.get("model")
        sw_version = info.get("firmware") or info.get("version")
        changes = {}
        if model and model != self._attr_device_info.get("model"):
            changes["model"] = model
        if sw_version and sw_version != self._attr_device_info.get("sw_version"):
            changes["sw_version"] = sw_version
        if not changes:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(
            identifiers=self._attr_device_info["identifiers"]
        )
        if device:
            registry.async_update_device(device.id, **changes)
            # Only now are the new values really registered; updating earlier
            # would make the guard above skip a retry if the lookup failed.
            self._attr_device_info.update(changes)

    # ----------------------------------------------------------------- state

    @property
    def state(self) -> MediaPlayerState:
        # is_on already requires a live connection.
        return MediaPlayerState.ON if self._tv.is_on else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        if not self._tv.connected or self._tv.volume is None:
            return None
        return self._tv.volume / 100

    @property
    def is_volume_muted(self) -> bool:
        return self._tv.connected and self._tv.muted

    @property
    def source_list(self) -> list[str]:
        names = [s["sourcename"] for s in self._tv.sources if s.get("sourcename")]
        names += [a["name"] for a in self._tv.apps if a.get("name")]
        return names

    @property
    def source(self) -> str | None:
        return self._tv.current_name if self._tv.connected else None

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
        # The TV only offers a toggle. Assume it landed; if this firmware does
        # broadcast mute, the client will correct us on the next message.
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_MUTE")
        self._tv.muted = mute
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_PLAY")

    async def async_media_pause(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_PAUSE")

    async def async_media_stop(self) -> None:
        await self.hass.async_add_executor_job(self._tv.send_key, "KEY_STOP")

    # Home Assistant has no dedicated channel control, so the track buttons are
    # the only native home for channel up/down. Seek still wins inside apps.
    async def async_media_next_track(self) -> None:
        key = "KEY_CHANNELUP" if self._tv.is_live_tv else "KEY_FORWARDS"
        await self.hass.async_add_executor_job(self._tv.send_key, key)

    async def async_media_previous_track(self) -> None:
        key = "KEY_CHANNELDOWN" if self._tv.is_live_tv else "KEY_BACKS"
        await self.hass.async_add_executor_job(self._tv.send_key, key)

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
        kind = str(media_type).lower()

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

        if kind in ("source", "input"):
            await self.async_select_source(media_id)
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
            f"Unsupported media type '{media_type}'. Use app, url, source or channel."
        )

    # ---------------------------------------------------------- media browser

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Browse apps, inputs and — where the TV provides them — channels."""
        if media_content_id in (None, "", "root"):
            children = [
                self._directory("Apps", "apps"),
                self._directory("Inputs", "inputs"),
            ]
            if self._tv.channels:
                children.append(self._directory("Channels", "channels"))
            return self._directory("Vidaa TV", "root", children)

        if media_content_id == "apps":
            return self._directory("Apps", "apps", [
                self._item(app.get("name", "?"), MediaType.APP, MediaClass.APP)
                for app in self._tv.apps if app.get("name")
            ])

        if media_content_id == "inputs":
            return self._directory("Inputs", "inputs", [
                self._item(src.get("sourcename", "?"), "source", MediaClass.CHANNEL)
                for src in self._tv.sources if src.get("sourcename")
            ])

        if media_content_id == "channels":
            return self._directory("Channels", "channels", [
                self._item(
                    ch.get("channel_name") or ch.get("name") or str(ch.get("channel_num", "?")),
                    MediaType.CHANNEL,
                    MediaClass.CHANNEL,
                    str(ch.get("channel_num") or ch.get("major") or ""),
                )
                for ch in self._tv.channels
            ])

        raise ServiceValidationError(f"Unknown media location: {media_content_id}")

    @staticmethod
    def _directory(title, content_id, children=None) -> BrowseMedia:
        return BrowseMedia(
            title=title,
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            media_content_id=content_id,
            can_play=False,
            can_expand=True,
            children=children or [],
        )

    @staticmethod
    def _item(title, content_type, media_class, content_id=None) -> BrowseMedia:
        return BrowseMedia(
            title=title,
            media_class=media_class,
            media_content_type=content_type,
            media_content_id=content_id if content_id is not None else title,
            can_play=True,
            can_expand=False,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Surface whatever the TV told us about itself."""
        attrs: dict[str, Any] = {}
        if self._tv.state_type:
            attrs["state_type"] = self._tv.state_type
        if self._tv.device_info:
            attrs.update(
                {f"device_{k}": v for k, v in self._tv.device_info.items()}
            )
        if self._tv.current_channel:
            attrs["channel"] = self._tv.current_channel
        return attrs
