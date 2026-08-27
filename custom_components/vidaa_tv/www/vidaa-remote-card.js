/**
 * VIDAA TV remote card.
 *
 * Laid out after the Toshiba CT-8547 handset that ships with these sets, so the
 * buttons sit where your thumb already expects them. Styled with Home Assistant
 * theme variables rather than the handset's own black shell, so it follows the
 * dashboard into light and dark themes.
 *
 * Keys go out over remote.send_command against the integration's remote entity.
 * That targets an entity directly, so a second TV is just a second card -- the
 * vidaa_tv.send_key service targets a config entry instead and cannot do that.
 *
 * Served by the integration itself at /vidaa_tv/vidaa-remote-card.js, so there
 * is no Lovelace resource to add by hand.
 */

const KEY = (label, command, opts = {}) => ({ label, command, ...opts });
const GAP = { spacer: true };

// null command = decorative label from the handset, not a button.
const LAYOUT = [
  { cls: "row-2", keys: [KEY("⊸", "KEY_SOURCE", { title: "Source" }), KEY("⏻", "KEY_POWER", { cls: "power", title: "Power" })] },
  // P.MODE, S.MODE, APPS and MEDIA are on the handset but the TV ignores their
  // key codes, so they are not drawn -- a button that does nothing is worse
  // than one that is absent.
  { cls: "row-2", keys: [KEY("i+", "KEY_INFO", { title: "Info" }), KEY("TV", "KEY_TV")] },
  { cls: "row-3", keys: [KEY("1", "KEY_1", { cls: "num" }), KEY("2", "KEY_2", { cls: "num" }), KEY("3", "KEY_3", { cls: "num" })] },
  { cls: "row-3", keys: [KEY("4", "KEY_4", { cls: "num" }), KEY("5", "KEY_5", { cls: "num" }), KEY("6", "KEY_6", { cls: "num" })] },
  { cls: "row-3", keys: [KEY("7", "KEY_7", { cls: "num" }), KEY("8", "KEY_8", { cls: "num" }), KEY("9", "KEY_9", { cls: "num" })] },
  { cls: "row-3", keys: [KEY("MENU", "KEY_MENU"), KEY("0", "KEY_0", { cls: "num" }), KEY("TEXT", "KEY_TEXT")] },
  // The handset puts volume and channel on vertical rockers either side of
  // LIST/MUTE/HOME. A card has no rocker, so each half becomes its own button.
  { cls: "row-3", keys: [KEY("＋", "KEY_VOLUMEUP", { title: "Volume up" }), KEY("LIST", "KEY_LIST"), KEY("∧", "KEY_CHANNELUP", { title: "Channel up" })] },
  { cls: "row-3", keys: [KEY("🔇", "KEY_MUTE", { title: "Mute" }), KEY("HOME", "KEY_HOME"), KEY("∨", "KEY_CHANNELDOWN", { title: "Channel down" })] },
  { cls: "row-3", keys: [KEY("－", "KEY_VOLUMEDOWN", { title: "Volume down" }), KEY("↩", "KEY_BACK", { title: "Back" }), KEY("EXIT", "KEY_EXIT")] },
  { cls: "pad", keys: [
      GAP, KEY("▲", "KEY_UP", { cls: "round", title: "Up" }), GAP,
      KEY("◀", "KEY_LEFT", { cls: "round", title: "Left" }),
      KEY("OK", "KEY_OK", { cls: "ok" }),
      KEY("▶", "KEY_RIGHT", { cls: "round", title: "Right" }),
      GAP, KEY("▼", "KEY_DOWN", { cls: "round", title: "Down" }), GAP,
    ] },
  { cls: "row-2", keys: [KEY("GUIDE", "KEY_GUIDE"), KEY("SUBTITLE", "KEY_SUBTITLE")] },
  { cls: "colors", keys: [
      KEY("", "KEY_RED", { cls: "c-red", title: "Red" }),
      KEY("", "KEY_GREEN", { cls: "c-green", title: "Green" }),
      KEY("", "KEY_YELLOW", { cls: "c-yellow", title: "Yellow" }),
      KEY("", "KEY_BLUE", { cls: "c-blue", title: "Blue" }),
    ] },
  { cls: "row-3", keys: [KEY("◀◀", "KEY_BACKS", { title: "Rewind" }), KEY("▶", "KEY_PLAY", { title: "Play" }), KEY("▶▶", "KEY_FORWARDS", { title: "Fast forward" })] },
  { cls: "row-4", keys: [
      KEY("▮◀◀", "KEY_PREVIOUS", { title: "Previous" }), KEY("■", "KEY_STOP", { title: "Stop" }),
      KEY("▮▮", "KEY_PAUSE", { title: "Pause" }), KEY("▶▶▮", "KEY_NEXT", { title: "Next" }),
    ] },
  { cls: "row-2", keys: [
      KEY("NETFLIX", null, { cls: "netflix", app: "Netflix" }),
      KEY("YouTube", null, { cls: "youtube", app: "YouTube" }),
    ] },
];

