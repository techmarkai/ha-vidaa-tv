"""Config flow for VIDAA TV: DHCP discovery, active scan, or manual entry."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import network
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT

from .client import VidaaAuthError, VidaaError, scan, test_connection
from .const import CONF_MAC, DEFAULT_NAME, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

MANUAL = "manual"

# Guard against scanning something enormous if HA sits on a wide subnet.
MAX_SCAN_HOSTS = 1024

MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_MAC, default=""): str,
    }
)


class VidaaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Find a TV automatically where possible, fall back to typing an IP."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._mac: str | None = None
        self._name: str = DEFAULT_NAME

    # ------------------------------------------------------------ discovery

    async def async_step_dhcp(self, discovery_info: Any) -> ConfigFlowResult:
        """A device matching a VIDAA MAC prefix appeared on the network."""
        self._host = discovery_info.ip
        self._mac = discovery_info.macaddress
        if hostname := getattr(discovery_info, "hostname", None):
            self._name = hostname

        await self.async_set_unique_id(f"{self._host}:{DEFAULT_PORT}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._host})

        # Only prompt the user if it really is a TV we can drive.
        try:
            await self.hass.async_add_executor_job(test_connection, self._host, DEFAULT_PORT)
        except VidaaError:
            return self.async_abort(reason="not_vidaa")

        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm adding a discovered TV."""
        if user_input is not None:
            return self._create(self._host, DEFAULT_PORT, self._name, self._mac)
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name, "host": self._host},
        )

    # ----------------------------------------------------------- user flow

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Scan the local networks, then offer what we found."""
        if user_input is not None:
            if user_input[CONF_HOST] == MANUAL:
                return await self.async_step_manual()
            return await self._finish(user_input[CONF_HOST], DEFAULT_PORT, DEFAULT_NAME, None)

        try:
            candidates = await self._async_candidate_hosts()
            found = await self.hass.async_add_executor_job(scan, candidates)
        except Exception:  # noqa: BLE001 - scanning must never block manual setup
            _LOGGER.exception("VIDAA scan failed; falling back to manual entry")
            found = []

        configured = {entry.data.get(CONF_HOST) for entry in self._async_current_entries()}
        found = [host for host in found if host not in configured]

        if not found:
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST): vol.In({**{h: h for h in found},
                                                  MANUAL: "Enter IP address manually"})}
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Type the TV's address directly."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._finish(
                user_input[CONF_HOST],
                user_input.get(CONF_PORT, DEFAULT_PORT),
                user_input.get(CONF_NAME) or DEFAULT_NAME,
                user_input.get(CONF_MAC) or None,
                errors,
            )
            if result is not None:
                return result
        return self.async_show_form(
            step_id="manual", data_schema=MANUAL_SCHEMA, errors=errors
        )

    # ----------------------------------------------------------- internals

    async def _async_candidate_hosts(self) -> list[str]:
        """Every address on Home Assistant's own IPv4 networks."""
        hosts: list[str] = []
        for adapter in await network.async_get_adapters(self.hass):
            if not adapter["enabled"]:
                continue
            for addr in adapter["ipv4"]:
                net = ipaddress.ip_network(
                    f"{addr['address']}/{addr['network_prefix']}", strict=False
                )
                if net.num_addresses > MAX_SCAN_HOSTS:
                    _LOGGER.debug("Skipping oversized network %s", net)
                    continue
                hosts.extend(str(host) for host in net.hosts())
        return hosts

    async def _finish(self, host, port, name, mac, errors=None):
        """Validate and create, or record an error."""
        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()
        try:
            await self.hass.async_add_executor_job(test_connection, host, port)
        except VidaaAuthError:
            if errors is None:
                return self.async_abort(reason="invalid_auth")
            errors["base"] = "invalid_auth"
            return None
        except VidaaError:
            if errors is None:
                return self.async_abort(reason="cannot_connect")
            errors["base"] = "cannot_connect"
            return None
        return self._create(host, port, name, mac)

    def _create(self, host, port, name, mac) -> ConfigFlowResult:
        return self.async_create_entry(
            title=name,
            data={CONF_HOST: host, CONF_PORT: port, CONF_MAC: mac},
        )
