# /// script
# requires-python = ">=3.11"
# dependencies = ["pedalboard>=0.9.16", "numpy", "soundfile"]
# ///
"""fx_chain.py — цепочка плагинов микшера FL Studio без FL.

  extract <preset.fst> <chain_dir>   разобрать пресет канала микшера FL (.fst) → chain_dir/chain.json + состояния
  run <chain_dir> <in.wav> <out.wav> прогнать WAV через те же VST3 с теми же настройками (headless, pedalboard)
  info <chain_dir>                   показать цепочку и ключевые параметры плагинов (проверка, что состояние встало)

Формат .fst (FL 21–26): заголовок FLhd + FLdt, дальше события [id][данные]. На слот микшера:
  213 — данные «Fruity Wrapper»: записи [u32 id][u64 size][data]; 52 — VST3 class id, 54 — имя, 55 — путь,
        56 — производитель, 53 — состояние, внутри снова записи: 3 — IComponent::getState, 2 — IEditController::getState,
        4 — кэш параметров FL (не нужен);
  98  — номер слота; 225 — параметры микшера: записи по 12 байт <u32 ?, u8 id, u8 ?, u16 ch, i32 msg>,
        id 0 — слот включён, id 1 — микс слота (12800 = 100%), id 192 — громкость канала (12800 = 0 дБ).
Состояние отдаётся плагину в формате JUCE (как его ждёт pedalboard.raw_state): "VC2!" + len + XML
<VST3PluginState><IComponent>…</IComponent><IEditController>…</IEditController></VST3PluginState>,
где байты закодированы JUCE-base64 ("<размер>.<символы>", алфавит .A-Za-z0-9+, биты little-endian).
Микс слота повторяется как в FL: out = dry·(1−m) + wet·m. Выключенные слоты пропускаются."""
import json, os, struct, sys
from pathlib import Path

JUCE_B64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"

def juce_b64(data: bytes) -> str:
    n = int.from_bytes(data, "little"); chars = ((len(data) << 3) + 5) // 6
    return f"{len(data)}." + "".join(JUCE_B64[(n >> (6 * i)) & 63] for i in range(chars))

def juce_unb64(s: str) -> bytes:
    size, enc = s.split(".", 1); n = 0
    for i, c in enumerate(enc): n |= JUCE_B64.index(c) << (6 * i)
    return n.to_bytes(int(size) + 8, "little")[: int(size)]

def juce_state(component: bytes, controller: bytes = b"") -> bytes:
    xml = '<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>' + juce_b64(component) + "</IComponent>"
    if controller: xml += "<IEditController>" + juce_b64(controller) + "</IEditController>"
    xml = (xml + "</VST3PluginState>").encode()
    return b"VC2!" + struct.pack("<I", len(xml)) + xml + b"\x00"

def fl_events(d: bytes):
    assert d[:4] == b"FLhd", "не FL-файл"
    p = 8 + struct.unpack("<I", d[4:8])[0]; assert d[p:p + 4] == b"FLdt"; p += 8
    while p < len(d):
        eid = d[p]; p += 1
        if eid < 64: yield eid, d[p]; p += 1
        elif eid < 128: yield eid, struct.unpack("<H", d[p:p + 2])[0]; p += 2
        elif eid < 192: yield eid, struct.unpack("<I", d[p:p + 4])[0]; p += 4
        else:
            n = s = 0
            while True:
                b = d[p]; p += 1; n |= (b & 0x7F) << s; s += 7
                if not b & 0x80: break
            yield eid, d[p:p + n]; p += n

def records(b: bytes, start=4):
    q, r = start, {}
    while q + 12 <= len(b):
        rid, size = struct.unpack("<IQ", b[q:q + 12]); q += 12; r[rid] = b[q:q + size]; q += size
    return r

def cstr(b): return b.decode("utf-8", "replace").rstrip("\x00")

