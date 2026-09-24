"""Rebuild one clean music track from several recordings that share it.

Ported unchanged from output/build_track.py (only the hard-coded sources, skeleton and codec
penalty became inputs). Pipeline:
  1. every source is separated by Demucs htdemucs_ft; music = drums + bass + other
  2. map: the longest source is the timeline skeleton; its stops / quiet breakdowns are part of
     the composition and are kept. For every 0.25 s step find every place in every source (incl.
     loop repeats inside the skeleton) where the same music plays:
       a. normalised cross-correlation on a 2 s window, refined to 1 sample
       b. propagation of a found alignment while a 1 s window still correlates (>= 0.6)
       c. through quiet steps an alignment is carried only if anchored on both sides (3 ms)
  3. score: voice energy near the copy + deviation from the consensus spectrum + codec penalty
     + melodic mismatch ('other' stem 400-5000 Hz must match the skeleton: drums and bass repeat
     on every loop pass, the phrase on top does not); other phrases are never chosen or fused
  4. render (STFT overlap-add): a clean copy is taken as is; with >= 3 copies of the same phrase
     the median magnitude per bin is taken; in stops the quietest of >= 2 copies
"""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np, soundfile as sf
from scipy.signal import fftconvolve, resample_poly, find_peaks, butter, sosfiltfilt

from .common import SR, rms, rms_db


@dataclass
class Params:
    ds: int = 8                 # coarse matching decimation -> 5512.5 Hz
    step: float = 0.25          # timeline grid, s
    ctx: float = 2.0            # matching window, s
    min_ncc: float = 0.88       # direct match acceptance
    prop_ncc: float = 0.60      # propagation acceptance (1 s window)
    hyst: float = 0.15          # score margin needed to leave the current run
    mid_w: float = 1.0          # weight of melodic-layer mismatch in the score
    mid_gate: float = 0.30      # below this best agreement the step has no usable melodic layer
    mid_ok: float = 0.75        # copies below this share of the best agreement carry another phrase
    quiet_db: float = -10.0     # music this far below the source's median level = quiet (stop)
    clean_leak: float = 0.10    # best candidate this clean -> copy it as is, no fusion
    fuse_min: int = 3           # aligned copies needed for per-bin fusion
    fuse_max: int = 8           # aligned copies used for per-bin fusion
    fuse_rank: float = 0.5      # magnitude rank taken per bin (0.5 = median)
    bridge_tol: float = 0.003   # alignment tolerance when anchoring a bridge, s
    codec_gap: float = 500.0    # a source whose codec cutoff is this far below the best is penalised
    codec_penalty: float = 0.03
    lowbit: int = 64000         # ... as is one below this bitrate
    codec_margin: float = 700.0 # fusion ignores a band-limited source this far below its cutoff


@dataclass
class Source:
    name: str
    music: np.ndarray           # (n, 2) drums + bass + other
    vocals: np.ndarray          # (n, 2)
    other: np.ndarray           # (n, 2)
    penalty: float = 0.0        # codec penalty in the score
    band_limit: float | None = None   # Hz; bins above are never taken from this source in fusion
    info: dict = field(default_factory=dict)


def codec_adjust(sources, stemsets, P):
    """codec penalty / fusion band limit from measured cutoff and bitrate."""
    best = max(s.cutoff for s in stemsets)
    for src, st in zip(sources, stemsets):
        narrow = best - st.cutoff > P.codec_gap
        low = st.bitrate is not None and st.bitrate < P.lowbit
        src.penalty = P.codec_penalty if (narrow or low) else 0.0
        src.band_limit = st.cutoff - P.codec_margin if narrow else None
        src.info.update({"file": st.path, "duration": st.duration, "bitrate": st.bitrate, "cutoff": st.cutoff})


def melodic_layer(other):
    """'other' stem (melody / chords), 400-5000 Hz, 11025 Hz: tells loop passes apart."""
    sos = butter(4, [400, 5000], btype="band", fs=SR, output="sos")
    return resample_poly(sosfiltfilt(sos, other.mean(1)), 1, 4).astype(np.float32)


def ncc_all(win, ref):
    c = fftconvolve(ref, win[::-1], mode="valid")
    e = np.sqrt(np.maximum(fftconvolve(ref ** 2, np.ones(len(win)), mode="valid"), 1e-12))
    return c / (e * np.linalg.norm(win) + 1e-12)


def ncc_pair(x, y):
    return float(x @ y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-12)


def refine(win, ref, pos, rad=12):
    best, bl, L = -2.0, pos, len(win)
    for p in range(max(0, pos - rad), min(len(ref) - L, pos + rad) + 1):
        r = ncc_pair(win, ref[p:p + L])
        if r > best: best, bl = r, p
    return bl, best


