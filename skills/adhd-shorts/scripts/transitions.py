"""transitions.py — раскладки кадра и переходы между ними (для render.py, вертикаль 1080×1920).

Раскладка («состояние») описывается геометрией: где лицо (прямоугольник + аффинное преобразование исходного кадра,
скругление, рамка-карточка) и где графика (прямоугольник + вертикальный сдвиг содержимого). Состояния:
  face  — только лицо;   split — графика сверху, лицо снизу;   full — графика на весь кадр;
  pip   — графика на весь кадр, лицо в карточке/кружке поверх.
Переход morph интерполирует геометрию (лицо съезжает/сжимается в карточку, графика выталкивает его), остальные
смешивают два готовых кадра: whip (резкий свайп), zoom (зум сквозь кадр), glitch, iris (круглая шторка), flash,
blur, slide (шторка-лист снизу). Размытие движения — усреднением подкадров внутри одного кадра (выдержка 180°).
2026-10-17, автор: «переходы классные, качественные… не как сейчас (фейд), что-нибудь нишевое и трендовое»."""
import math
import numpy as np, cv2

DUR = dict(morph=0.42, whip=0.26, zoom=0.32, glitch=0.2, iris=0.4, flash=0.26, blur=0.32, slide=0.4,
           leak=0.4, flicker=0.24, defocus=0.36, slit=0.45, invert=0.14, pulse=0.4)
# из разборов референсов (youtube/Ресерч/2026-10-17-моушн-разбор): leak — засветка плёнки, прячет джамп-кат на лице;
# flicker — мигание лампы с рывком наезда; defocus — расфокус-склейка; slit — кадр сжимается в щель с белой линией;
# invert — один кадр негатива + пролетающая полоса («миф/реальность»); pulse — ударная волна (iris с широким кольцом)
BLUR_KINDS = {"zoom"}                    # зуму — усреднение подкадров; свайпу и шторке — направленное размытие по скорости
SOUND = dict(morph="whoosh", whip="whoosh", slide="whoosh", zoom="rise", glitch="glitch", iris="sparkle", flash="sparkle", blur=None,
             leak="boom", flicker="glitch", defocus="whoosh", slit="whoosh", invert="punch", pulse="boom")


def clip01(p): return min(1.0, max(0.0, p))
def inout_expo(p):
    p = clip01(p)
    if p in (0.0, 1.0): return p
    return 2 ** (20 * p - 10) / 2 if p < 0.5 else (2 - 2 ** (-20 * p + 10)) / 2
def inout_cubic(p): p = clip01(p); return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2
def out_cubic(p): p = clip01(p); return 1 - (1 - p) ** 3
def out_back(p, s=1.3): p = clip01(p) - 1; return 1 + (s + 1) * p ** 3 + s * p ** 2


def geo(fa, fr, gr, gs=0.0, rad=0.0, card=0.0):
    """fa — (k, tx, ty): исходный кадр → выход (x' = k·x + tx); fr — прямоугольник лица (x, y, w, h);
    gr — прямоугольник графики; gs — сдвиг содержимого графики по вертикали; rad — скругление; card — рамка и тень."""
    return dict(fa=np.array(fa, float), fr=np.array(fr, float), gr=np.array(gr, float), gs=float(gs), rad=float(rad), card=float(card))
def lerp(a, b, e): return {k: a[k] + (b[k] - a[k]) * e for k in a}


def rr_mask(w, h, r):
    """Скруглённый прямоугольник w×h → маска float32 0..1 со сглаженными краями."""
    w, h = int(round(w)), int(round(h))
    if w < 1 or h < 1: return None
    r = int(max(0, min(r, w / 2 - 1, h / 2 - 1)))
    m = np.zeros((h, w), np.uint8)
    if r < 2: m[:] = 255
    else:
        cv2.rectangle(m, (r, 0), (w - 1 - r, h - 1), 255, -1); cv2.rectangle(m, (0, r), (w - 1, h - 1 - r), 255, -1)
        for cx, cy in ((r, r), (w - 1 - r, r), (r, h - 1 - r), (w - 1 - r, h - 1 - r)): cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m.astype(np.float32) / 255


def _paste(out, patch, alpha, x, y):
    """Накладывает patch (h×w×3 или цвет) с маской alpha (h×w) в точку (x, y), обрезая по краям кадра."""
    H, W = out.shape[:2]; h, w = alpha.shape
    xa, ya, xb, yb = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if xa >= xb or ya >= yb: return
    a = alpha[ya - y:yb - y, xa - x:xb - x][..., None]
    src = patch[ya - y:yb - y, xa - x:xb - x] if isinstance(patch, np.ndarray) and patch.ndim == 3 else np.array(patch, np.float32)
    roi = out[ya:yb, xa:xb]; roi[:] = (roi * (1 - a) + src * a).astype(np.uint8)


