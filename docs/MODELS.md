**Українська** · моделі розділення в Music Extractor

# Моделі

Програма пропонує 11 моделей і один ансамбль. Усі завантажуються самі (установником або при першому
використанні) у `%LOCALAPPDATA%\MusicExtractor\models`; через [Downloader](https://github.com/RiasJ1Dar/downloader),
якщо він встановлений.

| Ключ | Модель | Сімейство | Файл | Розмір | Стеми |
|---|---|---|---|---:|---|
| `bs_roformer` | BS-RoFormer 1297 (viperx) | RoFormer | `model_bs_roformer_ep_317_sdr_12.9755.ckpt` | 610 МБ | голос / мінус |
| `melband_kim` | Mel-Band RoFormer (Kimberley Jensen) | RoFormer | `vocals_mel_band_roformer.ckpt` | 871 МБ | голос / мінус |
| `melband_inst_v2` | Mel-Band RoFormer Inst V2 (unwa) | RoFormer | `melband_roformer_inst_v2.ckpt` | 1502 МБ | голос / мінус |
| `melband_inst_becruily` | Mel-Band RoFormer Instrumental (becruily) | RoFormer | `mel_band_roformer_instrumental_becruily.ckpt` | 871 МБ | голос / мінус |
| `mdx23c` | MDX23C InstVoc HQ | MDX23C | `MDX23C-8KFFT-InstVoc_HQ.ckpt` | 427 МБ | голос / мінус |
| `mdx_inst_hq4` | UVR-MDX-NET Inst HQ4 | MDX-Net (ONNX) | `UVR-MDX-NET-Inst_HQ_4.onnx` | 56 МБ | голос / мінус |
| `htdemucs` | Demucs htdemucs | Demucs v4 | 1 файл | 80 МБ | голос, барабани, бас, інше |
| `htdemucs_ft` | Demucs htdemucs_ft (fine-tuned) | Demucs v4 | 4 файли | 321 МБ | голос, барабани, бас, інше |
| `htdemucs_6s` | Demucs htdemucs_6s | Demucs v4 | 1 файл | 52 МБ | + гітара, фортепіано |
| `hdemucs_mmi` | Demucs hdemucs_mmi | Demucs v3 | 1 файл | 160 МБ | голос, барабани, бас, інше |
| `mdx_extra` | Demucs mdx_extra | Demucs v3 | 4 файли | 639 МБ | голос, барабани, бас, інше |
| `ens_bs_kim` | Ансамбль BS-RoFormer + Mel-Band Kim | — | обидві моделі | — | голос / мінус |

Для моделей із двома стемами барабани / бас / інше отримуються розкладанням чистого мінусу через `htdemucs_ft`.

## Замір 1: мінус одного файлу (з відомим результатом)

Чистий трек змішано з мовою; SDR мінусу проти оригінальної музики, дБ (більше = краще). «Синтезована» —
Windows TTS, «живий» — справжній диктор. Час — на 48-секундний фрагмент, RTX 2060.

| Модель | Синтезована | Живий | Час |
|---|---:|---:|---:|
| BS-RoFormer 1297 | **21.9** | 19.2 | ~70–100 с |
| Ансамбль BS-RoFormer + Kim | 21.2 | **19.6** | ~85–115 с |
| Mel-Band RoFormer (Kim) | 18.9 | 19.4 | ~14 с |
| Mel-Band RoFormer Inst V2 | 18.7 | 18.9 | ~48–167 с |
| Mel-Band RoFormer Instrumental (becruily) | 18.6 | 18.7 | ~18 с |
| UVR-MDX-NET Inst HQ4 | 17.8 | 16.2 | ~6–19 с |
| MDX23C InstVoc HQ | 14.0 | 18.8 | ~41 с |
| Demucs htdemucs | 6.5 | 18.3 | ~12–45 с |
| Demucs mdx_extra | 6.3 | 17.4 | ~20–150 с |
| Demucs hdemucs_mmi | 6.0 | 17.0 | ~8–41 с |
| Demucs htdemucs_ft | 6.5 | 15.9 | ~33–37 с |
| Demucs htdemucs_6s | 1.7 | 16.9 | ~5–18 с |

## Замір 2: відновлення треку з кількох відео (режим B)

Той самий трек, відновлений з 4 реальних відео з диктором кожною моделлю. Еталона немає, тому голос, що
лишився, оцінюють три моделі-«судді» (htdemucs_ft, Mel-Band Kim, BS-RoFormer); суддя ніколи не оцінює власну
модель. Ранг — середнє місце за суддями (менше = краще); «інша фраза» — частка часу, коли мелодія не збігається
з вихідним відео (5–12 % — фон методу).

| Місце | Модель | Середній ранг | Інша фраза | Час прогону |
|---:|---|---:|---:|---:|
| 1 | **Demucs htdemucs_ft** (за замовчуванням для режиму B) | 2.0 | 9 % | 5 хв |
| 2 | Demucs htdemucs_6s | 4.0 | 28 % ⚠️ | 3 хв |
| 3 | Mel-Band RoFormer Instrumental (becruily) | 4.3 | 10 % | 8 хв |
| 4 | MDX23C InstVoc HQ | 5.3 | 11 % | 10 хв |
| 5 | Demucs mdx_extra | 6.0 | 5 % | 4 хв |
| 6 | Demucs htdemucs | 6.3 | 10 % | 3 хв |
| 7 | Demucs hdemucs_mmi | 8.0 | 12 % | 3 хв |
| 8 | Mel-Band RoFormer Inst V2 | 9.0 | 9 % | 112 хв ⚠️ |
| 9 | Mel-Band RoFormer (Kim) | 10.0 | 9 % | 7 хв |
| 10 | Ансамбль BS-RoFormer + Kim | 10.0 | 9 % | 16 хв |
| 11 | UVR-MDX-NET Inst HQ4 | 10.3 | 7 % | 6 хв |
| 12 | BS-RoFormer 1297 | 12.0 | 11 % | 15 хв |

Моделі RoFormer, найкращі на заміри 1, у режимі B опинились унизу: у паузах музики, де голос диктора звучить
сам, вони лишають його в мінусі (до −14 дБ проти −28…−63 дБ у htdemucs_ft). Mel-Band Inst V2 на відеокарті з
6 ГБ пам'яті працює в десятки разів повільніше за інші.

## Що обрати

- **Мінус одного файлу:** за замовчуванням BS-RoFormer; якщо в записі є паузи музики з голосом — спробуйте
  Demucs htdemucs_ft. Швидкий варіант — Mel-Band RoFormer (Kim).
- **Відновлення з кількох відео:** Demucs htdemucs_ft.
- **Стеми (барабани, бас):** будь-яка модель; для гітари та фортепіано окремо — htdemucs_6s.

Моделі належать їхнім авторам і мають власні ліцензії: Demucs — [facebookresearch/demucs](https://github.com/facebookresearch/demucs)
(MIT), решта — через [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator) з репозиторіїв
UVR та авторів моделей.
