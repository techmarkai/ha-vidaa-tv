"""Generate the brand assets Home Assistant and HACS expect.

    python tools/make_brand.py

Writes into custom_components/vidaa_tv/brand/:

    logo.png / logo@2x.png   the VIDAA wordmark, background removed
    icon.png / icon@2x.png   a square television mark in the VIDAA gradient

Since Home Assistant 2026.3 a custom integration ships its own brand images in
custom_components/<domain>/brand/, and those take priority over the brands CDN.
The home-assistant/brands repository no longer accepts custom integration
icons, so there is nothing to submit upstream.

Icons must be square, so the wordmark cannot be one without leaving most of the
canvas empty. The square mark therefore reuses VIDAA's gradient, sampled from
the wordmark itself, on a generic television silhouette.

VIDAA is a trademark of Hisense. The wordmark is included for identification of
the devices this integration controls, which is the same basis on which Home
Assistant's own brands repository carries vendor logos.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(__file__).resolve().parent / "vidaa-wordmark.jpg"
OUT = ROOT / "custom_components" / "vidaa_tv" / "brand"

SCREEN = (26, 12, 40, 255)      # near-black plum, so the gradient reads as the frame
ARC = (255, 255, 255, 255)
SUPERSAMPLE = 4


def wordmark() -> Image.Image:
    """Load the wordmark and knock the white background out to transparency."""
    img = Image.open(SOURCE).convert("RGB")
    px = img.load()
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    op = out.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = px[x, y]
            # Strokes are saturated, the background is pure white. Scaling the
            # distance from white keeps strokes fully opaque while leaving the
            # antialiased edges soft, rather than unpremultiplying into
            # half-transparent letters that vanish on dark backgrounds.
            alpha = min(255, (255 - min(r, g, b)) * 4)
            if alpha:
                op[x, y] = (r, g, b, alpha)
    return out.crop(out.getbbox())


def gradient_stops(mark: Image.Image, count: int = 24) -> list[tuple[int, int, int]]:
    """Average each vertical slice of the wordmark to recover its gradient."""
    px = mark.load()
    stops = []
    step = max(1, mark.width // count)
    for x0 in range(0, mark.width, step):
        totals = [0, 0, 0]
        seen = 0
        for x in range(x0, min(x0 + step, mark.width)):
            for y in range(0, mark.height, 2):      # every other row is plenty
                r, g, b, a = px[x, y]
                if a > 200:
                    totals[0] += r
                    totals[1] += g
                    totals[2] += b
                    seen += 1
        if seen:
            stops.append(tuple(t // seen for t in totals))
    return stops


def gradient_image(size: int, stops: list[tuple[int, int, int]]) -> Image.Image:
    """A horizontal gradient interpolated across the sampled stops."""
    grad = Image.new("RGB", (len(stops), 1))
    grad.putdata(stops)
    return grad.resize((size, size), Image.BICUBIC)


def _silhouette(canvas: int) -> Image.Image:
    """White-on-black mask of the television frame, minus the screen cutout."""
    mask = Image.new("L", (canvas, canvas), 0)
    d = ImageDraw.Draw(mask)
    u = canvas / 256
    left, right = 6 * u, 250 * u
    top, bottom = 14 * u, 188 * u

    d.rounded_rectangle([left, top, right, bottom], radius=24 * u, fill=255)
    inset = 17 * u
    d.rounded_rectangle(
        [left + inset, top + inset, right - inset, bottom - inset],
        radius=11 * u, fill=0,
    )

    neck_w, neck_h = 30 * u, 18 * u
    cx = canvas / 2
    d.rectangle([cx - neck_w, bottom - u, cx + neck_w, bottom + neck_h], fill=255)
    foot_w = 88 * u
    d.rounded_rectangle(
        [cx - foot_w, bottom + neck_h, cx + foot_w, bottom + neck_h + 22 * u],
        radius=11 * u, fill=255,
    )
    return mask


def build_icon(size: int, stops: list[tuple[int, int, int]]) -> Image.Image:
    canvas = size * SUPERSAMPLE
    u = canvas / 256

    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Screen first, so the gradient frame paints over its edges.
    left, right, top, bottom = 6 * u, 250 * u, 14 * u, 188 * u
    inset = 17 * u
    d.rounded_rectangle(
        [left + inset, top + inset, right - inset, bottom - inset],
        radius=11 * u, fill=SCREEN,
    )

    # Signal arcs — the TV is driven over the network.
    cx = canvas / 2
    cy = top + (bottom - top) * 0.66
    for i, radius in enumerate((26, 46, 66)):
        r = radius * u
        d.arc([cx - r, cy - r, cx + r, cy + r], start=202, end=338,
              fill=ARC[:3] + (255 - i * 55,), width=max(1, int(7 * u)))
    dot = 8 * u
    d.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=ARC)

    frame = gradient_image(canvas, stops).convert("RGBA")
    frame.putalpha(_silhouette(canvas))
    img.alpha_composite(frame)

    bbox = img.getbbox()
    img = img.crop(bbox)
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return square.resize((size, size), Image.LANCZOS)


def build_logo(mark: Image.Image, height: int) -> Image.Image:
    width = round(mark.width * height / mark.height)
    return mark.resize((width, height), Image.LANCZOS)


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source wordmark: {SOURCE}")

    OUT.mkdir(parents=True, exist_ok=True)
    mark = wordmark()
    stops = gradient_stops(mark)
    print(f"wordmark {mark.width}x{mark.height}, {len(stops)} gradient stops "
          f"{stops[0]} -> {stops[-1]}")

    build_icon(256, stops).save(OUT / "icon.png", optimize=True)
    build_icon(512, stops).save(OUT / "icon@2x.png", optimize=True)
    # Logo spec: shortest side 128-256 normal, 256-512 hDPI.
    build_logo(mark, 256).save(OUT / "logo.png", optimize=True)
    build_logo(mark, 512).save(OUT / "logo@2x.png", optimize=True)

    for f in sorted(OUT.glob("*.png")):
        with Image.open(f) as im:
            x0, y0, x1, y1 = im.getbbox()
            pad = max(x0, y0, im.width - x1, im.height - y1) / max(im.size)
            print(f"{f.name}: {im.width}x{im.height} {im.mode} "
                  f"{f.stat().st_size}B padding={pad:.1%}")
            if f.name.startswith("icon") and im.width != im.height:
                raise SystemExit(f"{f.name} must be square")


if __name__ == "__main__":
    main()
