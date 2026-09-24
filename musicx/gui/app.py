"""Music Extractor desktop app (PySide6). All heavy work runs in a QThread; the UI never blocks."""
import os, sys, threading, traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QRadioButton, QButtonGroup, QListWidget, QPushButton, QLineEdit, QFileDialog,
                               QComboBox, QCheckBox, QProgressBar, QLabel, QPlainTextEdit, QMessageBox,
                               QGroupBox, QAbstractItemView)

from musicx import __version__
from musicx.core import models as M
from musicx.core.common import Job, Cancelled, MEDIA_EXT, CACHE_ROOT, cache_size, clear_cache, human_size

MODE_MINUS, MODE_REBUILD = 0, 1
# overall progress bar: where each core stage sits, per mode
STAGES = {
    MODE_MINUS: {"Розділення": (0.0, 1.0), "Збереження": (0.0, 1.0), "Готово": (1.0, 1.0)},
    MODE_REBUILD: {"Розділення": (0.0, 0.60), "Підготовка": (0.60, 0.61), "Пошук збігів": (0.61, 0.85),
                   "Оцінка копій": (0.85, 0.87), "Рендер": (0.87, 0.98), "Збереження": (0.98, 1.0),
                   "Готово": (1.0, 1.0)},
}


class Worker(QObject):
    progress = Signal(str, float, str)
    log = Signal(str)
    done = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, mode, files, out_dir, opts):
        super().__init__()
        self.mode, self.files, self.out_dir, self.opts = mode, files, out_dir, opts
        self.cancel_event = threading.Event()

    def run(self):
        job = Job(progress=lambda s, f, t: self.progress.emit(s, f, t), log=self.log.emit, cancel=self.cancel_event)
        try:
            from musicx.core.jobs import run_minus, run_rebuild   # heavy imports (torch) off the UI thread
            if self.mode == MODE_MINUS:
                res = run_minus(self.files, self.out_dir, job, fmt=self.opts["fmt"], save_stems=self.opts["stems"],
                                shifts=self.opts["shifts"], device=self.opts["device"], preset=self.opts["preset"])
            else:
                res = run_rebuild(self.files, self.out_dir, job, fmt=self.opts["fmt"],
                                  shifts=self.opts["shifts"], device=self.opts["device"], preset=self.opts["preset"])
                res = {"files": res["files"], "coverage": res["coverage"]}
            self.done.emit(res)
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:
            self.failed.emit(f"{e}\n\n{traceback.format_exc()}")