class Timeline:
    def __init__(self, M, skeleton, P):
        self.P = P; self.skeleton = skeleton
        self.mono = {n: M[n].mean(1) for n in M}
        self.coarse = {n: resample_poly(self.mono[n], 1, P.ds) for n in M}
        self.sk = self.mono[skeleton]
        self.n = int(len(self.sk) / SR / P.step)
        h = int(0.5 * SR)   # per-source threshold: sources are mixed at different levels
        self.median = {n: float(np.median([rms_db(x[k:k + h]) for k in range(0, len(x) - h, h)]))
                       for n, x in self.mono.items()}

    def t(self, i): return (i + 0.5) * self.P.step

    def win(self, name, centre, L):
        a = int(round((centre - L / 2) * SR)); b = a + int(L * SR)
        x = self.mono[name]
        return x[a:b] if a >= 0 and b <= len(x) else None

    def quiet(self, i):
        return rms_db(self.win(self.skeleton, self.t(i), self.P.step)) < self.median[self.skeleton] + self.P.quiet_db


def build_map(tl, job):
    P, SK = tl.P, tl.skeleton
    grid = [{"t": tl.t(i), "quiet": tl.quiet(i), "cands": []} for i in range(tl.n)]
    csr = SR / P.ds
    for i, g in enumerate(grid):                                   # a. direct matches
        if i % 8 == 0: job.progress("Пошук збігів", 0.8 * i / tl.n, f"{g['t']:.1f} с з {tl.n * P.step:.0f} с")
        t = g["t"]
        if g["quiet"]:
            g["cands"].append({"src": SK, "at": t, "ncc": 1.0, "kind": "self"}); continue
        a = max(0.0, min(t - P.ctx / 2, len(tl.sk) / SR - P.ctx))
        wc = tl.coarse[SK][int(a * csr):int((a + P.ctx) * csr)]
        wf = tl.sk[int(a * SR):int((a + P.ctx) * SR)]
        for n in tl.mono:
            r = ncc_all(wc, tl.coarse[n])
            pk, _ = find_peaks(r, height=P.min_ncc - 0.06, distance=int(0.5 * csr))
            for p in pk:
                fp, rr = refine(wf, tl.mono[n], int(round(p * P.ds)))
                if rr >= P.min_ncc:
                    g["cands"].append({"src": n, "at": fp / SR + (t - a), "ncc": rr,
                                       "kind": "self" if n == SK and abs(fp / SR - a) < 1e-3 else "match"})
        if not any(c["kind"] == "self" for c in g["cands"]):
            g["cands"].append({"src": SK, "at": t, "ncc": 1.0, "kind": "self"})

    def has(cands, src, at):
        return any(c["src"] == src and abs(c["at"] - at) < 0.004 for c in cands)

    def propagate(order, d):                                       # b + c
        added = 0
        for i in order:
            j = i - d
            if j < 0 or j >= tl.n: continue
            for c in list(grid[j]["cands"]):
                at = c["at"] + d * P.step
                if has(grid[i]["cands"], c["src"], at) or tl.win(c["src"], at, 1.0) is None: continue
                if grid[i]["quiet"]:
                    grid[i]["cands"].append({"src": c["src"], "at": at, "ncc": 0.0, "kind": "bridge"}); added += 1
                elif c["kind"] != "bridge":
                    x = tl.win(SK, grid[i]["t"], 1.0)
                    if x is None: continue
                    r = ncc_pair(x, tl.win(c["src"], at, 1.0))
                    if r >= P.prop_ncc:
                        grid[i]["cands"].append({"src": c["src"], "at": at, "ncc": r, "kind": "prop"}); added += 1
        return added
    for it in range(3):
        job.progress("Пошук збігів", 0.8 + 0.05 * it, "протягування збігів")
        a = propagate(range(1, tl.n), +1) + propagate(range(tl.n - 2, -1, -1), -1)
        job.log(f"протягування: додано {a} кандидатів")
        if a == 0: break

    def same(x, j, c, i):   # same source at the same alignment (a sample or two of refine jitter allowed)
        return x["src"] == c["src"] and abs((x["at"] - grid[j]["t"]) - (c["at"] - grid[i]["t"])) < P.bridge_tol
    for i in range(tl.n):                   # a bridge must be anchored by real matches on both sides
        keep = []
        for c in grid[i]["cands"]:
            if c["kind"] != "bridge": keep.append(c); continue
            ok = [False, False]
            for side, rng in ((0, range(i - 1, -1, -1)), (1, range(i + 1, tl.n))):
                for j in rng:
                    m = [x for x in grid[j]["cands"] if same(x, j, c, i)]
                    if not m: break
                    if m[0]["kind"] != "bridge": ok[side] = True; break
            if all(ok): keep.append(c)
        grid[i]["cands"] = keep
    return grid


