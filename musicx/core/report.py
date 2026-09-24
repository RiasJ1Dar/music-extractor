"""report.md for a rebuilt track."""
from datetime import datetime


def _fmt_t(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def _runs(res):
    """consecutive steps with the same method / source / alignment -> table rows."""
    grid, path, fused = res["grid"], res["path"], set(res["fused_steps"])
    step = res["params"]["step"]; lead = res["lead_trim"]
    rows = []
    for i, (g, p) in enumerate(zip(grid, path)):
        m = "fused" if i in fused else "copy"
        key = (m, p["src"] if m == "copy" else None, round(p["at"] - g["t"], 2) if m == "copy" else None, bool(g["quiet"]))
        ok = [c for c in g["cands"] if c["melody_ok"]]
        if rows and rows[-1]["key"] == key:
            r = rows[-1]; r["e"] = g["t"]; r["leak"] = max(r["leak"], p["leak"])
            r["n"] = (min(r["n"][0], len(ok)), max(r["n"][1], len(ok))); r["srcs"] |= {c["src"] for c in ok}
        else:
            rows.append({"key": key, "s": g["t"], "e": g["t"], "at": p["at"], "leak": p["leak"],
                         "n": (len(ok), len(ok)), "srcs": {c["src"] for c in ok}})
    out = []
    for r in rows:
        m, src, off, q = r["key"]
        t0 = max(0.0, r["s"] - step / 2 - lead); t1 = r["e"] + step / 2 - lead
        if t1 <= 0: continue
        if m == "copy":
            what = f"{src} {r['at'] - step / 2:.2f}–{r['at'] + (r['e'] - r['s']) + step / 2:.2f} с"
            how = "копія" + (" (стоп)" if q else "")
        else:
            what = "злиття: " + ", ".join(sorted(r["srcs"]))
            how = f"злиття {r['n'][0]}–{r['n'][1]} копій" + (" (стоп, мінімум)" if q else " (медіана)")
        out.append((t0, t1, what, how, r["leak"], m == "fused" and r["n"][1] == 2 and not q))
    return out


def write_report(path, res, duration, out_file):
    step = res["params"]["step"]
    steps = len(res["path"])
    fused = len(res["fused_steps"])
    by_src = {}
    for i, p in enumerate(res["path"]):
        if i not in set(res["fused_steps"]): by_src[p["src"]] = by_src.get(p["src"], 0) + 1
    L = [f"# Відновлений трек: звіт\n",
         f"Створено {datetime.now():%Y-%m-%d %H:%M}. Файл: `{out_file}`, **{duration:.2f} с** ({_fmt_t(duration)}), 44.1 kHz stereo.\n"]
    if res["coverage"] < 0.2:
        L.append(f"> ⚠️ **Джерела майже не збігаються**: лише {res['coverage']*100:.0f}% кроків мають копію з іншого "
                 "джерела. Ймовірно, у файлах звучать різні треки — результат майже повністю взято зі скелета "
                 "(фактично це мінус одного файлу).\n")
    L.append("## Джерела\n")
    L.append("| Назва | Файл | Тривалість | Бітрейт | Зріз кодека | Штраф | Гучність |\n|---|---|---|---|---|---|---|")
    import math
    for s in res["sources"]:
        g = res["G"].get(s["name"], 1.0)
        br = f"{s['bitrate'] // 1000} kbps" if s.get("bitrate") else "—"
        L.append(f"| {s['name']}{' (скелет)' if s['name'] == res['skeleton'] else ''} | {s.get('file', '')} | "
                 f"{s.get('duration', 0):.1f} с | {br} | {s.get('cutoff', 0) / 1000:.1f} кГц | {s['penalty']:.2f} | "
                 f"{20 * math.log10(g):+.1f} дБ |")
    L.append("\n## Підсумок\n")
    L.append(f"- Скелет таймлайну: **{res['skeleton']}** (найдовше джерело); його паузи-стопи збережено.")
    L.append(f"- Кроків по {step} с: {steps}. Копія одного джерела: {steps - fused} "
             f"({', '.join(f'{n}: {k}' for n, k in sorted(by_src.items(), key=lambda x: -x[1]))}); злиття кількох копій: {fused}.")
    L.append(f"- Покриття іншими джерелами: {res['coverage']*100:.0f}% кроків.\n")
    rows = _runs(res)
    L.append("## Проблемні ділянки\n")
    L.append("Голос може лишитись ледь чутним: є лише одна копія правильної фрази і біля неї звучав голос "
             "(`leak` > 0.5), або злиття лише двох копій.\n")
    prob = [r for r in rows if (r[3].startswith("копія") and r[4] > 0.5) or r[5]]
    if prob:
        L.append("| Час, с | Що там | leak |\n|---|---|---|")
        for t0, t1, what, how, leak, _ in prob:
            L.append(f"| {t0:.2f}–{t1:.2f} | {what}, {how} | {leak:.2f} |")
    else:
        L.append("Немає.")
    L.append("\n## Сегменти\n")
    L.append("`leak`: скільки голосу звучало біля обраної копії у вихідному файлі (0 = немає, 1 ≈ голос на рівні музики).\n")
    L.append("| Час у треку, с | Джерело | Метод | leak |\n|---|---|---|---|")
    for t0, t1, what, how, leak, _ in rows:
        L.append(f"| {t0:.2f}–{min(t1, duration):.2f} | {what} | {how} | {leak:.2f} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