class FileList(QListWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMinimumHeight(140)

    def paths(self):
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def add(self, paths):
        have = set(self.paths())
        for p in paths:
            p = Path(p)
            items = sorted(x for x in p.rglob("*") if x.suffix.lower() in MEDIA_EXT) if p.is_dir() else [p]
            for x in items:
                if x.suffix.lower() in MEDIA_EXT and str(x) not in have:
                    self.addItem(x.name); self.item(self.count() - 1).setData(Qt.UserRole, str(x))
                    self.item(self.count() - 1).setToolTip(str(x)); have.add(str(x))
        self.changed.emit()

    def dragEnterEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.add(u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()); e.acceptProposedAction()
        else:
            super().dropEvent(e)


class MainWindow(QMainWindow):
    cuda_info = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Music Extractor {__version__}")
        self.resize(760, 720)
        self.thread = None; self.worker = None; self._best = 0.0; self._last_out = None
        c = QWidget(); self.setCentralWidget(c); v = QVBoxLayout(c)

        mode_box = QGroupBox("Режим"); mv = QVBoxLayout(mode_box)
        self.rb_minus = QRadioButton("Мінус / стеми — кожен файл обробляється окремо")
        self.rb_rebuild = QRadioButton("Відновити трек з кількох джерел — у файлах звучить той самий трек")
        self.rb_minus.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.rb_minus, MODE_MINUS); self.mode_group.addButton(self.rb_rebuild, MODE_REBUILD)
        self.mode_hint = QLabel(); self.mode_hint.setWordWrap(True); self.mode_hint.setStyleSheet("color: gray")
        for w in (self.rb_minus, self.rb_rebuild, self.mode_hint): mv.addWidget(w)
        v.addWidget(mode_box)

        files_box = QGroupBox("Файли (відео або аудіо; можна перетягнути сюди)"); fv = QVBoxLayout(files_box)
        self.files = FileList(); fv.addWidget(self.files)
        fb = QHBoxLayout()
        self.btn_add = QPushButton("Додати…"); self.btn_del = QPushButton("Прибрати"); self.btn_clear = QPushButton("Очистити")
        for b in (self.btn_add, self.btn_del, self.btn_clear): fb.addWidget(b)
        fb.addStretch(); fv.addLayout(fb)
        v.addWidget(files_box)

        opt = QGroupBox("Налаштування"); g = QGridLayout(opt)
        g.addWidget(QLabel("Папка результату:"), 0, 0)
        self.out_edit = QLineEdit(str(Path.home() / "Music" / "Music Extractor"))
        self.btn_out = QPushButton("Огляд…")
        g.addWidget(self.out_edit, 0, 1, 1, 3); g.addWidget(self.btn_out, 0, 4)
        g.addWidget(QLabel("Формат:"), 1, 0)
        self.fmt = QComboBox(); self.fmt.addItem("WAV 24-bit", "wav"); self.fmt.addItem("FLAC", "flac")
        g.addWidget(self.fmt, 1, 1)
        g.addWidget(QLabel("Якість:"), 1, 2)
        self.quality = QComboBox(); self.quality.addItem("Якісно (shifts 2)", 2); self.quality.addItem("Швидко (shifts 1)", 1)
        self.quality.setToolTip("Скільки зсувів усереднює Demucs. Моделей RoFormer / MDX не стосується.")
        g.addWidget(self.quality, 1, 3)
        g.addWidget(QLabel("Модель:"), 3, 0)
        self.model = QComboBox()
        for p in M.PRESETS:
            self.model.addItem(p.label, p.key)
            self.model.setItemData(self.model.count() - 1, p.note or p.label, Qt.ToolTipRole)
        self.model.setCurrentIndex(self.model.findData(M.DEFAULT))
        self._model_touched = False                  # user picked a model -> stop following the mode default
        self.model.activated.connect(lambda *_: setattr(self, "_model_touched", True))
        g.addWidget(self.model, 3, 1, 1, 4)
        g.addWidget(QLabel("Пристрій:"), 2, 0)
        self.device = QComboBox(); self.device.addItem("Авто", "auto"); self.device.addItem("CUDA (відеокарта)", "cuda")
        self.device.addItem("CPU", "cpu")
        g.addWidget(self.device, 2, 1)
        self.stems = QCheckBox("Зберегти стеми (голос, барабани, бас, інше)")
        g.addWidget(self.stems, 2, 2, 1, 3)
        v.addWidget(opt)

        rb = QHBoxLayout()
        self.btn_start = QPushButton("Старт"); self.btn_start.setDefault(True); self.btn_start.setMinimumHeight(34)
        self.btn_cancel = QPushButton("Скасувати"); self.btn_cancel.setEnabled(False)
        self.btn_open = QPushButton("Відкрити папку")
        self.btn_cache = QPushButton("Очистити кеш")
        self.btn_cache.setToolTip("Розділені стеми зберігаються тут, щоб повторна обробка була миттєвою:\n"
                                  f"{CACHE_ROOT}")
        rb.addWidget(self.btn_start, 2); rb.addWidget(self.btn_cancel, 1); rb.addWidget(self.btn_open, 1)
        rb.addWidget(self.btn_cache, 1)
        v.addLayout(rb)
        self.stage = QLabel("Готово до роботи"); v.addWidget(self.stage)
        self.bar = QProgressBar(); self.bar.setRange(0, 1000); self.bar.setTextVisible(False); v.addWidget(self.bar)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000)
        v.addWidget(self.log, 1)

        self.btn_add.clicked.connect(self.pick_files)
        self.btn_del.clicked.connect(lambda: [self.files.takeItem(self.files.row(i)) for i in self.files.selectedItems()])
        self.btn_clear.clicked.connect(self.files.clear)
        self.btn_out.clicked.connect(self.pick_out)
        self.btn_start.clicked.connect(self.start)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_open.clicked.connect(self.open_out)
        self.btn_cache.clicked.connect(self.clear_cache)
        self.update_cache_label()
        self.mode_group.idToggled.connect(lambda *_: self.update_mode())
        self.update_mode()
        self.cuda_info.connect(self.on_cuda_info)
        threading.Thread(target=self.detect_cuda, daemon=True).start()   # importing torch takes seconds

    # ---------------------------------------------------------------- UI helpers
    def update_mode(self):
        minus = self.mode() == MODE_MINUS
        if hasattr(self, "model") and not self._model_touched:
            self.model.setCurrentIndex(self.model.findData(M.DEFAULT if minus else M.DEFAULT_REBUILD))
        self.stems.setEnabled(minus)
        self.mode_hint.setText(
            "Для кожного файлу: instrumental (без голосу) і, за бажанням, окремі стеми." if minus else
            "Потрібно 2+ файли з тим самим треком (напр. кілька відео). Голос і шуми прибираються, "
            "беручи кожен шматок треку з того файлу, де він найчистіший. Результат: clean_track + звіт.")

    def mode(self):
        return self.mode_group.checkedId()

    def detect_cuda(self):
        try:
            import torch
            ok = torch.cuda.is_available()
            name = torch.cuda.get_device_name(0) if ok else ""
        except Exception:
            ok, name = False, ""
        self.cuda_info.emit(ok, name)

    def on_cuda_info(self, ok, name):
        if not ok:
            self.device.model().item(1).setEnabled(False)
            self.append_log("Відеокарту CUDA не знайдено — розділення працюватиме на процесорі (повільніше).")
        else:
            self.append_log(f"Відеокарта: {name}")

    def append_log(self, text):
        self.log.appendPlainText(text)

    def pick_files(self):
        exts = " ".join(f"*{e}" for e in sorted(MEDIA_EXT))
        paths, _ = QFileDialog.getOpenFileNames(self, "Виберіть файли", str(Path.home()), f"Медіа ({exts});;Усі файли (*)")
        self.files.add(paths)

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Папка результату", self.out_edit.text())
        if d: self.out_edit.setText(d)

    def open_out(self):
        d = Path(self.out_edit.text()); d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def update_cache_label(self):
        n = cache_size()
        self.btn_cache.setText(f"Очистити кеш ({human_size(n)})" if n else "Кеш порожній")
        self.btn_cache.setEnabled(bool(n) and not (self.thread and self.thread.isRunning()))

    def clear_cache(self):
        n = cache_size()
        if QMessageBox.question(self, "Очистити кеш",
                                f"Видалити збережені результати розділення ({human_size(n)})?\n\n"
                                "Готові файли в папці результату не зачіпаються. Завантажені моделі "
                                "залишаться. Повторна обробка тих самих файлів знову займе час.") != QMessageBox.Yes:
            return
        freed = clear_cache()
        self.append_log(f"Кеш очищено: звільнено {human_size(freed)}")
        self.update_cache_label()

    def set_running(self, running):
        for w in (self.btn_start, self.btn_add, self.btn_del, self.btn_clear, self.btn_out, self.out_edit,
                  self.fmt, self.quality, self.device, self.model, self.rb_minus, self.rb_rebuild, self.files):
            w.setEnabled(not running)
        self.stems.setEnabled(not running and self.mode() == MODE_MINUS)
        self.btn_cancel.setEnabled(running)
        if running: self.btn_cache.setEnabled(False)
        else: self.update_cache_label()

    # ---------------------------------------------------------------- job control
    def start(self):
        files = self.files.paths()
        if not files:
            QMessageBox.information(self, "Немає файлів", "Додайте хоча б один файл."); return
        mode = self.mode()
        if mode == MODE_REBUILD and len(files) == 1:
            r = QMessageBox.question(self, "Один файл",
                                     "Для відновлення потрібно щонайменше 2 файли з тим самим треком.\n"
                                     "Зробити мінус (прибрати голос) з цього файлу?")
            if r != QMessageBox.Yes: return
            self.rb_minus.setChecked(True); mode = MODE_MINUS
        missing = [f for f in files if not Path(f).exists()]
        if missing:
            QMessageBox.warning(self, "Файл не знайдено", "\n".join(missing)); return
        opts = {"fmt": self.fmt.currentData(), "stems": self.stems.isChecked(),
                "shifts": self.quality.currentData(), "device": self.device.currentData(),
                "preset": self.model.currentData()}
        self._run_mode = mode; self._best = 0.0; self.bar.setValue(0)
        self.append_log(f"—— {'Мінус / стеми' if mode == MODE_MINUS else 'Відновлення треку'}: {len(files)} файл(ів)")
        self.thread = QThread(self)
        self.worker = Worker(mode, files, self.out_edit.text(), opts)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.append_log)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_cancelled)
        for s in (self.worker.done, self.worker.failed, self.worker.cancelled): s.connect(self.thread.quit)
        self.thread.finished.connect(lambda: self.set_running(False))
        self.set_running(True)
        self.stage.setText("Запуск…")
        self.thread.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel_event.set()
            self.btn_cancel.setEnabled(False)
            self.stage.setText("Скасування…")

    def on_progress(self, stage, frac, text):
        lo, hi = STAGES[self._run_mode].get(stage, (self._best, self._best))
        self._best = max(self._best, lo + (hi - lo) * frac)
        self.bar.setValue(int(self._best * 1000))
        if self.worker and not self.worker.cancel_event.is_set():
            self.stage.setText(f"{stage}{': ' + text if text else ''}  ({self._best * 100:.0f}%)")

    def on_done(self, res):
        self.bar.setValue(1000); self.stage.setText("Готово")
        self.append_log("Готово. Файли:\n  " + "\n  ".join(res["files"]))
        if res.get("coverage") is not None and res["coverage"] < 0.2:
            QMessageBox.warning(self, "Джерела майже не збігаються",
                                f"Лише {res['coverage']*100:.0f}% треку знайдено більш ніж в одному файлі.\n"
                                "Схоже, у файлах звучать різні треки: результат майже повністю взято з одного "
                                "файлу. Деталі — у звіті.")

    def on_failed(self, msg):
        self.stage.setText("Помилка")
        self.append_log("❌ " + msg)
        QMessageBox.critical(self, "Помилка", msg.split("\n\n")[0])

    def on_cancelled(self):
        self.stage.setText("Скасовано"); self.bar.setValue(0)
        self.append_log("Скасовано.")

    def closeEvent(self, e):
        if self.thread and self.thread.isRunning():
            if QMessageBox.question(self, "Задача виконується", "Скасувати задачу і вийти?") != QMessageBox.Yes:
                e.ignore(); return
            self.worker.cancel_event.set(); self.thread.quit(); self.thread.wait(30000)
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Music Extractor")
    w = MainWindow(); w.show()
    w.files.add(a for a in sys.argv[1:] if os.path.exists(a))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
