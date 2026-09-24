"""GUI end-to-end (in-process, real clicks via QTest): mode A on one file.
  1. Start, wait until the separation model is running, press Cancel -> the job stops, UI unlocks.
  2. Start again and let it finish -> instrumental written.
Throughout, a 20 ms heartbeat timer on the UI thread measures the longest UI stall."""
import os, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work" / "test_gui"
if WORK.exists(): shutil.rmtree(WORK)
os.environ["MUSICX_CACHE"] = str(WORK / "cache")
sys.path.insert(0, str(ROOT))

import soundfile as sf                                            # noqa: E402
from PySide6.QtCore import QTimer, Qt                             # noqa: E402
from PySide6.QtTest import QTest                                  # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402
from musicx.gui.app import MainWindow                             # noqa: E402

SRC = Path(os.environ.get("MUSICX_TEST_MEDIA", Path.home() / "Downloads")) / "vivaldi_drones-264.mp4"
app = QApplication(sys.argv)
w = MainWindow(); w.show()
beat = {"last": time.perf_counter(), "max": 0.0}


def tick():
    now = time.perf_counter(); beat["max"] = max(beat["max"], now - beat["last"]); beat["last"] = now


hb = QTimer(); hb.timeout.connect(tick); hb.start(20)


def wait(cond, timeout, what):
    t0 = time.time()
    while not cond():
        app.processEvents(); time.sleep(0.005)
        if time.time() - t0 > timeout: raise TimeoutError(what)
    return time.time() - t0


wait(lambda: "Відеокарта" in w.log.toPlainText() or "CUDA не знайдено" in w.log.toPlainText(), 60, "cuda probe")
w.files.add([str(SRC)]); w.out_edit.setText(str(WORK / "out")); w.rb_minus.setChecked(True)
ok = True

# 1. cancel in the middle of Demucs
beat["max"] = 0; beat["last"] = time.perf_counter()
QTest.mouseClick(w.btn_start, Qt.LeftButton)
wait(lambda: w.stage.text().startswith("Розділення") and "%" in w.stage.text() and w.bar.value() > 150, 900,
     "separation progress")
print(f"[cancel] stage before cancel: {w.stage.text()!r}")
QTest.mouseClick(w.btn_cancel, Qt.LeftButton)
dt = wait(lambda: not w.thread.isRunning() and w.btn_start.isEnabled(), 60, "cancel")
res1 = w.stage.text() == "Скасовано" and not list((WORK / "out").glob("*instrumental*"))
print(f"[cancel] stopped {dt:.2f} s after Cancel, stage {w.stage.text()!r}, no output written; "
      f"longest UI stall {beat['max']*1000:.0f} ms -> {'PASS' if res1 and beat['max'] < 0.5 else 'FAIL'}")
ok &= res1 and beat["max"] < 0.5

# 2. full run
beat["max"] = 0; beat["last"] = time.perf_counter()
QTest.mouseClick(w.btn_start, Qt.LeftButton)
dt = wait(lambda: w.stage.text() in ("Готово", "Помилка"), 1200, "full run")
outs = list((WORK / "out").glob("*instrumental*"))
res2 = w.stage.text() == "Готово" and len(outs) == 1
if res2:
    x, sr = sf.read(outs[0]); print(f"[full] {outs[0].name}: {len(x)/sr:.2f} s, {sr} Hz")
print(f"[full] finished in {dt:.0f} s, stage {w.stage.text()!r}, progress {w.bar.value()/10:.0f}%; "
      f"longest UI stall {beat['max']*1000:.0f} ms -> {'PASS' if res2 and beat['max'] < 0.5 else 'FAIL'}")
ok &= res2 and beat["max"] < 0.5
print("--- log ---\n" + w.log.toPlainText())
w.close()
sys.exit(0 if ok else 1)
