"""Generate the brand assets HACS and Home Assistant expect.

    python tools/make_brand.py

Writes icon/logo PNGs into custom_components/vidaa_tv/brand/.

Two rules from home-assistant/brands drive the design:

1. "Custom integrations must not use Home Assistant branded images, as this
   might confuse the end-user into thinking that the integration is an official
   integration." So the palette deliberately avoids Home Assistant's blue.
2. "The image should be trimmed, so it contains the minimum amount of empty
   space on the edges." So the drawing is auto-cropped to its content and then
   padded only as far as the required 1:1 aspect ratio demands.

The mark is a generic television. VIDAA, Hisense and Toshiba are other people's
trademarks and must not be shipped inside a third-party integration.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "vidaa_tv" / "brand"

# Teal and amber: legible on both light and dark backgrounds, and clearly not
# Home Assistant's palette.
BEZEL = (0, 150, 136, 255)
SCREEN = (16, 42, 40, 255)
GLOW = (255, 202, 64, 255)

SUPERSAMPLE = 4


def _render(canvas: int) -> Image.Image:
    """Draw the mark on a `canvas`-sized square, using a 256-unit design grid."""
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = canvas / 256

    left, right = 6 * u, 250 * u
    body_top, body_bottom = 14 * u, 188 * u

    d.rounded_rectangle([left, body_top, right, body_bottom], radius=24 * u, fill=BEZEL)

    inset = 17 * u
    d.rounded_rectangle(
        [left + inset, body_top + inset, right - inset, body_bottom - inset],
        radius=11 * u,
        fill=SCREEN,
    )

    # Signal arcs: this TV is driven over the network, so the mark says so.
    cx = canvas / 2
    cy = body_top + (body_bottom - body_top) * 0.66
    for i, radius in enumerate((26, 46, 66)):
        r = radius * u
        d.arc(
            [cx - r, cy - r, cx + r, cy + r],
            start=202, end=338,
            fill=GLOW[:3] + (255 - i * 50,),
            width=max(1, int(7 * u)),
        )
    dot = 8 * u
    d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=GLOW)

    # Stand
    neck_w, neck_h = 30 * u, 18 * u
    d.rectangle([cx - neck_w, body_bottom - u, cx + neck_w, body_bottom + neck_h], fill=BEZEL)
    foot_w = 88 * u
    d.rounded_rectangle(
        [cx - foot_w, body_bottom + neck_h, cx + foot_w, body_bottom + neck_h + 22 * u],
        radius=11 * u,
        fill=BEZEL,
    )
    return img


def build(size: int) -> Image.Image:
    """Render big, trim to content, pad to square, then downsample."""
    img = _render(size * SUPERSAMPLE)

    bbox = img.getbbox()          # alpha-aware: exact content bounds
    if bbox is None:
        raise RuntimeError("drew nothing")
    img = img.crop(bbox)

    # Icons must be 1:1, so pad the shorter axis only.
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))

    return square.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        img = build(size)
        img.save(OUT / name, optimize=True)

    # Logo is optional and falls back to the icon, but shipping it keeps the
    # HACS in-repo brands check happy without a second design.
    build(256).save(OUT / "logo.png", optimize=True)
    build(512).save(OUT / "logo@2x.png", optimize=True)

    for f in sorted(OUT.glob("*.png")):
        with Image.open(f) as im:
            x0, y0, x1, y1 = im.getbbox()
            # Content fills the width; the icon must be 1:1, so a landscape
            # mark keeps a little padding above and below. Report how much.
            pad = max(x0, y0, im.width - x1, im.height - y1) / im.width
            print(f"{f.name}: {im.width}x{im.height} {im.mode} "
                  f"{f.stat().st_size}B padding={pad:.1%}")
            if pad > 0.10:
                raise SystemExit(f"{f.name}: {pad:.1%} padding is too much")


if __name__ == "__main__":
    main()
