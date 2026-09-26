**Українська** · [English](#english)

# Music Extractor

<img src="musicx/gui/icon.png" width="96" align="right" alt="">

Програма для Windows, яка витягує музику з відео та аудіо:

- **Мінус / стеми** — прибирає голос із будь-якого файлу (instrumental), за бажанням розкладає
  на голос, барабани, бас та інше.
- **Відновлення треку з кількох джерел** — якщо один і той самий трек звучить у кількох відео
  (реклама, трейлери, ролики з диктором), програма знаходить кожен фрагмент треку в усіх файлах,
  бере його звідти, де він найчистіший, і склеює в один повний трек без голосу. Там, де голос є
  в усіх копіях, копії зливаються: голос у кожній звучить в іншому місці, а музика однакова.

## Встановлення

Завантажте `MusicExtractor-Setup-<версія>.exe` зі сторінки
[Releases](https://github.com/RiasJ1Dar/music-extractor/releases) і запустіть.
Установник невеликий: під час встановлення він сам завантажує ffmpeg, Python 3.11, PyTorch
(версію для відеокарти NVIDIA або для процесора), Demucs, audio-separator і моделі — разом
близько 5 ГБ. Якщо зв'язок обірвався, просто запустіть установник ще раз: уже завантажене не
качається повторно.

Моделі завантажуються через [Downloader](https://github.com/RiasJ1Dar/downloader), якщо він
встановлений (сегментовано, з докачуванням), інакше — вбудованим завантажувачем із докачуванням.

⚠️ Установник не підписаний, тож Windows SmartScreen попередить при першому запуску
(«Докладніше» → «Виконати в будь-якому разі»).

Вимоги: Windows 10/11 x64, ~6 ГБ місця. Відеокарта NVIDIA не обов'язкова, але з нею
обробка в рази швидша.

## Моделі

У програмі можна вибрати модель розділення. Порядок і модель за замовчуванням визначено
заміром: чистий трек змішано з мовою з відомим результатом, і порівняно мінус кожної моделі з
оригінальною музикою (SDR, дБ, більше = краще). «Синтезована» — голос Windows TTS поверх
музики, «живий» — справжній диктор.

| Модель | Синтезована | Живий | Швидкість |
|---|---:|---:|---|
| **BS-RoFormer 1297** (за замовчуванням) | **21.9** | 19.2 | повільно |
| Ансамбль BS-RoFormer + Mel-Band Kim | 21.2 | **19.6** | найповільніше |
| Mel-Band RoFormer (Kim) | 18.9 | 19.4 | **швидко** |
| Mel-Band RoFormer Inst V2 | 18.7 | 18.9 | середньо |
| Mel-Band RoFormer Instrumental (becruily) | 18.6 | 18.7 | швидко |
| UVR-MDX-NET Inst HQ4 | 17.8 | 16.2 | швидко |
| MDX23C InstVoc HQ | 14.0 | 18.8 | середньо |
| Demucs htdemucs | 6.5 | 18.3 | швидко |
| Demucs mdx_extra | 6.3 | 17.4 | повільно |
| Demucs hdemucs_mmi | 6.0 | 17.0 | швидко |
| Demucs htdemucs_ft (версія 1.0) | 6.5 | 15.9 | середньо |
| Demucs htdemucs_6s | 1.7 | 16.9 | швидко |

Моделі RoFormer виявились кращими за Demucs на 1–15 дБ; ансамблі майже не додають якості.
Для стемів (барабани / бас / інше) чистий мінус додатково розкладає Demucs htdemucs_ft.

Повний список моделей (файли, розміри, обидва заміри, що обрати) — у [docs/MODELS.md](docs/MODELS.md).

**Режим відновлення з кількох джерел** за замовчуванням використовує Demucs htdemucs_ft: на реальних
відео з диктором BS-RoFormer у паузах музики пропускав голос у мінус, і відновлений трек виходив
гіршим. Модель можна змінити у вікні програми для будь-якого режиму.

## Як працює відновлення з кількох джерел

1. Кожен файл розділяється на музику й голос.
2. Найдовший файл стає таймлайном. Для кожних 0.25 с треку знаходяться всі місця в усіх файлах
   (включно з повторами петлі), де грає те саме — кроскореляцією з точністю до семпла.
3. Кожна копія оцінюється: скільки голосу поруч, чи збігається мелодійний шар (барабани й бас
   однакові на кожному колі петлі, а фраза зверху — ні), чи немає сторонніх звуків, якість кодека.
4. Чиста копія береться як є; якщо голос є в усіх, береться медіана кількох копій у кожній
   частотно-часовій клітинці. Паузи-«стопи», що є в самій композиції, зберігаються.
5. Поруч із треком пишеться звіт: звідки взято кожен шматок і де міг лишитися голос.

## Вхідні й вихідні файли

Вхід: `.mp4 .mkv .mov .webm .avi .m4v .mp3 .wav .flac .m4a .aac .ogg .opus .wma`.

Результат пишеться у вибрану папку у форматі WAV 24-bit або FLAC. Наявні файли не
перезаписуються: до нового імені додається ` (2)`, ` (3)` тощо.

| Режим | Файли |
|---|---|
| Мінус / стеми | `<ім'я>_instrumental.wav`, зі стемами ще й `<ім'я>_stems\` з `vocals`, `drums`, `bass`, `other` |
| Відновлення з кількох джерел | `clean_track.wav` + звіт `clean_track_report.md` |

| Що | Де |
|---|---|
| Програма (установник) | `%LOCALAPPDATA%\Programs\Music Extractor` |
| Лог установки | `install.log` у папці програми |
| Моделі | `%LOCALAPPDATA%\MusicExtractor\models` |
| Кеш розділених стемів і карт збігів | `%LOCALAPPDATA%\MusicExtractor\cache`, або шлях зі змінної середовища `MUSICX_CACHE` |

Кеш робить повторну обробку тих самих файлів миттєвою. Очистити його можна кнопкою «Очистити кеш»,
моделі при цьому лишаються.

## Командний рядок

Основна робота йде через вікно програми. Ці команди запускаються з папки програми (або з клону
репозиторію) Python-ом із `.venv`.

**Запуск програми з файлами у списку:**

```
.venv\Scripts\python -m musicx.gui.app [ФАЙЛ ...]
```

Шляхи, що існують, одразу додаються до списку файлів. Режим, модель і решту налаштувань вибирайте у вікні.

**Завантаження моделей наперед:**

```
.venv\Scripts\python -m musicx.core.models --download default   # моделі за замовчуванням
.venv\Scripts\python -m musicx.core.models --download all       # усі моделі (див. docs/MODELS.md)
```

| Прапорець | Значення |
|---|---|
| `--download default` | моделі для мінусу й відновлення за замовчуванням, а також `htdemucs_ft` для стемів |
| `--download all` | усі 11 моделей |

**Встановлення залежностей** (`installer\deps.ps1`, його запускає установник, можна й вручну;
повторний запуск пропускає вже зроблені кроки):

```
powershell -ExecutionPolicy Bypass -File installer\deps.ps1 [-Cpu] [-AllModels] [-InstallDownloader] [-NoShortcut] [-FromSetup]
```

| Прапорець | Значення |
|---|---|
| `-Cpu` | ставити PyTorch для процесора, навіть якщо є відеокарта NVIDIA |
| `-AllModels` | завантажити всі моделі одразу (інакше решта завантажується при першому використанні) |
| `-InstallDownloader` | встановити [Downloader](https://github.com/RiasJ1Dar/downloader), якщо його немає, і качати ним усі великі файли |
| `-NoShortcut` | не створювати ярлик на робочому столі |
| `-FromSetup` | службовий: вивід прогресу для вікна установника, без ярлика |

**Тихе встановлення.** Установник зроблений на Inno Setup, тож приймає його стандартні ключі. Додаткові
завдання: `desktopicon` (ярлик), `cpu` (PyTorch для процесора), `allmodels` (усі моделі),
`downloader` (встановити Downloader):

```
MusicExtractor-Setup-1.1.0.exe /VERYSILENT /TASKS="desktopicon,allmodels"
```

**Службова команда** `python -m musicx.core.uvr_run MODEL_FILE INPUT_WAV OUT_DIR MODELS_DIR` запускає одну
модель RoFormer / MDX в окремому процесі. Її викликає сама програма, вручну вона не потрібна.

## Розробка

```
git clone https://github.com/RiasJ1Dar/music-extractor
cd music-extractor
powershell -ExecutionPolicy Bypass -File installer\deps.ps1   # .venv + усі залежності
.venv\Scripts\python -m musicx.gui.app
```

Збірка установника (потрібен [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```
ISCC installer\MusicExtractor.iss      # -> dist\MusicExtractor-Setup-<версія>.exe
```

Версію установника можна задати під час збірки: `ISCC /DAppVersion=1.2.0 installer\MusicExtractor.iss`.

Тести потребують власних тестових файлів (шляхи на початку кожного тесту):

```
.venv\Scripts\python tests\test_minus.py [ключ]            # мінус; ключ моделі з docs/MODELS.md, типово htdemucs_ft
.venv\Scripts\python tests\regress_rebuild.py [cached|fresh] # відновлення проти еталону; cached — з готових стемів і карти
.venv\Scripts\python tests\test_gui.py                      # вікно програми, мінус одного файлу
```

## Ліцензія

[MIT](LICENSE) — можна вільно використовувати, змінювати й поширювати, зберігши рядок про автора.

Сторонні компоненти мають власні ліцензії: [Demucs](https://github.com/adefossez/demucs) (MIT),
[audio-separator](https://github.com/nomadkaraoke/python-audio-separator) (MIT),
PySide6 (LGPL-3.0), PyTorch (BSD), ffmpeg (LGPL/GPL). Моделі — ліцензії їхніх авторів.

---

## English

**Music Extractor** is a Windows app that extracts music from video and audio files:

- **Instrumental / stems** — removes the voice from any file, optionally splits into vocals,
  drums, bass and other.
- **Rebuild a track from several sources** — when the same music plays in several videos with
  narration in different places, every part of the track is taken from the file where it is
  cleanest; where all copies have a voice, they are fused per time-frequency bin.

Download `MusicExtractor-Setup-<version>.exe` from
[Releases](https://github.com/RiasJ1Dar/music-extractor/releases). The setup downloads ffmpeg,
Python 3.11, PyTorch (CUDA or CPU), Demucs, audio-separator and the models (~5 GB) and resumes
if interrupted. The interface is in Ukrainian; the installer is available in Ukrainian and English.

Command line (run from the app folder):

```
.venv\Scripts\python -m musicx.gui.app [FILE ...]                 # open the app with these files listed
.venv\Scripts\python -m musicx.core.models --download default|all  # fetch models in advance
powershell -ExecutionPolicy Bypass -File installer\deps.ps1 [-Cpu] [-AllModels] [-InstallDownloader] [-NoShortcut]
MusicExtractor-Setup-1.1.0.exe /VERYSILENT /TASKS="desktopicon,cpu,allmodels,downloader"
```

Output: `<name>_instrumental.wav` (+ `<name>_stems\`) or `clean_track.wav` + `clean_track_report.md`,
WAV 24-bit or FLAC. Models live in `%LOCALAPPDATA%\MusicExtractor\models`, the cache in
`%LOCALAPPDATA%\MusicExtractor\cache` (override with `MUSICX_CACHE`).
