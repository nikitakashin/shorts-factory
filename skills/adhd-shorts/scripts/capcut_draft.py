"""capcut_draft.py <workdir> <draft name> [--template <папка черновика>] [--insert <видео в конец>] [--insert-gain-db 9]

Собирает ЧЕРНОВИК CapCut (desktop 9.x) из готового монтажа adhd-shorts, чтобы автор мог сам двигать склейки,
звуки и субтитры прямо в CapCut и экспортировать оттуда. Читает из workdir:
  edl_out.json — планы (исходник a..b, скорость, f0/n кадров выхода, z/z2 — зум);
  voice.wav — финальный голос (Adobe + цепочка), режется кусками под каждый план;
  sfx_list.json — какой звук где и на какой громкости (пишет render.py);
  overlays.json — субтитры по словам и плашки (пишет render.py);
  layout.json + gfx.mp4 — UI-панели (если есть): отдельная видеодорожка поверх.
Формат черновика CapCut недокументирован: структура клипов и материалов КЛОНИРУЕТСЯ из шаблона — черновика,
который автор сделал руками (видео с ключевыми кадрами масштаба, текст, звук, вторая видеодорожка).
CapCut должен быть закрыт: открытый CapCut перезапишет черновик своим состоянием.
Что не переносится (только в отрендеренном short.mp4): тряска, вспышки, «пунч»-зум на словах, подсветка
активного слова рисуется сменой цвета в отдельных текстовых клипах (по клипу на слово)."""
import argparse, copy, json, os, random, shutil, subprocess, time, uuid
from pathlib import Path

ROOT = Path.home() / "Movies/CapCut/User Data/Projects/com.lveditor.draft"
ap = argparse.ArgumentParser(); ap.add_argument("wd"); ap.add_argument("name")
ap.add_argument("--template", required=True, help="папка черновика-шаблона в ROOT, сделанного руками (см. README)"); ap.add_argument("--insert", default=None)
ap.add_argument("--insert-gain-db", type=float, default=9.0)
A = ap.parse_args(); WD = Path(A.wd).expanduser(); TPL = Path(A.template).expanduser()
if not TPL.is_absolute(): TPL = ROOT / TPL          # можно передать просто имя черновика-шаблона
if subprocess.run(["pgrep", "-x", "CapCut"], capture_output=True).returncode == 0:
    raise SystemExit("CapCut открыт — закрой его, иначе он перезапишет черновик")

US = 1_000_000
def uid(): return str(uuid.uuid4()).upper()
def us(t): return int(round(t * US))
J = json.load(open(TPL / "draft_info.json")); M = J["materials"]
E = json.load(open(WD / "edl_out.json")); FPS = E["fps"]; SP = E.get("speed", 1.15)
OV = json.load(open(WD / "overlays.json")); LAND = OV.get("landscape", False)
SFXL = json.load(open(WD / "sfx_list.json")) if (WD / "sfx_list.json").exists() else {"global_gain": 1, "sounds": []}
LAY = json.load(open(WD / "layout.json")) if (WD / "layout.json").exists() and (WD / "gfx.mp4").exists() else None
CW, CH = (1920, 1080) if LAND else (1080, 1920)

# ---------- шаблонные объекты ----------
by_id = {o["id"]: (k, o) for k, v in M.items() if isinstance(v, list) for o in v if isinstance(o, dict) and "id" in o}
def tpl_seg(kind):
    for t in J["tracks"]:
        if t["type"] == kind and t["segments"]: return t["segments"][0]
    raise SystemExit(f"в шаблоне нет дорожки {kind}")
