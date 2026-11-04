from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BASE_DIR / "static" / "ducks"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SIZE = (640, 480)

LEVELS = [
    (0, "duck_0.png", "Hatchling"),
    (10, "duck_10.png", "Brave"),
    (25, "duck_25.png", "Glitter"),
    (50, "duck_50.png", "Mythic"),
    (100, "duck_100.png", "Arcane"),
    (300, "duck_300.png", "Stellar"),
    (500, "duck_500.png", "Eternal"),
    (700, "duck_700.png", "Celestial"),
    (1000, "duck_1000.png", "Legend"),
]

BG_COLORS = [
    (251, 242, 219),
    (255, 236, 200),
    (253, 228, 193),
    (243, 221, 208),
    (230, 235, 244),
    (217, 231, 242),
    (200, 226, 240),
    (189, 222, 241),
    (173, 217, 242),
]

ORNAMENT_COLORS = [
    (217, 107, 43),
    (245, 156, 66),
    (246, 195, 92),
    (255, 213, 119),
    (197, 120, 238),
    (115, 182, 255),
    (102, 206, 182),
    (142, 232, 126),
    (255, 112, 132),
]


def draw_stars(draw: ImageDraw.ImageDraw, count: int, color: tuple[int, int, int]) -> None:
    for i in range(count):
        x = 50 + (i * 55) % (SIZE[0] - 100)
        y = 40 + (i * 33) % (SIZE[1] - 150)
        draw.regular_polygon((x, y, 12), 5, fill=color, outline=None)


def draw_duck(draw: ImageDraw.ImageDraw, accent: tuple[int, int, int], level: int) -> None:
    body = (240, 199, 82)
    head = (248, 210, 102)
    beak = (216, 102, 37)
    wing = (230, 180, 76)

    # Body
    draw.ellipse((140, 220, 510, 400), fill=body)
    draw.ellipse((210, 170, 360, 320), fill=body)
    # Wing
    draw.ellipse((260, 245, 440, 360), fill=wing)
    # Head
    draw.ellipse((370, 140, 510, 280), fill=head)
    # Eye
    draw.ellipse((445, 190, 470, 215), fill=(30, 30, 30))
    draw.ellipse((452, 197, 462, 207), fill=(255, 255, 255))
    # Beak
    draw.polygon([(505, 225), (575, 250), (505, 260)], fill=beak)

    # Extra flair per level
    if level >= 10:
        draw.regular_polygon((420, 120, 22), 5, fill=accent)
    if level >= 25:
        draw_stars(draw, 6, accent)
    if level >= 50:
        draw.arc((120, 120, 520, 420), 200, 320, width=6, fill=accent)
    if level >= 100:
        draw.rounded_rectangle((160, 90, 480, 130), radius=18, fill=accent)
    if level >= 300:
        draw.regular_polygon((130, 180, 30), 8, fill=accent)
        draw.regular_polygon((520, 320, 26), 8, fill=accent)
    if level >= 500:
        draw.rectangle((70, 390, 570, 420), fill=accent)
    if level >= 700:
        draw.pieslice((30, 40, 160, 170), 20, 320, fill=accent)
        draw.pieslice((480, 40, 610, 170), 220, 520, fill=accent)
    if level >= 1000:
        draw.ellipse((240, 40, 400, 200), outline=accent, width=10)


def draw_label(draw: ImageDraw.ImageDraw, text: str) -> None:
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((24, 24), text, fill=(20, 30, 35), font=font)


def main() -> None:
    for idx, (level, filename, label) in enumerate(LEVELS):
        image = Image.new("RGB", SIZE, BG_COLORS[idx])
        draw = ImageDraw.Draw(image)
        accent = ORNAMENT_COLORS[idx]
        draw_duck(draw, accent, level)
        draw_label(draw, label)
        image.save(OUT_DIR / filename)


if __name__ == "__main__":
    main()
