"""The two user-facing jobs: A) instrumental / stems per file, B) one track rebuilt from several."""
import hashlib, json
from pathlib import Path

import numpy as np, soundfile as sf

from .common import SR, CACHE_ROOT
from .separate import separate, STEMS
from . import models as M
from .rebuild import Source, Params, rebuild, codec_adjust
from .report import write_report

FORMATS = {"wav": ("WAV", "PCM_24", ".wav"), "flac": ("FLAC", "PCM_24", ".flac")}


def _free(path):
    """path, or 'name (2).ext' if it already exists (never overwrite earlier results)."""
    path = Path(path)
    if not path.exists(): return path
    k = 2
    while True:
        p = path.with_name(f"{path.stem} ({k}){path.suffix}")
        if not p.exists(): return p
        k += 1


def write_audio(path, x, fmt):
    kind, sub, _ = FORMATS[fmt]
    sf.write(path, x, SR, format=kind, subtype=sub)


def _limit(x, job, what):
    peak = float(np.abs(x).max())
    if peak > 0.999:
        job.log(f"{what}: пік {20*np.log10(peak):+.1f} dBFS, гучність знижено до −0.2 dBFS")
        return x * (0.98 / peak)
    return x


def run_minus(files, out_dir, job, fmt="wav", save_stems=False, shifts=2, device="auto", cache_root=CACHE_ROOT,
              preset=M.DEFAULT):
    """mode A: every file on its own -> <name>_instrumental (+ <name>_stems/)."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    ext = FORMATS[fmt][2]; made = []
    for k, f in enumerate(files):
        f = Path(f)
        st = separate(f, job, preset=preset, shifts=shifts, device=device, cache_root=cache_root,
                      frac=(k / len(files), (k + 0.95) / len(files)), need_parts=save_stems)
        job.progress("Збереження", (k + 0.95) / len(files), f.name)
        inst = st.read("music")
        dst = _free(out_dir / f"{f.stem}_instrumental{ext}")
        write_audio(dst, _limit(inst, job, dst.name), fmt); made.append(dst)
        job.log(f"✅ {dst.name}: {len(inst) / SR:.2f} с")
        if save_stems:
            sd = _free(out_dir / f"{f.stem}_stems"); sd.mkdir()
            for s in STEMS:
                p = sd / f"{s}{ext}"; write_audio(p, _limit(st.read(s), job, f"{sd.name}/{p.name}"), fmt); made.append(p)
            job.log(f"✅ стеми: {sd.name}\\")
    job.progress("Готово", 1.0)
    return {"files": [str(p) for p in made]}


def run_rebuild(files, out_dir, job, fmt="wav", shifts=2, device="auto", cache_root=CACHE_ROOT,
                names=None, P=None, map_cache="auto", preset=M.DEFAULT_REBUILD):
    """mode B: one clean track from >= 2 recordings of the same music."""
    if len(files) < 2: raise ValueError("Для відновлення потрібно щонайменше 2 файли")
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    P = P or Params()
    names = names or _unique_names(files)
    stemsets = []
    for k, (f, n) in enumerate(zip(files, names)):
        stemsets.append(separate(f, job, name=n, preset=preset, shifts=shifts, device=device, cache_root=cache_root,
                                 frac=(k / len(files), (k + 1) / len(files)), need_parts=True))
    job.progress("Підготовка", 0.0, "завантаження стемів")
    sources = []
    for st in stemsets:
        sources.append(Source(st.name, st.read("music"), st.read("vocals"), st.read("other")))
    codec_adjust(sources, stemsets, P)
    for s in sources:
        if s.penalty: job.log(f"{s.name}: вужча смуга / низький бітрейт → штраф {s.penalty}, "
                              f"у злитті ігнорується вище {s.band_limit / 1000:.1f} кГц" if s.band_limit else
                              f"{s.name}: низький бітрейт → штраф {s.penalty}")
    if map_cache == "auto":
        key = hashlib.sha1(json.dumps([st.dir.name for st in stemsets] + names).encode()).hexdigest()[:16]
        map_cache = Path(cache_root) / "maps" / f"{key}.json"; map_cache.parent.mkdir(parents=True, exist_ok=True)
    out, res = rebuild(sources, job, P, map_cache=map_cache)
    job.progress("Збереження", 0.5)
    dst = _free(out_dir / f"clean_track{FORMATS[fmt][2]}")
    write_audio(dst, out, fmt)
    rep = dst.with_name(dst.stem + "_report.md")
    write_report(rep, res, len(out) / SR, dst.name)
    job.log(f"✅ {dst.name}: {len(out) / SR:.2f} с; звіт: {rep.name}")
    if res["coverage"] < 0.2:
        job.log(f"⚠️ джерела майже не збігаються: лише {res['coverage']*100:.0f}% кроків мають копію з іншого файлу")
    job.progress("Готово", 1.0)
    return {"files": [str(dst), str(rep)], "coverage": res["coverage"], "result": res, "audio": dst}


def _unique_names(files):
    names, seen = [], {}
    for f in files:
        n = Path(f).stem
        seen[n] = seen.get(n, 0) + 1
        names.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return names
