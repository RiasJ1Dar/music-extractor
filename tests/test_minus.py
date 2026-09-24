"""Mode A on vivaldi_drones-264.mp4: instrumental has the input's duration and, re-separated by
Demucs, carries at least 30 dB less voice than the original file.

  python tests/test_minus.py [preset]     (preset from musicx.core.models.PRESETS; judge is always htdemucs_ft)"""
import os, shutil, sys, time
from pathlib import Path

import numpy as np, soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from musicx.core.common import Job, SR, rms          # noqa: E402
from musicx.core.jobs import run_minus                # noqa: E402
from musicx.core.separate import separate, probe      # noqa: E402

JUDGE = "htdemucs_ft"
SRC = Path(os.environ.get("MUSICX_TEST_MEDIA", Path.home() / "Downloads")) / "vivaldi_drones-264.mp4"
OUT = ROOT / "work" / "test_minus"


def main(preset):
    if OUT.exists(): shutil.rmtree(OUT)
    job = Job(log=lambda s: print("  ", s))
    t0 = time.time()
    r = run_minus([SRC], OUT / "out", job, fmt="wav", save_stems=True, cache_root=OUT / "cache", preset=preset)
    print(f"[{preset}] mode A done in {time.time() - t0:.0f} s:", [Path(f).name for f in r["files"]])
    inst_p = Path(r["files"][0])
    inst = sf.read(inst_p, dtype="float32")[0]
    dur_in, _ = probe(SRC)
    d_ok = abs(len(inst) / SR - dur_in) < 0.05
    print(f"duration: input {dur_in:.3f} s, instrumental {len(inst) / SR:.3f} s -> {'PASS' if d_ok else 'FAIL'}")

    orig_voc = separate(SRC, job, preset=JUDGE, cache_root=OUT / "cache").read("vocals")
    re_voc = separate(inst_p, job, preset=JUDGE, cache_root=OUT / "cache_re").read("vocals")  # instrumental re-separated
    a, b = rms(orig_voc), rms(re_voc)
    drop = 20 * np.log10(a / (b + 1e-12))
    v_ok = drop >= 30
    print(f"voice: original {20*np.log10(a):.1f} dBFS, in instrumental {20*np.log10(b + 1e-12):.1f} dBFS, "
          f"drop {drop:.1f} dB -> {'PASS' if v_ok else 'FAIL'}")
    return d_ok and v_ok


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else "htdemucs_ft") else 1)
