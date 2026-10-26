"""Draws the EZ Tag icon (round, colorful, a tag with a music note)."""
import math, sys, os
from PIL import Image, ImageDraw, ImageFilter

S = 1024
out = sys.argv[1] if len(sys.argv) > 1 else "app/assets"
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
# gradient disc: purple -> pink -> orange
grad = Image.new("RGBA", (S, S))
gp = grad.load()
c1, c2, c3 = (95, 61, 196), (214, 51, 108), (247, 103, 7)
for y in range(S):
    for x in range(0, S, 1):
        t = (x + y) / (2 * S)
        if t < .55:
            k = t / .55; a, b = c1, c2
        else:
            k = (t - .55) / .45; a, b = c2, c3
        gp[x, y] = tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)) + (255,)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).ellipse((24, 24, S - 24, S - 24), fill=255)
img.paste(grad, (0, 0), mask)
# soft shadow tag
tag = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(tag)
pts = [(250, 300), (620, 300), (800, 512), (620, 724), (250, 724)]
d.rounded_rectangle((250, 300, 700, 724), radius=70, fill=(255, 255, 255, 255))
d.polygon(pts, fill=(255, 255, 255, 255))
d.ellipse((300, 470, 360, 530), fill=(0, 0, 0, 0))  # hole
# music note (purple)
note = (112, 72, 232, 255)
d.ellipse((380, 560, 500, 660), fill=note)
d.ellipse((540, 520, 660, 620), fill=note)
d.rectangle((470, 380, 500, 610), fill=note)
d.rectangle((630, 340, 660, 570), fill=note)
d.polygon([(470, 380), (660, 340), (660, 410), (470, 450)], fill=note)
tag = tag.rotate(-18, resample=Image.BICUBIC, center=(512, 512))
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
shadow.paste((0, 0, 0, 90), (0, 0), tag.split()[3])
shadow = shadow.filter(ImageFilter.GaussianBlur(18))
img.alpha_composite(shadow, (14, 22))
img.alpha_composite(tag)
# yellow sparkle
sp = ImageDraw.Draw(img)
cx, cy, r = 770, 260, 70
sp.polygon([(cx, cy - r), (cx + 18, cy - 18), (cx + r, cy), (cx + 18, cy + 18), (cx, cy + r),
            (cx - 18, cy + 18), (cx - r, cy), (cx - 18, cy - 18)], fill=(255, 212, 59, 255))
os.makedirs(out, exist_ok=True)
big = img.resize((256, 256), Image.LANCZOS)
big.save(os.path.join(out, "ez-tag.png"))
img.resize((512, 512), Image.LANCZOS).save(os.path.join(out, "ez-tag-512.png"))
big.save(os.path.join(out, "ez-tag.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon written to", out)
