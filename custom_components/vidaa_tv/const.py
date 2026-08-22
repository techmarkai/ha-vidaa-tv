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

# Source names that mean broadcast TV rather than an app or an HDMI input.
# Matched exactly (after strip/lower), not as substrings, because "tv" as a
# substring would also match app names like "Apple TV".
LIVE_TV_MARKERS = ("tv", "live tv", "livetv", "atv", "dtv", "antenna", "cable", "tuner")

# Every key this firmware generation is known to accept. The TV silently
# ignores actions it does not implement, so listing a key a given model lacks
# costs nothing. This exists to populate the send_key dropdown — it is NOT a
# whitelist, and any string is still passed through.
KEYS = (
    "KEY_POWER", "KEY_SOURCE", "KEY_INPUT", "KEY_TV",
    "KEY_HOME", "KEY_MENU", "KEY_BACK", "KEY_RETURNS", "KEY_EXIT", "KEY_SETTINGS",
    "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_OK",
    "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE",
    "KEY_CHANNELUP", "KEY_CHANNELDOWN", "KEY_LIST", "KEY_FAV", "KEY_GUIDE", "KEY_EPG",
    "KEY_0", "KEY_1", "KEY_2", "KEY_3", "KEY_4",
    "KEY_5", "KEY_6", "KEY_7", "KEY_8", "KEY_9",
    "KEY_PLAY", "KEY_PAUSE", "KEY_STOP", "KEY_FORWARDS", "KEY_BACKS", "KEY_RECORD",
    "KEY_RED", "KEY_GREEN", "KEY_YELLOW", "KEY_BLUE",
    "KEY_INFO", "KEY_SUBTITLE", "KEY_AUDIO", "KEY_SLEEP", "KEY_PICTURE", "KEY_SOUND",
    "KEY_NETFLIX", "KEY_YOUTUBE", "KEY_AMAZON",
    # On the CT-8547 handset but never confirmed against a TV: the remote card
    # draws them, and this firmware ignores actions it does not implement, so a
    # wrong guess does nothing rather than erroring. Confirm before relying on
    # them, and drop any that stay dead.
    "KEY_TEXT", "KEY_APPS", "KEY_MEDIA", "KEY_PREVIOUS", "KEY_NEXT",
)

# The keys worth a dashboard button, as (key, display name, icon). A curated
# subset of KEYS on purpose: one entity per key across all 52 would clutter
# every entity picker to serve keys nobody puts on a card. Everything else
# stays reachable through the send_key service and remote.send_command.
BUTTONS = (
    ("KEY_UP", "Up", "mdi:arrow-up"),
    ("KEY_DOWN", "Down", "mdi:arrow-down"),
    ("KEY_LEFT", "Left", "mdi:arrow-left"),
    ("KEY_RIGHT", "Right", "mdi:arrow-right"),
    ("KEY_OK", "OK", "mdi:check-circle-outline"),
    ("KEY_BACK", "Back", "mdi:arrow-u-left-top"),
    ("KEY_HOME", "Home", "mdi:home"),
    ("KEY_MENU", "Menu", "mdi:menu"),
    ("KEY_EXIT", "Exit", "mdi:exit-to-app"),
    ("KEY_CHANNELUP", "Channel up", "mdi:chevron-up-box"),
    ("KEY_CHANNELDOWN", "Channel down", "mdi:chevron-down-box"),
    ("KEY_0", "0", "mdi:numeric-0"),
    ("KEY_1", "1", "mdi:numeric-1"),
    ("KEY_2", "2", "mdi:numeric-2"),
    ("KEY_3", "3", "mdi:numeric-3"),
    ("KEY_4", "4", "mdi:numeric-4"),
    ("KEY_5", "5", "mdi:numeric-5"),
    ("KEY_6", "6", "mdi:numeric-6"),
    ("KEY_7", "7", "mdi:numeric-7"),
    ("KEY_8", "8", "mdi:numeric-8"),
    ("KEY_9", "9", "mdi:numeric-9"),
)

# Service names used in the /remoteapp/tv/<service>/... topic tree.
SERVICES = ("remote_service", "ui_service", "platform_service")

# Seconds to keep reporting the last known state after the TV closes the MQTT
# socket. This firmware drops the link every few minutes while still switched
# on and paho is back within seconds; the grace covers that gap without hiding
# a TV that was really switched off for long.
# ponytail: fixed window, tune if your set drops for longer than this.
DISCONNECT_GRACE = 60.0
