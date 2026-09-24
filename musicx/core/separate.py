"""Audio extraction (ffmpeg) and source separation, cached per input file and model preset.

A preset is one model or an ensemble. Each model yields an instrumental ('music') and vocals; an
ensemble averages them. Demucs models also yield drums / bass / other ('parts'); for other presets
the parts are made on demand by splitting the clean instrumental with PARTS_MODEL.
"""
import hashlib, json, os, queue, random, subprocess, sys, threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np, soundfile as sf
from scipy.signal import welch

from .common import SR, CACHE_ROOT, Cancelled, find_tool, run_tool, NO_WINDOW
from . import models as M

PARTS = ("drums", "bass", "other")
STEMS = ("vocals",) + PARTS
_separators = {}


def file_key(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""): h.update(block)
    return h.hexdigest()[:16]


def probe(path):
    """duration (s) and audio bitrate (bit/s or None) of the first audio stream."""
    out = run_tool([find_tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                    "stream=bit_rate,duration:format=duration", "-of", "json", str(path)])
    j = json.loads(out)
    if not j.get("streams"): raise ValueError(f"У файлі немає аудіо: {Path(path).name}")
    st = j["streams"][0]
    dur = float(st.get("duration") or j.get("format", {}).get("duration") or 0)
    br = st.get("bit_rate")
    return dur, (int(br) if br and br.isdigit() else None)


def extract(path, out_wav):
    run_tool([find_tool("ffmpeg"), "-y", "-v", "error", "-i", str(path), "-vn", "-ac", "2",
              "-ar", str(SR), "-c:a", "pcm_f32le", str(out_wav)])


def measure_cutoff(x):
    """frequency where the spectrum falls 40 dB below its 1-4 kHz level (codec low-pass edge)."""
    f, p = welch(x.mean(1), SR, nperseg=8192)
    db = 10 * np.log10(p + 1e-20)
    ref = np.median(db[(f > 1000) & (f < 4000)])
    return float(f[np.where(db > ref - 40)[0].max()])


def _rescale(w):
    peak = float(np.abs(w).max())
    return (w / max(1.01 * peak, 1.0)).astype(np.float32)       # demucs CLI "rescale" clip mode


def _write(p, x):
    sf.write(p, x.astype(np.float32), SR, subtype="FLOAT")


@dataclass
class StemSet:
    name: str           # display / map name
    path: str           # original input file
    dir: Path           # cache folder: raw.wav, music.wav, vocals.wav [, drums/bass/other.wav], meta.json
    duration: float
    bitrate: int | None
    cutoff: float
    preset: str = M.DEFAULT
    shifts: int = 2
    device: str = "auto"

    @property
    def raw(self): return self.dir / "raw.wav"

    def stem(self, s): return self.dir / f"{s}.wav"

    def read(self, s):
        return sf.read(self.stem(s), dtype="float32")[0]

    def has_parts(self):
        return all(self.stem(s).exists() for s in PARTS)

    def ensure_parts(self, job, frac=(0.0, 1.0)):
        """drums / bass / other: split the clean instrumental with PARTS_MODEL."""
        if self.has_parts(): return
        job.log(f"{Path(self.path).name}: розкладання мінусу на барабани / бас / інше")
        st = _run_demucs(M.MODELS[M.PARTS_MODEL].ref, self.read("music"), job, self.shifts, self.device,
                         Path(self.path).name, frac)
        for s in PARTS: _write(self.stem(s), _rescale(st[s]))


# ---------------------------------------------------------------- engines
def _demucs_separator(name, shifts, device):
    import torch
    from demucs.api import Separator
    if device == "auto": device = "cuda" if torch.cuda.is_available() else "cpu"
    key = (name, shifts, device)
    if key not in _separators:
        _separators.clear()                      # keep at most one model in (GPU) memory
        _separators[key] = Separator(model=name, repo=M.DEMUCS_DIR, shifts=shifts, device=device, progress=False)
    return _separators[key]


def _run_demucs(name, x, job, shifts, device, label, frac):
    import torch
    lo, hi = frac
    M.ensure_demucs(name, job.log, job._cancel)
    sep = _demucs_separator(name, shifts, device)
    state = {"done": 0.0}

    def cb(info):
        if job._cancel is not None and job._cancel.is_set(): raise KeyboardInterrupt
        n_models, L = info["models"], max(1, info["audio_length"])
        f = (info["model_idx_in_bag"] + (info["shift_idx"] + info["segment_offset"] / L) / shifts) / n_models
        if info["state"] == "end" and f > state["done"]:
            state["done"] = f
            job.progress("Розділення", lo + (hi - lo) * f, f"{label}: {name} {f*100:.0f}%")
    sep.update_parameter(callback=cb)
    random.seed(0); torch.manual_seed(0)        # Demucs shifts are random: fixed for reproducibility
    job.log(f"{label}: {name} (shifts {shifts}, {sep._device})")
    try:
        _, stems = sep.separate_tensor(torch.from_numpy(x.T.copy()), SR)
    except KeyboardInterrupt:
        raise Cancelled()
    return {k: v.cpu().numpy().T for k, v in stems.items()}


