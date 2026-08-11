"""Constants for the VIDAA TV integration."""

DOMAIN = "vidaa_tv"

DEFAULT_PORT = 36669
DEFAULT_NAME = "Vidaa TV"

CONF_MAC = "mac"

# Baked into VIDAA firmware; identical on every TV of this generation.
MQTT_USERNAME = "hisenseservice"
MQTT_PASSWORD = "multimqttservice"

# The TV routes replies to /remoteapp/mobile/<client_id>/..., so the id must be
# stable and must keep the "<mac>$normal" shape. The MAC itself is arbitrary.
CLIENT_ID = "00:11:22:33:44:55$normal"

# Substrings that mark a statetype as "not actually showing anything". Matched
# as substrings because firmware versions vary the exact wording
# ("fake_sleep_0", "sleep", "standby", ...).
OFF_STATE_MARKERS = ("sleep", "standby", "poweroff", "power_off", "shutdown")

# Service names used in the /remoteapp/tv/<service>/... topic tree.
SERVICES = ("remote_service", "ui_service", "platform_service")