SEG_V, SEG_A, SEG_T = tpl_seg("video"), tpl_seg("audio"), tpl_seg("text")
_vt = [t for t in J["tracks"] if t["type"] == "video" and t["segments"]]
SEG_V2 = _vt[1]["segments"][0] if len(_vt) > 1 else SEG_V      # клип второй видеодорожки (оверлей) — для панелей
TRK = {t["type"]: t for t in J["tracks"]}
NEW = {k: [] for k, v in M.items() if isinstance(v, list)}
def clone_refs(seg):
    refs = []
    for r in seg["extra_material_refs"]:
        k, o = by_id[r]; o = copy.deepcopy(o); o["id"] = uid(); NEW[k].append(o); refs.append((k, o))
    return refs
def probe(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height:stream_side_data=rotation",
                        "-of", "json", str(p)], capture_output=True, text=True).stdout
    d = json.loads(o); v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    w, h = (v["width"], v["height"]) if v else (0, 0)
    rot = abs(int(next((sd.get("rotation", 0) for sd in (v or {}).get("side_data_list", [])), 0) or 0))
    if rot in (90, 270): w, h = h, w
    return float(d["format"]["duration"]), w, h, any(s["codec_type"] == "audio" for s in d["streams"])

def video_mat(path):
    path = reachable(path)
    dur, w, h, ha = probe(path)
    o = copy.deepcopy(by_id[SEG_V["material_id"]][1]); o.update(id=uid(), path=str(path), material_name=Path(path).name,
        duration=us(dur), width=w, height=h, has_audio=ha, unique_id=uuid.uuid4().hex)
    NEW["videos"].append(o); return o
MEDIA = WD / "capcut_media"
def reachable(path):
    """CapCut не видит файлы в защищённых папках (Рабочий стол, Документы): 2026-10-12 звуки из ~/Desktop/…/Samples
    не нашлись («Link media»), а видео и голос из ~/Movies — нашлись. Всё вне ~/Movies копируем к проекту."""
    path = Path(path).expanduser().resolve()
    if str(path).startswith(str(Path.home() / "Movies")): return path
    MEDIA.mkdir(exist_ok=True)
    dst = MEDIA / f"{abs(hash(str(path))) % 10**8:08d}_{path.name}"
    if not dst.exists(): shutil.copy2(path, dst)
    return dst

def audio_mat(path):
    path = reachable(path)
    dur, *_ = probe(path)
    o = copy.deepcopy(by_id[SEG_A["material_id"]][1]); o.update(id=uid(), path=str(path), name=Path(path).name,
        duration=us(dur), unique_id=uuid.uuid4().hex, type="extract_music", wave_points=[])
    NEW["audios"].append(o); return o

def kf(prop, pts):
    return {"id": uid(), "material_id": "", "property_type": prop, "keyframe_list": [
        {"id": uid(), "curveType": "Line", "time_offset": t, "left_control": {"x": 0.0, "y": 0.0},
         "right_control": {"x": 0.0, "y": 0.0}, "values": [v], "string_value": "", "graphID": ""} for t, v in pts]}