def _run_uvr(model_file, raw_wav, out_dir, job, device, label, frac):
    lo, hi = frac
    M.ensure_uvr(model_file, job.log, job._cancel)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if device == "cpu": env["CUDA_VISIBLE_DEVICES"] = ""
    job.log(f"{label}: {model_file}")
    p = subprocess.Popen([sys.executable, "-m", "musicx.core.uvr_run", model_file, str(raw_wav), str(out_dir),
                          str(M.MODELS_DIR)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env, cwd=str(Path(__file__).resolve().parents[2]),
                         creationflags=NO_WINDOW)
    result, tail = None, []
    lines = queue.Queue()                        # reader thread: Cancel is checked every 0.2 s, not per line
    threading.Thread(target=lambda: [lines.put(l) for l in p.stdout] + [lines.put(None)], daemon=True).start()
    try:
        while True:
            if job._cancel is not None and job._cancel.is_set(): raise Cancelled()
            try: line = lines.get(timeout=0.2)
            except queue.Empty: continue
            if line is None: break
            line = line.strip()
            if line.startswith("PROGRESS "):
                f = float(line.split()[1])
                job.progress("Розділення", lo + (hi - lo) * f, f"{label}: {model_file.rsplit('.', 1)[0]} {f*100:.0f}%")
            elif line.startswith("DONE "):
                result = line[5:].split("|")
            elif line:
                tail = (tail + [line])[-15:]
        p.wait()
    finally:
        if p.poll() is None: p.kill(); p.wait()
    if p.returncode != 0 or not result:
        raise RuntimeError(f"модель {model_file} завершилась з помилкою:\n" + "\n".join(tail))
    voc = sf.read(result[0], dtype="float32")[0]; inst = sf.read(result[1], dtype="float32")[0]
    for f in result: Path(f).unlink(missing_ok=True)
    return voc, inst


def _fit(x, n):
    return x[:n] if len(x) >= n else np.vstack([x, np.zeros((n - len(x), 2), np.float32)])


def separate(path, job, name=None, preset=M.DEFAULT, shifts=2, device="auto", cache_root=CACHE_ROOT,
             frac=(0.0, 1.0), need_parts=False):
    """extract + separate one file with a model preset; returns the cached StemSet."""
    path = Path(path)
    pre = M.preset(preset)
    lo, hi = frac
    job.progress("Розділення", lo, f"{path.name}: аналіз файлу")
    d = Path(cache_root) / f"{file_key(path)}_{pre.key}_s{shifts}"
    meta_p = d / "meta.json"
    name = name or path.stem

    def stemset(m):
        return StemSet(name, str(path), d, m["duration"], m["bitrate"], m["cutoff"], pre.key, shifts, device)

    if meta_p.exists() and (d / "music.wav").exists() and (d / "vocals.wav").exists():
        st = stemset(json.loads(meta_p.read_text(encoding="utf-8")))
        job.log(f"{path.name}: результат розділення взято з кешу")
        if need_parts: st.ensure_parts(job, frac)
        return st
    d.mkdir(parents=True, exist_ok=True)
    dur, br = probe(path)
    job.progress("Розділення", lo, f"{path.name}: витягування аудіо")
    extract(path, d / "raw.wav")
    x = sf.read(d / "raw.wav", dtype="float32")[0]
    meta = {"source": str(path), "duration": dur, "bitrate": br, "cutoff": measure_cutoff(x), "preset": pre.key}
    job.check()

    n_models = len(pre.models) + (1 if need_parts and not any(M.MODELS[k].engine == "demucs" for k in pre.models) else 0)
    span = (hi - lo) / n_models
    musics, vocals, parts = [], [], None
    for i, key in enumerate(pre.models):
        m = M.MODELS[key]; sub = (lo + i * span, lo + (i + 1) * span)
        if m.engine == "demucs":
            st = _run_demucs(m.ref, x, job, shifts, device, path.name, sub)
            st = {k: _rescale(v) for k, v in st.items()}
            if "guitar" in st: st["other"] = st["other"] + st.pop("guitar") + st.pop("piano")   # htdemucs_6s
            voc = st["vocals"]; inst = st["drums"] + st["bass"] + st["other"]
            if parts is None and len(pre.models) == 1: parts = {s: st[s] for s in PARTS}
        else:
            voc, inst = _run_uvr(m.ref, d / "raw.wav", d / f"_{key}", job, device, path.name, sub)
        musics.append(_fit(inst, len(x))); vocals.append(_fit(voc, len(x)))
        job.check()
    if len(musics) == 1:
        music, voc = musics[0], vocals[0]
    else:                                        # ensemble: average of the models' estimates
        music, voc = np.mean(musics, 0), np.mean(vocals, 0)
        job.log(f"{path.name}: ансамбль {len(musics)} моделей")
    _write(d / "music.wav", music); _write(d / "vocals.wav", voc)
    if parts:
        for s in PARTS: _write(d / f"{s}.wav", parts[s])
    meta_p.write_text(json.dumps(meta), encoding="utf-8")   # written last: marks the cache entry complete
    st = stemset(meta)
    if need_parts: st.ensure_parts(job, (hi - span, hi))
    job.progress("Розділення", hi, f"{path.name}: готово")
    return st
