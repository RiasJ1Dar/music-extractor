"""Separation models offered by the app, presets (single models and ensembles) and downloading.

Every model file is fetched with the Downloader app (`dl get`, github.com/RiasJ1Dar/downloader):
segmented, resumes after a broken connection or a killed process. Without Downloader installed a
built-in resumable HTTP fallback is used. A file counts as finished only when `<file>.ok` exists and
no `<file>.dlpart` state is left, because `dl` pre-allocates the full size before the data arrives.

  python -m musicx.core.models --download default|all      (used by the installer)
"""
import argparse, logging, os, re, shutil, subprocess, sys, time
from dataclasses import dataclass
from pathlib import Path

MODELS_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MusicExtractor" / "models"
DEMUCS_DIR = MODELS_DIR / "demucs"
DEMUCS_ROOT_URL = "https://dl.fbaipublicfiles.com/demucs/"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass(frozen=True)
class Model:
    key: str
    engine: str          # "demucs" | "uvr" (audio-separator)
    ref: str             # demucs model name / audio-separator model file
    label: str


MODELS = {m.key: m for m in [
    Model("htdemucs", "demucs", "htdemucs", "Demucs htdemucs"),
    Model("htdemucs_ft", "demucs", "htdemucs_ft", "Demucs htdemucs_ft"),
    Model("htdemucs_6s", "demucs", "htdemucs_6s", "Demucs htdemucs_6s"),
    Model("hdemucs_mmi", "demucs", "hdemucs_mmi", "Demucs hdemucs_mmi"),
    Model("mdx_extra", "demucs", "mdx_extra", "Demucs mdx_extra"),
    Model("bs_roformer", "uvr", "model_bs_roformer_ep_317_sdr_12.9755.ckpt", "BS-RoFormer 1297"),
    Model("melband_kim", "uvr", "vocals_mel_band_roformer.ckpt", "Mel-Band RoFormer (Kim)"),
    Model("melband_inst_v2", "uvr", "melband_roformer_inst_v2.ckpt", "Mel-Band RoFormer Inst V2"),
    Model("melband_inst_becruily", "uvr", "mel_band_roformer_instrumental_becruily.ckpt", "Mel-Band RoFormer Instrumental (becruily)"),
    Model("mdx23c", "uvr", "MDX23C-8KFFT-InstVoc_HQ.ckpt", "MDX23C InstVoc HQ"),
    Model("mdx_inst_hq4", "uvr", "UVR-MDX-NET-Inst_HQ_4.onnx", "UVR-MDX-NET Inst HQ4"),
]}


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    models: tuple        # model keys; >1 = ensemble (instrumentals averaged)
    note: str = ""


# Ordered by the benchmark (README, "Моделі"): SDR of the instrumental on music + synthetic speech / music +
# a real narrator, dB. Ensembles barely help (+0.4 dB on real speech, -0.8 dB on synthetic), so the default
# is the best single model.
_BENCH = {"bs_roformer": (21.9, 19.2), "melband_kim": (18.9, 19.4), "melband_inst_v2": (18.7, 18.9),
          "melband_inst_becruily": (18.6, 18.7), "mdx_inst_hq4": (17.8, 16.2), "mdx23c": (14.0, 18.8),
          "htdemucs": (6.5, 18.3), "mdx_extra": (6.3, 17.4), "hdemucs_mmi": (6.0, 17.0), "htdemucs_ft": (6.5, 15.9),
          "htdemucs_6s": (1.7, 16.9)}


def _note(tts, real, extra=""):
    return f"Замір (SDR мінусу): синтезована мова {tts} дБ, живий диктор {real} дБ. {extra}".strip()