def vseg(mat, src0, tgt0, tgt_dur, speed=1.0, scale=1.0, scale2=None, x=0.0, y=0.0, vol=0.0, blur=None, base=None):
    base = base or SEG_V
    s = copy.deepcopy(base); s["id"] = uid(); s["material_id"] = mat["id"]
    s["source_timerange"] = {"start": us(src0), "duration": us(tgt_dur * speed)}
    s["target_timerange"] = {"start": us(tgt0), "duration": us(tgt_dur)}
    s["speed"] = speed; s["volume"] = vol; s["last_nonzero_volume"] = 1.0
    s["clip"] = {"scale": {"x": scale, "y": scale}, "rotation": 0.0, "transform": {"x": x, "y": y},
                 "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0}
    s["uniform_scale"] = {"on": True, "value": scale}
    s["common_keyframes"] = []
    if scale2 is not None and abs(scale2 - scale) > 1e-3:   # плавный наезд z → z2 (время ключей — в шкале исходника)
        a, b = us(src0), us(src0 + tgt_dur * speed)
        s["common_keyframes"] = [kf("KFTypeScaleX", [(a, scale), (b, scale2)]), kf("KFTypePositionX", [(a, x), (b, x)]),
                                 kf("KFTypePositionY", [(a, y), (b, y)])]
    refs = clone_refs(base)
    for k, o in refs:
        if k == "speeds": o["speed"] = speed
        if k == "canvases" and blur: o.update(type="canvas_blur", blur=blur)
    s["extra_material_refs"] = [o["id"] for _, o in refs]
    return s

def aseg(mat, src0, tgt0, dur, vol=1.0):
    s = copy.deepcopy(SEG_A); s["id"] = uid(); s["material_id"] = mat["id"]
    s["source_timerange"] = {"start": us(src0), "duration": us(dur)}
    s["target_timerange"] = {"start": us(tgt0), "duration": us(dur)}
    s["speed"] = 1.0; s["volume"] = vol; s["last_nonzero_volume"] = vol
    s["extra_material_refs"] = [o["id"] for _, o in clone_refs(SEG_A)]
    return s

FONT = json.loads(by_id[SEG_T["material_id"]][1]["content"])["styles"][0]["font"]
def hexrgb(h): h = h.lstrip("#"); return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
def tseg(t0, t1, words, active=None, size=12.0, x=0.0, y=0.0, color="#FFFFFF", act_color="#FFE500",
         bg=None, rot=0.0, stroke=True):
    """Текстовый клип. words — список слов (или строк); active — индекс подсвеченного слова."""
    text = words if isinstance(words, str) else " ".join(words)
    styles, pos = [], 0
    parts = [text] if isinstance(words, str) else words
    for i, w in enumerate(parts):
        st = {"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0,
              "color": hexrgb(act_color if i == active else color)}}}, "font": FONT, "range": [pos, pos + len(w)],
              "size": size, "bold": True, "useLetterColor": True}
        if stroke: st["strokes"] = [{"content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [0, 0, 0]}}, "width": 0.12}]
        styles.append(st); pos += len(w)
        if not isinstance(words, str) and i < len(parts) - 1:
            styles.append(dict(st, range=[pos, pos + 1])); pos += 1
    m = copy.deepcopy(by_id[SEG_T["material_id"]][1]); m["id"] = uid()
    m["content"] = json.dumps({"styles": styles, "text": text}, ensure_ascii=False)
    m.update(font_size=size, text_color=color, border_color="#000000", border_width=0.12 if stroke else 0.0)
    if bg:
        m.update(background_style=1, background_color=bg, background_alpha=1.0, background_round_radius=0.25,
                 background_width=0.16, background_height=0.16)
    else:
        m.update(background_alpha=0.0, background_style=0)
    NEW["texts"].append(m)
    s = copy.deepcopy(SEG_T); s["id"] = uid(); s["material_id"] = m["id"]
    s["target_timerange"] = {"start": us(t0), "duration": us(max(0.05, t1 - t0))}
    s["clip"] = {"scale": {"x": 1.0, "y": 1.0}, "rotation": rot, "transform": {"x": x, "y": y},
                 "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0}
    s["extra_material_refs"] = [o["id"] for _, o in clone_refs(SEG_T)]
    return s

def nx(px): return (px - CW / 2) / (CW / 2)
def ny(py): return (CH / 2 - py) / (CH / 2)        # в CapCut +y — вверх

# ---------- 1. видео: лицо (+ сдвиг вправо, пока на экране панель) ----------
modes = [(m["s"], m["e"]) for m in (LAY or {}).get("modes", [])]
def mode_cuts(t0, t1):
    pts = sorted({t0, t1, *[x for s, e in modes for x in (s, e) if t0 < x < t1]})
    return [(a, b, any(s <= (a + b) / 2 < e for s, e in modes)) for a, b in zip(pts, pts[1:]) if b - a > 1e-3]
SRC = Path(E["src"]); face = video_mat(SRC)
FACE_X = nx(CW - 608 / 2) if LAND else 0.0      # столбик лица справа, пока слева панель
v_main, v_gfx, a_voice, texts = [], [], [], []
def lufs(f):
    o = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    return float([l for l in o.splitlines() if l.strip().startswith("I:")][-1].split()[1])
mixf = WD / "capcut_mix.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(WD / "voice.wav"), "-i", str(WD / "sfx.wav"), "-filter_complex",
                "amix=inputs=2:normalize=0", str(mixf)], check=True)
GAIN_DB = -14.0 - lufs(mixf); G = 10 ** (GAIN_DB / 20)
vcap = WD / "voice_capcut.wav"       # голос +GAIN_DB с лимитером (пики ≤ −1.5 дБ), как делает master.sh
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(WD / "voice.wav"), "-af",
                f"volume={GAIN_DB:.2f}dB,alimiter=limit=0.84:level=disabled", "-ar", "48000", str(vcap)], check=True)