// Everything above, minus the keypad, colour keys, teletext and the second
// transport row -- what gets used day to day, at about half the height so the
// card sits beside others instead of owning a column.
const COMPACT_LAYOUT = [
  { cls: "row-2", keys: [KEY("⊸", "KEY_SOURCE", { title: "Source" }), KEY("⏻", "KEY_POWER", { cls: "power", title: "Power" })] },
  { cls: "pad", keys: [
      GAP, KEY("▲", "KEY_UP", { cls: "round", title: "Up" }), GAP,
      KEY("◀", "KEY_LEFT", { cls: "round", title: "Left" }),
      KEY("OK", "KEY_OK", { cls: "ok" }),
      KEY("▶", "KEY_RIGHT", { cls: "round", title: "Right" }),
      GAP, KEY("▼", "KEY_DOWN", { cls: "round", title: "Down" }), GAP,
    ] },
  { cls: "row-3", keys: [KEY("＋", "KEY_VOLUMEUP", { title: "Volume up" }), KEY("HOME", "KEY_HOME"), KEY("∧", "KEY_CHANNELUP", { title: "Channel up" })] },
  { cls: "row-3", keys: [KEY("－", "KEY_VOLUMEDOWN", { title: "Volume down" }), KEY("↩", "KEY_BACK", { title: "Back" }), KEY("∨", "KEY_CHANNELDOWN", { title: "Channel down" })] },
  { cls: "row-3", keys: [KEY("🔇", "KEY_MUTE", { title: "Mute" }), KEY("EXIT", "KEY_EXIT"), KEY("GUIDE", "KEY_GUIDE")] },
  { cls: "row-3", keys: [KEY("◀◀", "KEY_BACKS", { title: "Rewind" }), KEY("▶", "KEY_PLAY", { title: "Play" }), KEY("▶▶", "KEY_FORWARDS", { title: "Fast forward" })] },
  { cls: "row-2", keys: [
      KEY("NETFLIX", null, { cls: "netflix", app: "Netflix" }),
      KEY("YouTube", null, { cls: "youtube", app: "YouTube" }),
    ] },
];

const STYLE = `
  ha-card { padding: 12px; }
  .remote { display: flex; flex-direction: column; gap: 6px; max-width: 260px; margin: 0 auto; }
  .row-2, .row-3, .row-4, .colors, .pad { display: grid; gap: 6px; }
  .row-2 { grid-template-columns: repeat(2, 1fr); }
  .row-3 { grid-template-columns: repeat(3, 1fr); }
  .row-4 { grid-template-columns: repeat(4, 1fr); }
  .colors { grid-template-columns: repeat(4, 1fr); }
  .pad { grid-template-columns: repeat(3, 1fr); gap: 4px; place-items: center; }

  button {
    font: inherit; cursor: pointer; color: var(--primary-text-color);
    background: var(--secondary-background-color);
    border: 1px solid var(--divider-color); border-radius: 8px;
    min-height: 34px; padding: 4px 2px; width: 100%;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.72rem; letter-spacing: 0.02em;
    transition: background 0.15s, transform 0.06s;
  }
  button:hover { background: var(--primary-color); color: var(--text-primary-color); }
  button:active { transform: translateY(1px); }
  button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
  button[disabled] { opacity: 0.4; cursor: not-allowed; }
  button[disabled]:hover { background: var(--secondary-background-color); color: var(--primary-text-color); }

  .num { font-size: 0.95rem; font-weight: 500; }
  .power { color: var(--error-color); font-size: 1rem; }
  .round { border-radius: 50%; aspect-ratio: 1; min-height: 0; padding: 0; }
  .ok { border-radius: 50%; aspect-ratio: 1; min-height: 0; font-weight: 600; }
  .colors button { min-height: 14px; border-radius: 3px; }
  .c-red { background: #cf3b30; } .c-green { background: #2f9e57; }
  .c-yellow { background: #d9b229; } .c-blue { background: #2f6fc4; }
  .c-red:hover, .c-green:hover, .c-yellow:hover, .c-blue:hover { filter: brightness(1.2); background: inherit; }
  .netflix { color: #e50914; font-weight: 700; font-size: 0.62rem; }
  .youtube { color: #ff0000; font-weight: 700; font-size: 0.62rem; }
  .spacer { visibility: hidden; }
  .warn { padding: 16px; color: var(--error-color); font-size: 0.9rem; }
  @media (prefers-reduced-motion: reduce) { button { transition: none; } }
`;

class VidaaRemoteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._built = false;
    this._buttons = [];
  }

  setConfig(config) {
    this._config = { ...config };
    this._built = false;
    this.shadowRoot.innerHTML = "";
  }

  static getStubConfig(hass) {
    // Pre-fill the first VIDAA remote so dropping the card on a dashboard
    // works with no YAML. Any remote entity wins over none at all.
    const entity = Object.keys(hass.states).find((id) => id.startsWith("remote."));
    return { entity: entity || "" };
  }

  // Rows of buttons, roughly; Lovelace uses this for masonry placement.
  get _layout() {
    return LAYOUT;
  }

  getCardSize() {
    return 12;
  }

  set hass(hass) {
    this._hass = hass;
    const entity = this._entityId();
    if (!entity) {
      this.shadowRoot.innerHTML = `<ha-card><div class="warn">
        No VIDAA TV remote entity found. Set <code>entity:</code> to your
        <code>remote.*</code> entity.</div></ha-card>`;
      return;
    }
    if (!this._built) this._build();
    // Entities stay available across the TV's periodic MQTT drops, so this only
    // greys out when the TV is genuinely gone -- not every few minutes.
    const state = hass.states[entity];
    const dead = !state || state.state === "unavailable";
    for (const button of this._buttons) button.disabled = dead;
  }

  _entityId() {
    if (this._config && this._config.entity) return this._config.entity;
    if (!this._hass) return null;
    return Object.keys(this._hass.states).find((id) => id.startsWith("remote.")) || null;
  }

  _build() {
    const card = document.createElement("ha-card");
    if (this._config.title) card.setAttribute("header", this._config.title);
    const style = document.createElement("style");
    style.textContent = STYLE;
    const remote = document.createElement("div");
    remote.className = "remote";
    this._buttons = [];

    for (const row of this._layout) {
      const el = document.createElement("div");
      el.className = row.cls;
      for (const key of row.keys) {
        if (key.spacer) {
          el.appendChild(document.createElement("span"));
          continue;
        }
        const button = document.createElement("button");
        button.className = key.cls || "";
        button.textContent = key.label;
        const name = key.title || key.label || key.command || key.app;
        button.setAttribute("aria-label", name);
        button.title = name;
        button.addEventListener("click", () =>
          key.app ? this._launch(key.app) : this._send(key.command));
        el.appendChild(button);
        this._buttons.push(button);
      }
      remote.appendChild(el);
    }

    card.appendChild(style);
    card.appendChild(remote);
    this.shadowRoot.appendChild(card);
    this._built = true;
  }

  _mediaPlayerId() {
    // Both entities are named after the same device, so the object id matches:
    // remote.living_room -> media_player.living_room.
    const id = (this._entityId() || "").replace(/^remote\./, "media_player.");
    return this._hass && this._hass.states[id] ? id : null;
  }

  _launch(app) {
    // The TV ignores KEY_NETFLIX and KEY_YOUTUBE, but it reports its installed
    // apps, and selecting one by name launches it. Falls back to the key code
    // on firmware that has no media player entity to ask.
    const entity_id = this._mediaPlayerId();
    if (!entity_id) return this._send(`KEY_${app.toUpperCase()}`);
    this._hass.callService("media_player", "select_source", { entity_id, source: app });
    this.dispatchEvent(new CustomEvent("haptic", { bubbles: true, composed: true, detail: "light" }));
  }

  _send(command) {
    const entity_id = this._entityId();
    if (!entity_id) return;
    this._hass.callService("remote", "send_command", { entity_id, command });
    // Match the rest of the dashboard's press feedback.
    this.dispatchEvent(new CustomEvent("haptic", { bubbles: true, composed: true, detail: "light" }));
  }
}

/** Same behaviour, fewer buttons. */
class VidaaRemoteCompactCard extends VidaaRemoteCard {
  get _layout() {
    return COMPACT_LAYOUT;
  }

  getCardSize() {
    return 7;
  }
}

// Guarded: the integration injects this module itself, but the companion app's
// WebView often misses that injection, so users also add it as a Lovelace
// resource. Both paths loading is normal -- a bare define() would throw.
if (!customElements.get("vidaa-remote-card")) {
  customElements.define("vidaa-remote-card", VidaaRemoteCard);
  customElements.define("vidaa-remote-compact-card", VidaaRemoteCompactCard);

  window.customCards = window.customCards || [];
  window.customCards.push(
    {
      type: "vidaa-remote-card",
      name: "VIDAA TV Remote",
      description: "The full handset layout for a Hisense/Toshiba VIDAA TV.",
      preview: true,
    },
    {
      type: "vidaa-remote-compact-card",
      name: "VIDAA TV Remote (compact)",
      description: "The everyday controls only — about half the height.",
      preview: true,
    },
  );
}