PRESETS = [
    Preset("bs_roformer", "BS-RoFormer — найкраща якість (рекомендовано)", ("bs_roformer",),
           _note(*_BENCH["bs_roformer"], "Найвища середня якість; ~1.5 хв на хвилину аудіо на RTX 2060.")),
    Preset("melband_kim", "Mel-Band RoFormer Kim — швидко, майже так само якісно", ("melband_kim",),
           _note(*_BENCH["melband_kim"], "У 5–7 разів швидше за BS-RoFormer.")),
    Preset("ens_bs_kim", "Ансамбль BS-RoFormer + Mel-Band Kim — найповільніше", ("bs_roformer", "melband_kim"),
           _note(21.2, 19.6, "Найкраще на живій мові (+0.4 дБ), трохи гірше на синтезованій.")),
] + [Preset(k, MODELS[k].label + (" (як у версії 1.0)" if k == "htdemucs_ft" else ""), (k,), _note(*_BENCH[k]))
     for k in ("melband_inst_v2", "melband_inst_becruily", "mdx_inst_hq4", "mdx23c", "htdemucs", "mdx_extra",
               "hdemucs_mmi", "htdemucs_ft", "htdemucs_6s")]
DEFAULT = "bs_roformer"          # mode A: best on the ground-truth benchmark
# Mode B keeps htdemucs_ft: on the real videos its stems gave the cleaner rebuilt track (BS-RoFormer's
# instrumental let the narrator through in music stops, where mode B sometimes has only one copy).
DEFAULT_REBUILD = "htdemucs_ft"
PARTS_MODEL = "htdemucs_ft"   # splits a clean instrumental into drums / bass / other when needed


def preset(key):
    return next(p for p in PRESETS if p.key == key)