def compose(g, last, glast, W, H):
    """Кадр по геометрии: графика (glast) в своём прямоугольнике, поверх — лицо из исходного кадра last."""
    out = np.zeros((H, W, 3), np.uint8)
    x, y, w, h = g["gr"]
    y0, y1 = max(0, int(round(y))), min(H, int(round(y + h)))
    if y1 > y0 and w > 1:
        gs = int(round(g["gs"])); s0, s1 = y0 - gs, y1 - gs                 # строки glast для этих строк выхода
        c0, c1 = max(0, s0), min(glast.shape[0], s1)
        if c1 > c0: out[y0 + (c0 - s0):y0 + (c0 - s0) + (c1 - c0)] = glast[c0:c1, :W]
    x, y, w, h = g["fr"]
    if w >= 2 and h >= 2:
        bx, by, bw, bh = int(math.floor(x)), int(math.floor(y)), int(math.ceil(w)), int(math.ceil(h))
        k, tx, ty = g["fa"]
        if g["card"] > 0.01:                                                  # тень и светлая рамка карточки
            sh = rr_mask(bw + 60, bh + 60, g["rad"] + 30)
            if sh is not None:
                sh = cv2.GaussianBlur(sh, (0, 0), 16) * 0.5 * g["card"]; _paste(out, (0, 0, 0), sh, bx - 30, by - 14)
            b = 6; ring = rr_mask(bw + 2 * b, bh + 2 * b, g["rad"] + b)
            if ring is not None: _paste(out, (245, 245, 250), ring * g["card"], bx - b, by - b)
        patch = cv2.warpAffine(last, np.float32([[k, 0, tx - bx], [0, k, ty - by]]), (bw, bh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        m = rr_mask(bw, bh, g["rad"])
        if m is not None: _paste(out, patch, m, bx, by)
    return out


# ---------- переходы по двум готовым кадрам ----------
def _shift(img, dx, dy):
    return cv2.warpAffine(img, np.float32([[1, 0, dx], [0, 1, dy]]), (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_CONSTANT)
def _scale(img, s, c=None):
    H, W = img.shape[:2]; cx, cy = c or (W / 2, H / 2)
    return cv2.warpAffine(img, np.float32([[s, 0, cx - s * cx], [0, s, cy - s * cy]]), (W, H), borderMode=cv2.BORDER_REFLECT)

def mix1(kind, A, B, p, opt):
    """Один подкадр перехода kind на прогрессе p (0..1)."""
    H, W = A.shape[:2]
    if kind == "whip":
        d = opt.get("dir", "up"); L = H if d in ("up", "down") else W; s = -1 if d in ("up", "left") else 1
        o = inout_expo(p) * L * s; v = int(abs(inout_expo(opt.get("p1", p)) - inout_expo(opt.get("p0", p))) * L)   # сдвиг за выдержку
        if d in ("up", "down"):
            out = np.maximum(_shift(A, 0, o), _shift(B, 0, o - s * L))
            return cv2.blur(out, (1, v)) if v > 2 else out
        out = np.maximum(_shift(A, o, 0), _shift(B, o - s * L, 0))
        return cv2.blur(out, (v, 1)) if v > 2 else out
    if kind == "zoom":
        e = inout_cubic(p); c = opt.get("center")
        if e < 0.5: return _scale(A, 1 + 1.4 * (e / 0.5) ** 2, c)
        return _scale(B, 1 + 1.4 * (1 - (e - 0.5) / 0.5) ** 2, c)
    if kind == "slide":
        e = out_cubic(p); y = int(round(H * (1 - e))); v = int(abs(out_cubic(opt.get("p1", p)) - out_cubic(opt.get("p0", p))) * H)
        a = (_scale(A, 1 - 0.07 * e) * (1 - 0.45 * e)).astype(np.uint8); out = a.copy()
        if y < H:
            sh = rr_mask(W, 140, 0) * np.linspace(0, 0.55, 140)[:, None]       # тень над листом
            _paste(out, (0, 0, 0), sh, 0, y - 140)
            m = rr_mask(W, H + 60, 56)[:H]
            if v > 2: m = cv2.blur(m, (1, v)); B = cv2.blur(B, (1, v))      # лист смазан по скорости
            _paste(out, B, m, 0, y)
        return out
    if kind == "iris":
        e = inout_cubic(p); cx, cy = opt.get("center", (W / 2, H * 0.42)); R = e * math.hypot(max(cx, W - cx), max(cy, H - cy)) * 1.02
        m = np.zeros((H, W), np.uint8); cv2.circle(m, (int(cx), int(cy)), int(R), 255, -1, cv2.LINE_AA)
        mf = cv2.GaussianBlur(m, (0, 0), 3).astype(np.float32)[..., None] / 255
        out = A * (1 - mf) + B * mf
        if 0.02 < e < 0.98 and opt.get("ring", True):                         # тонкое светлое кольцо по краю шторки
            ring = np.zeros((H, W), np.uint8); cv2.circle(ring, (int(cx), int(cy)), int(R), 255, 6, cv2.LINE_AA)
            rf = cv2.GaussianBlur(ring, (0, 0), 4).astype(np.float32)[..., None] / 255 * (1 - e) * 0.9
            out = out * (1 - rf) + 255 * rf
        return np.clip(out, 0, 255).astype(np.uint8)
    if kind == "flash":
        k = math.sin(math.pi * clip01(p)) ** 2.5; base = A if p < 0.5 else B      # короткий пик белого в середине
        small = cv2.resize(base, (W // 4, H // 4)); bloom = cv2.resize(cv2.GaussianBlur(small, (0, 0), 12), (W, H)).astype(np.float32)
        out = base.astype(np.float32) * (1 - 0.35 * k) + bloom * 0.35 * k
        return np.clip(out + (255 - out) * 0.8 * k, 0, 255).astype(np.uint8)
    if kind == "blur":
        k = math.sin(math.pi * clip01(p)); e = inout_cubic(p)
        out = A.astype(np.float32) * (1 - e) + B.astype(np.float32) * e
        if k > 0.02:
            small = cv2.resize(out, (W // 4, H // 4)); bl = cv2.resize(cv2.GaussianBlur(small, (0, 0), 1 + 9 * k), (W, H))
            out = out * (1 - k) + bl * k
        return np.clip(out, 0, 255).astype(np.uint8)
    if kind == "leak":
        # синий слева → красная полоса прожога → пересвет (тут склейка) → бирюзовый хвост; поверх зерно
        rng = np.random.default_rng(opt.get("seed", 0)); k = math.sin(math.pi * clip01(p)); base = (A if p < 0.5 else B).astype(np.float32)
        yy, xx = np.mgrid[0:H:8, 0:W:8].astype(np.float32); cy, cx = H * (0.25 + 0.5 * rng.random()), W * (0.2 + 0.6 * rng.random())
        band = np.exp(-((yy - cy) / (H * 0.18)) ** 2)[..., None] * np.array([28, 42, 154], np.float32) * 1.6
        burn = np.exp(-((xx - cx) / (W * 0.12)) ** 2)[..., None] * np.array([176, 16, 42], np.float32) * 1.8
        blob = np.exp(-(((xx - cx) / (W * 0.3)) ** 2 + ((yy - cy) / (H * 0.25)) ** 2))[..., None] * np.array([200, 90, 190], np.float32) * 0.7
        leak = band * clip01(1.6 - 2 * p) + burn * math.sin(math.pi * clip01(p * 1.4)) + blob * k + np.array([60, 200, 170], np.float32) * clip01(2 * p - 1) * (1 - p) * 0.8
        leak = cv2.resize(leak, (W, H)) * k * 0.75; out = 255 - (255 - base) * (255 - np.clip(leak, 0, 255)) / 255   # screen
        out += (255 - out) * max(0.0, k - 0.9) * 7                                                                        # пересвет только на пике (склейка)
        out += rng.normal(0, 7 * k, (H // 2, W // 2, 1)).repeat(2, 0).repeat(2, 1)[:H, :W]                              # зерно
        return np.clip(out, 0, 255).astype(np.uint8)
    if kind == "flicker":
        steps = [1, .55, 0, .55, 1, .6]; i = min(len(steps) - 1, int(clip01(p) / 0.7 * len(steps)))
        if p >= 0.7: return B
        s_ = 1.06 + 0.19 * (i / (len(steps) - 1)) if i >= 2 else 1.0
        return (_scale(A, s_) * steps[i]).astype(np.uint8)
    if kind == "defocus":
        if p < 0.45:
            q = p / 0.45; img = _scale(A, 1 - 0.03 * q); img = _shift(img, opt.get("dx", 0) * q, 0) if opt.get("dx") else img; sg = 20 * q
        else:
            q = (p - 0.45) / 0.55; img = _scale(B, 1.03 - 0.03 * out_cubic(q)); sg = 24 * (1 - out_cubic(q))
        if sg < 0.6: return img
        small = cv2.resize(img, (W // 4, H // 4)); return cv2.resize(cv2.GaussianBlur(small, (0, 0), sg / 4), (W, H))
    if kind == "slit":
        if p < 0.82:
            e = inout_expo(p / 0.82); w = max(2, int(W * (1 - e))); x0 = (W - w) // 2
            out = np.zeros_like(A); out[:, x0:x0 + w] = cv2.resize(A, (w, H)); return out
        out = B.copy(); a = 1 - (p - 0.82) / 0.18; lw = 6
        out[:, W // 2 - lw:W // 2 + lw] = (out[:, W // 2 - lw:W // 2 + lw] * (1 - a) + 255 * a).astype(np.uint8); return out
    if kind == "invert":
        base = A if p < 0.5 else B; out = 255 - base if 0.3 < p < 0.7 else base.copy()
        y = int(H * (1.2 - 1.4 * clip01(p))); hh = int(H * 0.05)
        m = np.zeros((H, W), np.uint8); cv2.ellipse(m, (W // 2, y), (int(W * 0.72), hh), 0, 0, 360, 255, -1, cv2.LINE_AA)
        mf = cv2.GaussianBlur(m, (0, 0), 6).astype(np.float32)[..., None] / 255
        return np.clip(out * (1 - mf) + 255 * mf, 0, 255).astype(np.uint8)
    if kind == "pulse":
        e = math.pow(clip01(p), 2.2); cx, cy = opt.get("center", (W / 2, H * 0.45)); R = e * math.hypot(W, H) * 1.05
        m = np.zeros((H, W), np.uint8); cv2.circle(m, (int(cx), int(cy)), int(R), 255, -1, cv2.LINE_AA)
        mf = cv2.GaussianBlur(m, (0, 0), 3).astype(np.float32)[..., None] / 255
        bs = _scale(B, 0.6 + 0.4 * out_cubic(p), (cx, cy)); out = A * (1 - mf) + bs * mf
        ring = np.zeros((H, W), np.uint8); cv2.circle(ring, (int(cx), int(cy)), int(R), 255, 40, cv2.LINE_AA)
        rf = cv2.GaussianBlur(ring, (0, 0), 24).astype(np.float32)[..., None] / 255 * 0.35 * (1 - e)
        return np.clip(out * (1 - rf) + 255 * rf, 0, 255).astype(np.uint8)
    if kind == "glitch":
        rng = np.random.default_rng(int(p * 997) + opt.get("seed", 0)); k = math.sin(math.pi * clip01(p))
        base = (A if p < 0.5 else B).copy(); other = B if p < 0.5 else A
        for _ in range(int(4 + 10 * k)):                                      # горизонтальные полосы сдвигаются и меняются местами
            y0 = int(rng.integers(0, H - 20)); hh = int(rng.integers(8, 90)); dx = int(rng.integers(-90, 90) * k)
            src = other if rng.random() < 0.3 else base
            base[y0:y0 + hh] = np.roll(src[y0:y0 + hh], dx, axis=1)
        s = int(26 * k); out = base.copy()
        if s: out[..., 0] = np.roll(base[..., 0], -s, axis=1); out[..., 2] = np.roll(base[..., 2], s, axis=1)   # RGB-сдвиг
        out[::4] = (out[::4] * (1 - 0.25 * k)).astype(np.uint8)                                            # строки развёртки
        for _ in range(int(6 * k)):                                           # цифровые блоки
            bx, by = int(rng.integers(0, W - 120)), int(rng.integers(0, H - 60)); bw, bh = int(rng.integers(30, 160)), int(rng.integers(10, 50))
            out[by:by + bh, bx:bx + bw] = rng.integers(0, 255, 3)
        return out
    return B if p >= 0.5 else A

def mix(kind, A, B, ps, opt=None):
    """Переход с размытием движения: среднее подкадров на прогрессах ps."""
    opt = dict(opt or {}, p0=ps[0], p1=ps[-1])
    if kind not in BLUR_KINDS or len(ps) == 1: return mix1(kind, A, B, ps[len(ps) // 2], opt)
    acc = np.zeros(A.shape, np.float32)
    for p in ps: acc += mix1(kind, A, B, p, opt)
    return (acc / len(ps)).astype(np.uint8)
