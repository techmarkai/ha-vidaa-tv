"""Generate the brand assets HACS and Home Assistant expect.

    python tools/make_brand.py

Writes icon/logo PNGs into custom_components/vidaa_tv/brand/. Deliberately a
generic television mark: VIDAA, Hisense and Toshiba are other people's
trademarks and must not be shipped in a third-party integration.

Home Assistant brand spec: square icons at 256 and 512, transparent
background, trimmed to minimal padding.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "vidaa_tv" / "brand"

# Home Assistant's palette, so the mark sits naturally in the HA UI.
BEZEL = (3, 169, 244, 255)      # ha blue
SCREEN = (13, 44, 66, 255)      # deep slate
GLOW = (77, 208, 225, 255)      # cyan accent


def draw(size: int) -> Image.Image:
    """Draw at 4x then downsample — cheap antialiasing without extra deps."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    unit = s / 256          # design on a 256 grid, scale up
    pad = 14 * unit
    body_top = 26 * unit
    body_bottom = 190 * unit
    radius = 22 * unit

    # TV body
    d.rounded_rectangle(
        [pad, body_top, s - pad, body_bottom], radius=radius, fill=BEZEL
    )
    # Screen
    inset = 16 * unit
    d.rounded_rectangle(
        [pad + inset, body_top + inset, s - pad - inset, body_bottom - inset],
        radius=10 * unit,
        fill=SCREEN,
    )

    # Signal arcs — this TV is driven over the network, so say so.
    cx, cy = s / 2, body_top + (body_bottom - body_top) * 0.62
    for i, r in enumerate((22, 40, 58)):
        rr = r * unit
        width = max(1, int(6 * unit))
        alpha = 255 - i * 55
        d.arc(
            [cx - rr, cy - rr, cx + rr, cy + rr],
            start=200, end=340,
            fill=GLOW[:3] + (alpha,),
            width=width,
        )
    dot = 7 * unit
    d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=GLOW)

    # Stand
    leg_w, leg_h = 52 * unit, 12 * unit
    d.rounded_rectangle(
        [cx - leg_w, body_bottom, cx + leg_w, body_bottom + leg_h],
        radius=leg_h / 2, fill=BEZEL,
    )
    foot_w = 84 * unit
    d.rounded_rectangle(
        [cx - foot_w, body_bottom + leg_h + 6 * unit,
         cx + foot_w, body_bottom + leg_h + 18 * unit],
        radius=6 * unit, fill=BEZEL,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon256 = draw(256)
    icon512 = draw(512)

    icon256.save(OUT / "icon.png")
    icon512.save(OUT / "icon@2x.png")
    # No wordmark to show, so the logo is the icon. Brands allows this.
    icon256.save(OUT / "logo.png")
    icon512.save(OUT / "logo@2x.png")

    for f in sorted(OUT.glob("*.png")):
        with Image.open(f) as im:
            print(f"{f.name}: {im.size[0]}x{im.size[1]} {im.mode}")


if __name__ == "__main__":
    main()
