# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy","soundfile"]
# ///
"""sfx_scan.py <root> "<glob>" [...] — подбор сэмплов: длина, где атака (onset) и пик, уровень.
Пример: uv run --script sfx_scan.py "~/Samples/Boom One/Split" "SWOOSHES/**/*.wav" "*/*/*Tadaaa*"
Для вжуха на склейке важен пик (он ставится ровно на склейку), для удара — onset (ставится на слово)."""
import glob, sys
from pathlib import Path
import numpy as np, soundfile as sf
root = Path(sys.argv[1]).expanduser()
for pat in sys.argv[2:]:
    files = sorted(glob.glob(str(root / pat), recursive=True))
    print(f"== {pat}: {len(files)}")
    for f in files:
        x, sr = sf.read(f, always_2d=True); e = np.abs(x).max(1)
        hop = max(1, sr // 200); env = np.array([e[i:i + hop].max() for i in range(0, len(e), hop)])
        pk = env.max() + 1e-12; on = np.argmax(env > pk * 0.1) * hop / sr; peak = env.argmax() * hop / sr
        print(f"  {len(x)/sr:5.2f}s  onset {on:4.2f}  peak {peak:4.2f}  {20*np.log10(pk):6.1f} dBFS  {Path(f).relative_to(root)}")