def measure(grid, M, V, MID, SK):
    blk = int(1.0 * SR); mb = int(1.0 * SR / 4)
    def mseg(x, at):
        a = max(0, int(at * SR / 4) - mb // 2); s = x[a:a + mb]
        return np.pad(s, (0, mb - len(s)))
    def seg(x, at):
        a = max(0, int(at * SR) - blk // 2); s = x[a:a + blk].mean(1)
        return np.pad(s, (0, blk - len(s)))
    for g in grid:
        for c in g["cands"]:
            c["rms"] = rms(seg(M[c["src"]], c["at"])); c["vrms"] = rms(seg(V[c["src"]], c["at"]))
            S = np.abs(np.fft.rfft(seg(M[c["src"]], c["at"]) * np.hanning(blk)))
            c["_spec"] = np.log(np.add.reduceat(S, np.arange(0, len(S), 64)) / (c["rms"] + 1e-9) + 1e-9)
            c["_mid"] = mseg(MID[c["src"]], c["at"])
        sk = mseg(MID[SK], g["t"])
        for c in g["cands"]:
            c["midsk"] = 1.0 if c["kind"] == "self" else ncc_pair(c["_mid"], sk)


def source_gains(grid, names, SK):
    """per-source level so every source matches the skeleton's mix level (median over overlaps)."""
    ratios = {n: [] for n in names}
    for g in grid:
        if g["quiet"]: continue
        sk = [c for c in g["cands"] if c["kind"] == "self"]
        for c in g["cands"]:
            if c["rms"] > 1e-5: ratios[c["src"]].append(sk[0]["rms"] / c["rms"])
    G = {n: float(np.median(r)) if r else 1.0 for n, r in ratios.items()}
    G[SK] = 1.0
    return G


def score(grid, G, ref, penalty, P):
    for g in grid:
        specs = [c["_spec"] for c in g["cands"]]
        med = np.median(np.array(specs), 0) if len(specs) >= 3 and not g["quiet"] else None
        others = [c["midsk"] for c in g["cands"] if c["kind"] != "self"]
        best_mid = max(others) if others else 0.0
        for c in g["cands"]:
            rel = 1.0 if c["kind"] == "self" or best_mid < P.mid_gate else max(0.0, c["midsk"]) / best_mid
            c["mid_rel"] = rel; c["melody_ok"] = rel >= P.mid_ok
            c["leak"] = c["vrms"] * G[c["src"]] / ref          # voice energy vs normal music level
            c["vm"] = c["vrms"] / (c["rms"] + 1e-9)
            c["dev"] = float(np.mean(np.abs(c["_spec"] - med))) if med is not None else 0.0
            c["score"] = (c["leak"] + 0.15 * c["dev"] + penalty[c["src"]] + P.mid_w * (1 - rel)
                          + (0.1 * (1 - c["ncc"]) if c["kind"] == "prop" else 0.0))
        for c in g["cands"]: c.pop("_spec", None); c.pop("_mid", None)


def choose(grid, P):
    path, prev = [], None
    for g in grid:
        ok = [c for c in g["cands"] if c["melody_ok"]] or g["cands"]
        cs = sorted(ok, key=lambda c: c["score"])
        best = cs[0]
        if prev is not None:
            cont = [c for c in cs if c["src"] == prev["src"] and abs(c["at"] - prev["at"] - P.step) < 0.004]
            if cont and cont[0]["score"] <= best["score"] + P.hyst: best = cont[0]
        path.append(best); prev = best
    return path


def to_pieces(grid, path, P):
    pieces = []
    for g, p in zip(grid, path):
        s = p["at"] - P.step / 2
        if pieces and pieces[-1]["src"] == p["src"] and abs(pieces[-1]["start"] + pieces[-1]["dur"] - s) < 1e-3:
            pieces[-1]["dur"] += P.step; pieces[-1]["leak"] = max(pieces[-1]["leak"], p["leak"])
        else:
            pieces.append({"src": p["src"], "start": s, "dur": P.step, "t": g["t"] - P.step / 2, "leak": p["leak"]})
    return pieces


def fused_render(grid, path, M, G, band_limit, P, job):
    """STFT overlap-add render on the skeleton timeline (see module docstring, step 4)."""
    N, H = 4096, 1024
    win = np.hanning(N + 1)[:N].astype(np.float32)
    freqs = np.fft.rfftfreq(N, 1 / SR)
    shift = np.exp(2j * np.pi * np.arange(N // 2 + 1) / N)           # per-bin phase for a 1-sample shift
    total = int(len(grid) * P.step * SR)
    out = np.zeros((total + 2 * N, 2), np.float32); wsum = np.zeros(total + 2 * N, np.float32)  # offset N
    fused_steps = set()
    n_frames = total // H + 1
    for k in range(n_frames):
        if k % 200 == 0: job.progress("Рендер", k / n_frames)
        c_k = k * H
        i = min(len(grid) - 1, int(c_k / SR / P.step)); g = grid[i]; p = path[i]
        cands = [p]
        if p["leak"] > P.clean_leak:
            top = sorted((c for c in g["cands"] if c["melody_ok"]), key=lambda c: c["score"])[:P.fuse_max]
            if len(top) >= (2 if g["quiet"] else P.fuse_min): cands = top; fused_steps.add(i)
        ref = np.median([c["rms"] * G[c["src"]] for c in cands])
        X = []; mags = []
        for c in cands:
            pos = (c["at"] - g["t"]) * SR + c_k
            pi = int(np.floor(pos)); frac = pos - pi
            src = M[c["src"]]; a = pi - N // 2
            fr = src[max(0, a):max(0, a + N)]
            if a < 0: fr = np.vstack([np.zeros((-a, 2), np.float32), fr])
            if len(fr) < N: fr = np.vstack([fr, np.zeros((N - len(fr), 2), np.float32)])
            local = np.clip(ref / (c["rms"] * G[c["src"]] + 1e-9), 0.7, 1.4) if len(cands) > 1 else 1.0
            F = np.fft.rfft(fr.T * win, axis=1) * (G[c["src"]] * local)
            if frac: F = F * shift ** frac
            X.append(F)
            m = np.abs(F).sum(0)
            if band_limit.get(c["src"]): m = np.where(freqs > band_limit[c["src"]], 1e9, m)
            mags.append(m)
        if len(X) == 1:
            Y = X[0]
        else:
            X = np.array(X); mags = np.array(mags)
            r = 0 if g["quiet"] else int(P.fuse_rank * (len(X) - 1))   # in a stop: quietest copy per bin
            sel = np.argsort(mags, axis=0)[r]
            Y = X[sel, :, np.arange(X.shape[2])].T
        y = np.fft.irfft(Y, n=N, axis=1).T * win[:, None]
        a = c_k - N // 2 + N
        out[a:a + N] += y; wsum[a:a + N] += win ** 2
    out = out[N:N + total] / np.maximum(wsum[N:N + total], 1e-3)[:, None]
    return out, sorted(fused_steps)


def trim_silence(x, thr_db=-60):
    e = 20 * np.log10(np.abs(x).max(1) + 1e-9)
    nz = np.where(e > thr_db)[0]
    return (x[nz[0]:nz[-1] + 1], nz[0]) if len(nz) else (x, 0)


def rebuild(sources, job, P=None, map_cache=None):
    """sources: list[Source] (order kept). Returns (audio (n, 2) float32, result dict)."""
    P = P or Params()
    names = [s.name for s in sources]
    if len(set(names)) != len(names): raise ValueError("Назви джерел мають бути унікальними")
    M = {s.name: s.music for s in sources}; V = {s.name: s.vocals for s in sources}
    job.progress("Підготовка", 0.0, "мелодійний шар")
    MID = {s.name: melodic_layer(s.other) for s in sources}
    SK = max(sources, key=lambda s: len(s.music)).name            # skeleton = longest source
    job.log(f"скелет таймлайну: {SK} ({len(M[SK]) / SR:.1f} с)")
    tl = Timeline(M, SK, P)
    if map_cache and Path(map_cache).exists():
        grid = json.loads(Path(map_cache).read_text())
        job.log("карта збігів взята з кешу")
    else:
        grid = build_map(tl, job)
        if map_cache: Path(map_cache).write_text(json.dumps(grid, default=float))
    job.progress("Оцінка копій", 0.0)
    measure(grid, M, V, MID, SK)
    G = source_gains(grid, names, SK)
    job.log("вирівнювання гучності: " + ", ".join(f"{n} {20*np.log10(g):+.1f} дБ" for n, g in G.items()))
    score(grid, G, ref=10 ** (tl.median[SK] / 20), penalty={s.name: s.penalty for s in sources}, P=P)
    path = choose(grid, P)
    pieces = to_pieces(grid, path, P)
    out, fused = fused_render(grid, path, M, G, {s.name: s.band_limit for s in sources}, P, job)
    peak = float(np.abs(out).max())
    scale = min(1.0, 0.98 / peak); out *= scale
    out, lead = trim_silence(out)
    coverage = float(np.mean([any(c["src"] != SK for c in g["cands"]) for g in grid]))
    result = {"grid": grid, "path": path, "pieces": pieces, "fused_steps": fused, "G": G,
              "lead_trim": lead / SR, "scale": scale, "median_db": tl.median, "skeleton": SK,
              "coverage": coverage, "params": asdict(P),
              "sources": [dict(name=s.name, penalty=s.penalty, band_limit=s.band_limit, **s.info) for s in sources]}
    return out.astype(np.float32), result