# ---------------------------------------------------------------- fetching one file
def find_dl():
    for c in (shutil.which("dl"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Downloader", "dl.exe")):
        if c and os.path.isfile(c): return c
    return None


def is_done(dest):
    dest = Path(dest)
    return dest.is_file() and Path(f"{dest}.ok").is_file() and not Path(f"{dest}.dlpart").exists()


class NotFound(RuntimeError):
    """the server answered 404: callers may try another mirror."""


def fetch(url, dest, log=print, cancel=None):
    """download url -> dest, resuming whatever an earlier attempt left. Idempotent."""
    dest = Path(dest)
    if is_done(dest): return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and not Path(f"{dest}.dlpart").exists() and _remote_size(url) == dest.stat().st_size:
        Path(f"{dest}.ok").write_text("ok")      # complete file from before the markers existed
        return
    dl = find_dl()
    if dl: _fetch_dl(dl, url, dest, log, cancel)
    else: _fetch_py(url, dest, log, cancel)
    Path(f"{dest}.ok").write_text("ok")


def _remote_size(url):
    import requests
    try:
        r = requests.head(url, allow_redirects=True, timeout=30)
        return int(r.headers.get("content-length", -1)) if r.ok else -1
    except requests.RequestException:
        return -1


def _fetch_dl(dl, url, dest, log, cancel):
    last = ""
    for attempt in range(1, 4):
        log(f"Downloader: {dest.name}" + (f" (спроба {attempt})" if attempt > 1 else ""))
        p = subprocess.Popen([dl, "--lang", "en", "get", url, "-o", str(dest)], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        out = []
        while p.poll() is None:
            if cancel is not None and cancel.is_set():
                p.kill(); p.wait()
                from .common import Cancelled
                raise Cancelled()                 # dl keeps its state: the next run resumes
            time.sleep(0.2)
        out = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout.read().decode("utf-8", "replace"))
        if p.returncode == 0:
            m = re.search(r"(?:готово|done)[^\n]*", out)
            if m: log(f"   {m.group(0).strip()}")
            return
        last = out.strip().splitlines()[-1] if out.strip() else f"exit {p.returncode}"
        if " 404 " in out or "404" in last: raise NotFound(last)
        time.sleep(3 * attempt)                   # network hiccup: dl resumes from its state file
    raise RuntimeError(f"не вдалося завантажити {url}: {last}")


def _fetch_py(url, dest, log, cancel):
    """fallback without Downloader: single connection, resumes via HTTP Range into <dest>.part."""
    import requests
    part = Path(f"{dest}.part")
    if dest.is_file() and not part.exists(): dest.replace(part)   # unfinished file from an older attempt
    for attempt in range(1, 6):
        have = part.stat().st_size if part.exists() else 0
        try:
            with requests.get(url, headers={"Range": f"bytes={have}-"} if have else {}, stream=True, timeout=60) as r:
                if r.status_code == 404: raise NotFound(f"404 {url}")
                if r.status_code == 416: break                     # already complete
                r.raise_for_status()
                mode = "ab" if have and r.status_code == 206 else "wb"
                total = int(r.headers.get("content-length", 0)) + (have if mode == "ab" else 0)
                log(f"завантаження {dest.name} ({total / 2**20:.0f} МБ)" if total else f"завантаження {dest.name}")
                with open(part, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        if cancel is not None and cancel.is_set():
                            from .common import Cancelled
                            raise Cancelled()
                        f.write(chunk)
            if not total or part.stat().st_size >= total: break
        except (requests.RequestException, OSError) as e:
            if attempt == 5: raise RuntimeError(f"не вдалося завантажити {url}: {e}")
            time.sleep(3 * attempt)
    part.replace(dest)


# ---------------------------------------------------------------- whole models
def _demucs_files(name):
    """(url, filename) of every weight file of a demucs model / bag, from demucs' own index."""
    import yaml
    from demucs.pretrained import REMOTE_ROOT
    index, root = {}, ""
    for line in (REMOTE_ROOT / "files.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if line.startswith("root:"): root = line.split(":", 1)[1].strip(); continue
        index[line.split("-", 1)[0]] = (DEMUCS_ROOT_URL + root + line, line)
    bag = REMOTE_ROOT / f"{name}.yaml"
    sigs = yaml.safe_load(bag.read_text())["models"] if bag.exists() else [name]
    return bag if bag.exists() else None, [index[s] for s in sigs]


def ensure_demucs(name, log=print, cancel=None):
    """weights into DEMUCS_DIR (loaded with repo=DEMUCS_DIR, no network at run time)."""
    bag, files = _demucs_files(name)
    for url, fn in files:
        fetch(url, DEMUCS_DIR / fn, log, cancel)
    if bag is not None: shutil.copyfile(bag, DEMUCS_DIR / bag.name)
    return DEMUCS_DIR


def use_downloader_in_audio_separator(log=print, cancel=None):
    """make audio-separator fetch through fetch(): Downloader, resume, .ok markers, 404 -> mirror."""
    from audio_separator.separator import Separator

    def download_file_if_not_exists(self, url, output_path):
        try:
            fetch(url, output_path, log, cancel)
        except NotFound as e:
            raise RuntimeError(str(e))            # audio-separator then tries its next repository
    Separator.download_file_if_not_exists = download_file_if_not_exists


def ensure_uvr(model_file, log=print, cancel=None):
    from audio_separator.separator import Separator
    use_downloader_in_audio_separator(log, cancel)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    Separator(log_level=logging.WARNING, model_file_dir=str(MODELS_DIR), info_only=True).download_model_files(model_file)


def ensure(keys, log=print, cancel=None):
    for k in keys:
        m = MODELS[k]
        log(f"модель {m.label}")
        if m.engine == "demucs": ensure_demucs(m.ref, log, cancel)
        else: ensure_uvr(m.ref, log, cancel)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", choices=["default", "all"], required=True)
    a = ap.parse_args()
    keys = sorted(MODELS) if a.download == "all" else sorted(set(preset(DEFAULT).models) | set(preset(DEFAULT_REBUILD).models) | {PARTS_MODEL})
    ensure(keys, log=lambda s: print(s, flush=True))
    print("models ready", flush=True)


if __name__ == "__main__":
    sys.exit(main())