print(f"громкость: поднимаю голос и звуки на {GAIN_DB:+.1f} дБ → ≈ −14 LUFS в экспорте CapCut")
voice = audio_mat(vcap)
for s in E["segs"]:
    t0, dur, sp = s["f0"] / FPS, s["n"] / FPS, s.get("sp_eff", SP)
    z, z2 = s.get("z", 1.0), s.get("z2")
    for a, b, panel in mode_cuts(t0, t0 + dur):
        q0, q1 = (a - t0) / dur, (b - t0) / dur
        za = z + ((z2 or z) - z) * q0; zb = z + ((z2 or z) - z) * q1
        v_main.append(vseg(face, s["a"] + (a - t0) * sp, a, b - a, speed=sp, scale=za, scale2=zb if z2 else None,
                           x=FACE_X if (LAND and panel) else 0.0, blur=0.375 if LAND else None))
    a_voice.append(aseg(voice, t0, t0, dur))
end_t = E["frames"] / FPS
if A.insert:
    ins = video_mat(Path(A.insert).expanduser()); idur = probe(A.insert)[0]
    v_main.append(vseg(ins, 0.0, end_t, idur, vol=10 ** (A.insert_gain_db / 20), blur=0.375 if LAND else None))

# ---------- 2. панели (gfx.mp4) — своя дорожка поверх ----------
if LAY:
    g = video_mat(WD / "gfx.mp4"); gx = nx(LAY.get("gfx_w", CW) / 2) if LAND else 0.0
    for s, e in modes:
        y = ny(LAY.get("gfx_h", CH) / 2) if not LAND else 0.0
        v_gfx.append(vseg(g, s, s, e - s, x=gx, y=y, base=SEG_V2))

# ---------- 3. звуки — по клипу, раскладка по дорожкам без наложений ----------
lanes = []
for snd in SFXL["sounds"]:
    m = audio_mat(snd["file"]); seg = aseg(m, snd["src"], snd["t"], snd["dur"], vol=round(min(snd["gain"] * SFXL["global_gain"] * G, 0.84 / snd.get("peak", 1.0)), 4))   # пик звука ≤ −1.5 дБ
    for lane in lanes:
        if lane[-1][0] <= snd["t"]: lane.append((snd["t"] + snd["dur"], seg)); break
    else: lanes.append([(snd["t"] + snd["dur"], seg)])

# ---------- 4. субтитры (клип на каждое слово — подсветка активного) и плашки ----------
cap = OV["caption"]; cap_y = ny(cap.get("y", 1380)); cap_size = 6.5 if LAND else 9.0      # 9.0 в горизонтали — фразы по 5 слов вылезали за края (2026-10-12)
for c in OV["chunks"]:
    ws = [w["t"] for w in c["ws"]]
    for k, w in enumerate(c["ws"]):
        a = c["s"] if k == 0 else w["s"]; b = c["ws"][k + 1]["s"] if k + 1 < len(c["ws"]) else c["e"]
        texts.append(tseg(a, b, ws, active=k, size=cap_size, y=cap_y, color=cap.get("color", "#FFFFFF"),
                          act_color=cap.get("active", "#FFE500")))
