"""Map what a VIDAA TV's MQTT interface actually supports.

    python tools/probe.py 192.168.1.50

Fires every action worth trying and reports which ones answer. Use the output
to open an issue if your TV supports something this integration does not model
yet. Nothing here changes a setting; the only visible effect is that the TV may
briefly react to a query.
"""

import contextlib
import json
import ssl
import sys
import time
from collections import OrderedDict

import paho.mqtt.client as mqtt

PORT = 36669
USERNAME, PASSWORD = "hisenseservice", "multimqttservice"
CLIENT_ID = "00:11:22:33:44:55$normal"

# (service, action) pairs. Unsupported ones are simply ignored by the TV.
QUERIES = [
    ("ui_service", "sourcelist"),
    ("ui_service", "applist"),
    ("ui_service", "gettvstate"),
    ("ui_service", "getvolume"),
    ("ui_service", "getdeviceinfo"),
    ("ui_service", "gettvchannellist"),
    ("ui_service", "getcurrentchannel"),
    ("ui_service", "getchannellisttype"),
    ("ui_service", "getsourcelist"),
    ("ui_service", "getepginfo"),
    ("ui_service", "getpicturesetting"),
    ("ui_service", "getsoundsetting"),
    ("ui_service", "getsleeptimer"),
    ("platform_service", "getdeviceinfo"),
    ("platform_service", "getsystemstatus"),
    ("platform_service", "getvolume"),
    ("platform_service", "getmute"),
    ("platform_service", "getpicturemode"),
    ("platform_service", "getsoundmode"),
    ("remote_service", "getdeviceinfo"),
]

replies: "OrderedDict[str, list]" = OrderedDict()


def on_connect(client, _u, _f, rc):
    print(f"[connect] rc={rc} ({mqtt.connack_string(rc)})", flush=True)
    if rc == 0:
        client.subscribe("#")


def on_message(_c, _u, msg):
    # Skip the echo of what we published ourselves.
    if msg.topic.startswith("/remoteapp/tv/"):
        return
    replies.setdefault(msg.topic, []).append(msg.payload)


def connect(host):
    """VIDAA sets are split between plain MQTT and TLS. Try plain first."""
    for label, use_tls in (("plain", False), ("TLS", True)):
        client = mqtt.Client(client_id=CLIENT_ID, protocol=mqtt.MQTTv311)
        client.username_pw_set(USERNAME, PASSWORD)
        if use_tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with contextlib.suppress(ssl.SSLError):
                ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
            client.tls_set_context(ctx)
        client.on_connect, client.on_message = on_connect, on_message
        try:
            client.connect(host, PORT, 30)
        except Exception as err:  # noqa: BLE001
            print(f"[{label}] failed: {type(err).__name__}: {err}", flush=True)
            continue
        print(f"[{label}] connected", flush=True)
        return client
    return None


def show(payload):
    try:
        return json.dumps(json.loads(payload), indent=1)[:2000]
    except Exception:  # noqa: BLE001
        return repr(payload[:500])


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python tools/probe.py <tv-ip>")
    host = sys.argv[1]

    client = connect(host)
    if client is None:
        sys.exit(f"Could not reach a VIDAA broker at {host}:{PORT}")

    client.loop_start()
    time.sleep(2)

    for service, action in QUERIES:
        client.publish(f"/remoteapp/tv/{service}/{CLIENT_ID}/actions/{action}", "")
        time.sleep(1.2)

    print("\nListening 8s more for unsolicited broadcasts "
          "(change the input or volume now to capture more)...", flush=True)
    time.sleep(8)
    client.loop_stop()
    client.disconnect()

    print(f"\n{'=' * 60}\n{len(replies)} topics answered\n{'=' * 60}", flush=True)
    for topic, payloads in replies.items():
        print(f"\n--- {topic}  ({len(payloads)} message(s))")
        print(show(payloads[-1]))

    answered = {t.rsplit("/", 1)[-1] for t in replies}
    silent = [f"{s}/{a}" for s, a in QUERIES if a not in answered]
    print(f"\n{'=' * 60}\nNo reply from: {', '.join(silent) or 'nothing — all answered'}")
    print("Silence usually means the firmware lacks that action.")


if __name__ == "__main__":
    main()
