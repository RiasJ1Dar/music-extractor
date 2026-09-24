"""Shared helpers: progress / cancel plumbing, ffmpeg lookup, small DSP utilities."""
import os, shutil, subprocess, sys
from pathlib import Path

import numpy as np

SR = 44100
APP_ROOT = Path(__file__).resolve().parents[2]
CACHE_ROOT = Path(os.environ.get("MUSICX_CACHE") or
                  Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MusicExtractor" / "cache")
MEDIA_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".mp3", ".wav", ".flac", ".m4a",
             ".aac", ".ogg", ".opus", ".wma"}
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class Cancelled(Exception):
    """Raised inside a job when the user pressed Cancel."""


class Job:
    """Progress reporting and cancellation handed to every core function.

    progress(stage, fraction 0..1, text) and log(text) are optional callbacks;
    cancel is anything with is_set() (threading.Event)."""

    def __init__(self, progress=None, log=None, cancel=None):
        self._progress = progress
        self._log = log
        self._cancel = cancel

    def check(self):
        if self._cancel is not None and self._cancel.is_set():
            raise Cancelled()

    def progress(self, stage, frac, text=""):
        self.check()
        if self._progress: self._progress(stage, float(min(1.0, max(0.0, frac))), text)

    def log(self, text):
        if self._log: self._log(text)
        else: print(text)

    def sub(self, stage, lo, hi):
        """progress callback mapping 0..1 of a sub-step into lo..hi of the current stage."""
        return lambda f, text="": self.progress(stage, lo + (hi - lo) * f, text)


def find_tool(name):
    """ffmpeg / ffprobe: PATH, winget links, or the copy the installer drops into tools/."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    cands = [shutil.which(name),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", exe),
             str(APP_ROOT / "tools" / "ffmpeg" / "bin" / exe)]
    for c in cands:
        if c and os.path.isfile(c): return c
    raise FileNotFoundError(f"{name} не знайдено. Запустіть установник Music Extractor ще раз — він докачає залежності.")


def cache_size(root=None):
    """bytes used by cached separations / maps."""
    root = Path(root or CACHE_ROOT)
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.exists() else 0


def clear_cache(root=None):
    """delete cached separations / maps (models are kept). Returns bytes freed."""
    root = Path(root or CACHE_ROOT)
    n = cache_size(root)
    if root.exists(): shutil.rmtree(root, ignore_errors=True)
    return n


def human_size(n):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ": return f"{n:.0f} {unit}" if unit in ("Б", "КБ") else f"{n:.1f} {unit}"
        n /= 1024


def run_tool(args):
    r = subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(args[0]).name} завершився з помилкою:\n{r.stderr.strip()[-2000:]}")
    return r.stdout


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def rms_db(x):
    return 20 * np.log10(rms(x) + 1e-9)