def photo_mat(path):
    path = reachable(path); w, h = probe_img(path)
    o = copy.deepcopy(by_id[SEG_V["material_id"]][1]); o.update(id=uid(), path=str(path), material_name=Path(path).name,
        type="photo", duration=10800000000, width=w, height=h, has_audio=False, unique_id=uuid.uuid4().hex)
    NEW["videos"].append(o); return o
def probe_img(p):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True).stdout.strip().split(",")
    return int(o[0]), int(o[1])
def fit_scale(w, h):   # CapCut вписывает клип в холст при scale=1; нужен масштаб «пиксель в пиксель»
    return 1 / min(CW / w, CH / h)
stick = []
for st in OV["stickers"]:
    if not st.get("png"): continue
    m = photo_mat(st["png"]); w, h = m["width"], m["height"]
    stick.append(vseg(m, 0.0, st["t"], st["dur"], scale=fit_scale(w, h), x=nx(st.get("x", CW / 2)), y=ny(st.get("y", 340)), base=SEG_V2))

def no_overlap(segs):
    """на дорожке CapCut клипы не могут перекрываться (и начинаться раньше 0): подрезаем начало по концу предыдущего"""
    segs.sort(key=lambda s: s["target_timerange"]["start"]); end = 0
    for s in segs:
        tr = s["target_timerange"]; st = max(tr["start"], end, 0)
        d = st - tr["start"]
        if d and s.get("source_timerange"):        # звук/видео: сдвигаем и начало в исходнике (стык после округления до мкс)
            s["source_timerange"]["start"] += int(round(d * s.get("speed", 1.0)))
            s["source_timerange"]["duration"] -= int(round(d * s.get("speed", 1.0)))
        tr["duration"] -= d; tr["start"] = st
        end = tr["start"] + tr["duration"]
    return [s for s in segs if s["target_timerange"]["duration"] > 10000]
texts = no_overlap(texts)
st_lanes = []                       # плашки могут перекрываться (хук + стикер) — раскладываем по дорожкам
for sg in sorted(stick, key=lambda x: x["target_timerange"]["start"]):
    for ln in st_lanes:
        e = ln[-1]["target_timerange"]; 
        if e["start"] + e["duration"] <= sg["target_timerange"]["start"]: ln.append(sg); break
    else: st_lanes.append([sg])
v_main, a_voice = no_overlap(v_main), no_overlap(a_voice)

# ---------- сборка draft_info.json ----------
def track(kind, segs, flag=0, ri=0):
    t = copy.deepcopy(TRK[kind]); t.update(id=uid(), segments=segs, flag=flag)
    for s in segs: s["track_render_index"] = ri
    return t
tracks = [track("video", v_main)]
if v_gfx: tracks.append(track("video", v_gfx, flag=2, ri=1))
tracks += [track("audio", a_voice)] + [track("audio", [x[1] for x in lane]) for lane in lanes]
tracks += [track("text", texts, ri=2)] + [track("video", ln, flag=2, ri=3 + i) for i, ln in enumerate(st_lanes)]
total = max(end_t + (probe(A.insert)[0] if A.insert else 0), end_t)
D = copy.deepcopy(J); D["materials"] = {k: (NEW.get(k, []) if isinstance(v, list) else v) for k, v in M.items()}
D["tracks"] = tracks; D["duration"] = us(total); D["id"] = uid(); D["name"] = A.name
D["canvas_config"] = {"background": None, "height": CH, "ratio": "original", "width": CW}