def extract(fst, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    evs = list(fl_events(Path(fst).read_bytes()))
    slots, pending = [], None
    mix, enabled, volume = {}, {}, 12800
    for eid, val in evs:
        if eid == 213: pending = val
        elif eid == 98 and pending is not None:
            r = records(pending); st = records(r.get(53, b""))
            slots.append(dict(slot=val, name=cstr(r.get(54, b"")), path=cstr(r.get(55, b"")), vendor=cstr(r.get(56, b"")),
                              component=st.get(3, b""), controller=st.get(2, b"")))
            pending = None
        elif eid == 225:
            for k in range(0, len(val) - 11, 12):
                _, pid, _, ch, msg = struct.unpack("<IBBHi", val[k:k + 12])
                if pid == 0: enabled[ch & 0x3F] = bool(msg)
                elif pid == 1: mix[ch & 0x3F] = msg / 12800
                elif pid == 192: volume = msg
    chain = []
    for s in slots:
        f = out / f"slot{s['slot'] + 1}.state"; f.write_bytes(juce_state(s["component"], s["controller"]))
        sub = None
        if "WaveShell" in s["name"]:   # имя подплагина Waves — из XML пресета внутри состояния
            i = s["component"].find(b"<PluginName>")
            if i >= 0: sub = s["component"][i + 12: s["component"].find(b"</PluginName>", i)].decode()
        chain.append(dict(slot=s["slot"] + 1, name=sub or s["name"], file=s["path"], vendor=s["vendor"], shell_plugin=sub,
                          enabled=enabled.get(s["slot"], True), mix=round(mix.get(s["slot"], 1.0), 4), state=f.name))
    meta = dict(source=str(fst), channel_volume_db=round(20 * __import__("math").log10(max(volume, 1) / 12800), 2), chain=chain)
    (out / "chain.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    for c in chain:
        print(f"  {c['slot']}. {c['name']:<28} {'вкл ' if c['enabled'] else 'ВЫКЛ'}  микс {c['mix']*100:5.1f}%")
    print(f"→ {out/'chain.json'}")

def load(chain_dir):
    import pedalboard
    meta = json.loads((Path(chain_dir) / "chain.json").read_text()); plugins = []
    skip_shell = os.environ.get("ADHD_SKIP_SHELL") == "1"
    for c in meta["chain"]:
        if not c["enabled"]: continue
        if c.get("shell_plugin") and skip_shell:
            print(f"  (пропуск {c['name']}: ADHD_SKIP_SHELL=1)"); continue
        # Waves: сразу по имени «<плагин> Stereo». get_plugin_names_for_file перебирает всю оболочку
        # (сотни плагинов, >8 минут), поэтому вызывается только если имя не подошло.
        name = c.get("shell_name") or (c["shell_plugin"] + " Stereo" if c.get("shell_plugin") else None)
        try:
            p = pedalboard.load_plugin(c["file"], plugin_name=name) if name else pedalboard.load_plugin(c["file"])
        except Exception:
            if not c.get("shell_plugin"): raise
            names = pedalboard.VST3Plugin.get_plugin_names_for_file(c["file"])
            name = next((n for n in names if n.startswith(c["shell_plugin"])), None)
            p = pedalboard.load_plugin(c["file"], plugin_name=name)
        p.raw_state = (Path(chain_dir) / c["state"]).read_bytes()
        plugins.append((c, p))
    return meta, plugins

def run(chain_dir, inp, outp):
    import numpy as np, soundfile as sf
    meta, plugins = load(chain_dir)
    x, sr = sf.read(inp, always_2d=True, dtype="float32")
    if x.shape[1] == 1: x = np.repeat(x, 2, axis=1)
    y = x.T.copy()
    for c, p in plugins:
        wet = p.process(y, sr, reset=True)
        n = min(wet.shape[1], y.shape[1]); m = c["mix"]
        y = (y[:, :n] * (1 - m) + wet[:, :n] * m) if m < 0.999 else wet[:, :n]
        print(f"  {c['slot']}. {c['name']:<28} микс {m*100:5.1f}%  пик {20*np.log10(np.abs(y).max()+1e-9):6.1f} dBFS")
    y *= 10 ** (meta.get("channel_volume_db", 0) / 20)
    y = np.pad(y, ((0, 0), (0, max(0, x.shape[0] - y.shape[1]))))[:, : x.shape[0]]
    sf.write(outp, y.T, sr, subtype="PCM_24"); print(f"→ {outp}")

def info(chain_dir):
    meta, plugins = load(chain_dir)
    for c, p in plugins:
        ps = list(p.parameters.items())[:6]
        print(f"{c['slot']}. {c['name']} (микс {c['mix']*100:.0f}%): " + ", ".join(f"{k}={v.string_value if hasattr(v,'string_value') else v}" for k, v in ps))

if __name__ == "__main__":
    cmd = sys.argv[1]
    {"extract": lambda: extract(sys.argv[2], sys.argv[3]), "run": lambda: run(sys.argv[2], sys.argv[3], sys.argv[4]),
     "info": lambda: info(sys.argv[2])}[cmd]()
