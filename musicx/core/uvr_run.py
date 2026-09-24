"""Run one audio-separator (RoFormer / MDX) model in its own process, so the app can show progress
and cancel instantly (kill). Prints 'PROGRESS <0..1>' lines and finally 'DONE <vocals> <instrumental>'.

  python -m musicx.core.uvr_run MODEL_FILE INPUT_WAV OUT_DIR MODELS_DIR
"""
import logging, sys
from pathlib import Path


def main():
    model, inp, out_dir, models_dir = sys.argv[1:5]
    import tqdm as _tq

    class Progress(_tq.tqdm):                     # audio-separator reports chunks through tqdm
        def __init__(self, *a, **k):
            k["disable"] = False; k["file"] = open("nul" if sys.platform == "win32" else "/dev/null", "w")
            super().__init__(*a, **k)

        def update(self, n=1):
            r = super().update(n)
            if self.total: print(f"PROGRESS {min(1.0, self.n / self.total):.4f}", flush=True)
            return r
    _tq.tqdm = Progress
    import tqdm.auto; tqdm.auto.tqdm = Progress

    from audio_separator.separator import Separator
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from musicx.core.models import use_downloader_in_audio_separator
    use_downloader_in_audio_separator(log=lambda t: print(t, flush=True))   # any missing file: via Downloader
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    sep = Separator(log_level=logging.WARNING, model_file_dir=models_dir, output_dir=out_dir, output_format="WAV",
                    normalization_threshold=1.0)
    sep.load_model(model_filename=model)
    files = [Path(out_dir) / Path(f).name for f in sep.separate(inp)]
    voc = next(f for f in files if "(vocals)" in f.name.lower())
    inst = next(f for f in files if f != voc)
    print(f"DONE {voc}|{inst}", flush=True)


if __name__ == "__main__":
    main()
