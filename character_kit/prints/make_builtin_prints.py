"""The built-in prints for the Forge's wrap-unwrapped garments (T-shirt, tank top, shorts, jeans).

    python character_kit/prints/make_builtin_prints.py

A print covers a garment's whole layout (front on the left half, back on the right), about a metre of
cloth across, so the kit's 256 px fabric tiles are repeated 8 x 8 into a 2048 px image: the same
weave as the suits and shirts, tinted by the garment's colour in the Forge.
"""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
for out, src in (('cotton', 'cloth'), ('twill', 'suitcloth')):
    tile = Image.open(ROOT / 'assets' / 'materials' / f'{src}.png').convert('RGB')
    img = Image.new('RGB', (tile.width * 8, tile.height * 8))
    for i in range(8):
        for j in range(8):
            img.paste(tile, (i * tile.width, j * tile.height))
    path = ROOT / 'assets' / 'textures' / f'print_{out}.png'
    img.save(path, optimize=True)
    print('wrote', path, img.size)