# ---------- папка черновика: копия шаблона без его кэшей, новые id, регистрация в root_meta_info ----------
dst = ROOT / A.name
if dst.exists(): shutil.rmtree(dst)
shutil.copytree(TPL, dst, ignore=shutil.ignore_patterns("*.bak", ".locked", "draft_cover.jpg"))
proj = json.load(open(dst / "Timelines/project.json")); old_tl = proj["main_timeline_id"]; tl = uid(); now = int(time.time() * US)
(dst / "Timelines" / old_tl).rename(dst / "Timelines" / tl)
# id таймлайна шаблона сидит не только в project.json: timeline_layout.json, attachment-файлы и т.д. Если где-то
# останется старый id, CapCut показывает проект в списке, но молча не открывает его (2026-10-12).
for f in dst.rglob("*"):
    if f.is_file() and f.suffix in (".json", ".tmp", ".extra") and f.stat().st_size < 5_000_000:
        b = f.read_bytes()
        if old_tl.encode() in b: f.write_bytes(b.replace(old_tl.encode(), tl.encode()))
D["id"] = tl                                     # id черновика = id главного таймлайна (так у CapCut)
proj.update(id=uid(), main_timeline_id=tl, create_time=now, update_time=now)
proj["timelines"] = [dict(proj["timelines"][0], id=tl, create_time=now, update_time=now)]
json.dump(proj, open(dst / "Timelines/project.json", "w"), ensure_ascii=False)
for p in (dst / "draft_info.json", dst / "Timelines" / tl / "draft_info.json", dst / "template-2.tmp", dst / "Timelines" / tl / "template-2.tmp"):
    json.dump(D, open(p, "w"), ensure_ascii=False)   # template-2.tmp у CapCut — рабочая копия draft_info.json
draft_id = uid()
meta = json.load(open(dst / "draft_meta_info.json"))
meta.update(draft_id=draft_id, draft_name=A.name, draft_fold_path=str(dst), draft_root_path=str(ROOT),
            tm_draft_create=now, tm_draft_modified=now, tm_duration=us(total), draft_cover="draft_cover.jpg")
for g_ in meta.get("draft_materials", []): g_["value"] = []
json.dump(meta, open(dst / "draft_meta_info.json", "w"), ensure_ascii=False)
vs = dst / "draft_virtual_store.json"
if vs.exists():
    v = json.load(open(vs))
    for g_ in v.get("draft_virtual_store", []):
        if g_.get("type") == 1: g_["value"] = []
    json.dump(v, open(vs, "w"), ensure_ascii=False)
cover = dst / "draft_cover.jpg"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1", "-i", str(SRC), "-frames:v", "1", "-vf", "scale=480:-2", str(cover)])
rm = json.load(open(ROOT / "root_meta_info.json"))
rm["all_draft_store"] = [e for e in rm["all_draft_store"] if e.get("draft_fold_path") != str(dst)]
tplent = next(e for e in rm["all_draft_store"] if e.get("draft_fold_path") == str(TPL))
ent = copy.deepcopy(tplent)
ent.update(draft_id=draft_id, draft_name=A.name, draft_fold_path=str(dst), draft_json_file=str(dst / "draft_info.json"),
           draft_cover=str(cover), tm_draft_create=now, tm_draft_modified=now, tm_duration=us(total), draft_timeline_materials_size=sum(os.path.getsize(m["path"]) for m in NEW["videos"] + NEW["audios"] if os.path.exists(m["path"])))
rm["all_draft_store"].insert(0, ent); rm["draft_ids"] = len(rm["all_draft_store"])
shutil.copy(ROOT / "root_meta_info.json", ROOT / "root_meta_info.json.before_capcut_draft")
json.dump(rm, open(ROOT / "root_meta_info.json", "w"), ensure_ascii=False)
print(f"черновик «{A.name}»: {len(v_main)} клипов видео, {len(v_gfx)} панелей, {len(a_voice)} кусков голоса, "
      f"{sum(len(l) for l in lanes)} звуков на {len(lanes)} дорожках, {len(texts)} клипов субтитров, {len(stick)} плашек, {total:.1f} с → {dst}")
