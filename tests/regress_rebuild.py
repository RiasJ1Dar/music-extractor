"""Regression: mode B through the core (no GUI) must reproduce output/clean_track.wav.

  python tests/regress_rebuild.py cached   same Demucs stems (work/sep) and map (work/map.json) as the reference
  python tests/regress_rebuild.py fresh    everything from scratch: new extraction, separation and map
Pass: duration within 1 sample, waveform correlation >= 0.999.

Note on 'fresh': the reference was separated by the Demucs CLI without a fixed seed, and Demucs
'shifts' are random, so a fresh separation differs from it by about as much as two seeds differ
from each other (measured: 0.988 correlation of the final track). The map/score/render port itself is
exact: reference stems + a map rebuilt from scratch give 463/463 identical steps and correlation
1.000000. The app now seeds Demucs (seed 0), so its own runs are bit-for-bit reproducible.
"""
import os, shutil, sys, tempfile, time
from pathlib import Path

import numpy as np, soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from musicx.core.common import Job, SR                         # noqa: E402
from musicx.core.separate import StemSet, probe, measure_cutoff  # noqa: E402
from musicx.core.rebuild import Source, Params, rebuild, codec_adjust  # noqa: E402
from musicx.core.jobs import run_rebuild                       # noqa: E402

DL = Path(os.environ.get("MUSICX_TEST_MEDIA", Path.home() / "Downloads"))   # folder with the test videos
FILES = {"explainer": "vivaldi_explainer-264.mp4", "drones": "vivaldi_drones-264.mp4",
         "s2": "vivaldi-season-2-explainer-264.mp4", "army": "ab3_army_2026-09-24-18-59-54_1790265594133-2.mp4"}
REF = ROOT / "output" / "clean_track.wav"
OUT = ROOT / "work" / "regress"


def compare(path):
    a = sf.read(REF, dtype="float32")[0].mean(1); b = sf.read(path, dtype="float32")[0].mean(1)
    n = min(len(a), len(b))
    corr = float(a[:n] @ b[:n]) / (np.linalg.norm(a[:n]) * np.linalg.norm(b[:n]))
    ok = abs(len(a) - len(b)) <= 1 and corr >= 0.999
    print(f"reference {len(a)} samples ({len(a)/SR:.3f} s), result {len(b)} samples ({len(b)/SR:.3f} s), "
          f"diff {len(b)-len(a):+d}; correlation {corr:.6f} -> {'PASS' if ok else 'FAIL'}")
    return ok


def cached():
    job = Job(log=lambda s: print("  ", s))
    stemsets, sources = [], []
    for n, f in FILES.items():
        d = ROOT / "work" / "sep" / "htdemucs_ft" / n
        raw = sf.read(ROOT / "work" / "raw" / f"{n}.wav", dtype="float32")[0]
        dur, br = probe(DL / f)
        stemsets.append(StemSet(n, str(DL / f), d, dur, br, measure_cutoff(raw)))
        rd = lambda s: sf.read(d / f"{s}.wav", dtype="float32")[0]
        other = rd("other")
        sources.append(Source(n, rd("drums") + rd("bass") + other, rd("vocals"), other))
    P = Params()
    codec_adjust(sources, stemsets, P)
    print("codec:", {s.name: (s.penalty, s.band_limit and round(s.band_limit)) for s in sources})
    tmp = Path(tempfile.mkdtemp()); shutil.copy(ROOT / "work" / "map.json", tmp / "map.json")
    out, res = rebuild(sources, job, P, map_cache=tmp / "map.json")
    OUT.mkdir(parents=True, exist_ok=True)
    sf.write(OUT / "cached.wav", out, SR, subtype="PCM_24")
    print(f"fused steps {len(res['fused_steps'])}, coverage {res['coverage']*100:.0f}%")
    return compare(OUT / "cached.wav")


def fresh():
    cache = OUT / "fresh_cache"
    if cache.exists(): shutil.rmtree(cache)
    t0 = time.time()
    job = Job(log=lambda s: print("  ", s))
    r = run_rebuild([DL / f for f in FILES.values()], OUT / "fresh", job, names=list(FILES), cache_root=cache)
    print(f"built in {time.time() - t0:.0f} s; fused steps {len(r['result']['fused_steps'])}")
    return compare(r["audio"])


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "cached"
    sys.exit(0 if (cached() if mode == "cached" else fresh()) else 1)
