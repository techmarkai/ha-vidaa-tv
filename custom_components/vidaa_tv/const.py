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

# Every key known to the VIDAA remote protocol. The TV silently ignores keys it
# does not implement, and never acknowledges the ones it does — so this is a
# convenience list for the UI, NOT a whitelist. `remote.send_command` and
# `vidaa_tv.send_key` accept any string, so an unlisted key still works.
KEYS = [
    # Power and navigation
    "KEY_POWER", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_OK",
    "KEY_BACK", "KEY_RETURNS", "KEY_HOME", "KEY_MENU", "KEY_EXIT",
    # Volume and channel
    "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE",
    "KEY_CHANNELUP", "KEY_CHANNELDOWN", "KEY_CHANNELS",
    # Digits
    "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
    "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9",
    # Colour keys
    "KEY_RED", "KEY_GREEN", "KEY_YELLOW", "KEY_BLUE",
    # Transport
    "KEY_PLAY", "KEY_PAUSE", "KEY_STOP", "KEY_FORWARDS", "KEY_BACKS",
    "KEY_FASTFORWARD", "KEY_REWIND", "KEY_RECORD",
    # Sources and info
    "KEY_INPUT", "KEY_SOURCE", "KEY_TV", "KEY_INFO", "KEY_GUIDE", "KEY_EPG",
    "KEY_SUBTITLE", "KEY_TEXT", "KEY_AUDIO", "KEY_FAV", "KEY_LIST",
    # Settings and picture/sound
    "KEY_SETTINGS", "KEY_SETTING", "KEY_PICTURE", "KEY_SOUND", "KEY_SLEEP",
    "KEY_FREEZE", "KEY_ZOOM", "KEY_ASPECT",
    # App shortcuts
    "KEY_NETFLIX", "KEY_YOUTUBE", "KEY_PRIMEVIDEO", "KEY_APPS", "KEY_STORE",
]
