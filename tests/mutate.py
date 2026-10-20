"""Mutation check: break one rule at a time in a fresh copy of the repo and make sure the golden
tests (tests/run.sh) or the listener tests go red.

    python3 tests/mutate.py            # every row KILLED, exit 0; SURVIVED / INVALID -> exit 1

INVALID means the original text was not found exactly once: the code moved on, update the row.
dialog.ps1 is not covered here; break it by hand and run tests/desktop.sh.
"""
import os
import shutil
import subprocess
import sys
import tempfile

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# (name, file, original text, broken text)
M = [
    ("awk: no tab bar", "dialog.awk", r'ask = trim(raw[s + 1]) ~ /^(☐|☒|✔)|^←.*→$/', r'ask = trim(raw[s + 1]) ~ /^(☐|☒|✔)/'),
    ("awk: no done button", "dialog.awk", 'if (multi) print "t.', 'if (0) print "t.'),
    ("awk: [ ] Type something a button", "dialog.awk", r'(\[[^]]*\] )?(Type something', r'(Type something'),
    ("awk: no review page", "dialog.awk", 'review = trim(raw[s + 2]) == "Review your answers"', 'review = 0'),
    ("awk: review lines glued", "dialog.awk", 'else if (review && opt == "" && t ~ /^(●|→)/)', 'else if (0)'),
    ("awk: tab bar not joined", "dialog.awk", 'gsub(/  +/, " · ", t)', 't = t'),
    ("awk: [tag] counts as a box", "dialog.awk", r'function boxed(t) { return t ~ /^[0-9]+\. \[( |✔)\] / }', r'function boxed(t) { return t ~ /^[0-9]+\. \[/ }'),
    ("awk: typed row a button", "dialog.awk", 'if (multi && navrow(t)) { keep[k] = 0; continue }', 'if (multi && navrow(t)) continue'),
    ("awk: typed row unmarked", "dialog.awk", 'if (!skip) desc = L("（你打的字）", "(what you typed)")', 'if (0) desc = ""'),
    ("awk: English ignored", "dialog.awk", 'function L(zh, en) { return lang == "en" ? en : zh }', 'function L(zh, en) { return zh }'),
    ("awk: English by default", "dialog.awk", 'function L(zh, en) { return lang == "en" ? en : zh }', 'function L(zh, en) { return lang == "zh" ? zh : en }'),
    ("listener: no cursor walk", "listener/listener.py", 'return move(cursor, to) + (("enter",) if option == "t" else (option,))', 'return (("enter",) if option == "t" else (option,))'),
    ("listener: walk on single choice", "listener/listener.py", '    if not multi_select(rows):\n        return (option,)\n    want', '    want'),
    ("listener: done sends Tab", "listener/listener.py", '(("enter",) if option == "t" else (option,))', '(("tab",) if option == "t" else (option,))'),
    ("listener: [tag] counts as a box", "listener/listener.py", r'BOX = re.compile(r"\[(?: |✔)\] ")', r'BOX = re.compile(r"\[")'),
    ("listener: second typing allowed", "listener/listener.py", 'if not rows[nav - 1][1].endswith("Type something"):', 'if False:'),
    ("listener: Enter after typing", "listener/listener.py", 'return Decision(True, keys=move(cursor, nav - 1), enter=False)', 'return Decision(True, keys=move(cursor, nav - 1))'),
    ("listener: old button edits", "listener/listener.py", 'return "changed", True', 'return "changed", False'),
    ("listener: language always zh", "listener/listener.py", 'return "zh-TW" if word in ("zh-TW", "zh") else "en"', 'return "zh-TW"'),
    ("listener: missing file not en", "listener/listener.py", '    except OSError:\n        return "en"', '    except OSError:\n        return "zh-TW"'),
    ("listener: render w/o config dir", "listener/listener.py", '"HERDR_PLUGIN_CONFIG_DIR": str(CONFIG_DIR or "")', '"HERDR_PLUGIN_CONFIG_DIR": ""'),
    ("listener: options ignore language", "listener/listener.py", '"-v", "part=options", "-v", f"lang={LANG}"', '"-v", "part=options"'),
    ("listener: unchanged = answered", "listener/listener.py", '    return "same"\n', '    return "done"\n'),
    ("listener: herdr timeout raises", "listener/listener.py", '        except subprocess.TimeoutExpired:\n            return None  # read', '        except ZeroDivisionError:\n            return None  # read'),
    ("listener: no redraw on change", "listener/listener.py", 'return "next" if dialog_options(screen) else "done"', 'return "done"'),
    ("listener: redraw w/o choices", "listener/listener.py", 'return "next" if dialog_options(screen) else "done"', 'return "next"'),
    ("listener: typed redraw + note", "listener/listener.py", '    note = follow_up(target, text, herdr, tg, chat_id, original["message_id"], typed=True)\n    if note is None:\n        return', '    note = follow_up(target, text, herdr, tg, chat_id, original["message_id"], typed=True)\n    if note is None:\n        pass'),
    ("listener: redraw w/o buttons", "listener/listener.py", '        if page and page[1]:', '        if page:'),
    ("listener: bad JSON raises", "listener/listener.py", '    try:\n        page = herdr.render(target)', '    page = herdr.render(target)\n    try:'),
    ("listener: edit_html no buttons", "listener/listener.py", 'parse_mode="HTML",\n                  reply_markup=markup)', 'parse_mode="HTML")'),
    ("listener: no pause", "listener/listener.py", 'STEP_READS, STEP_PAUSE = 5, 0.4', 'STEP_READS, STEP_PAUSE = 5, 0'),
    ("listener: 4 reads", "listener/listener.py", 'STEP_READS, STEP_PAUSE = 5, 0.4', 'STEP_READS, STEP_PAUSE = 4, 0.4'),
    ("listener: 1 read", "listener/listener.py", 'STEP_READS, STEP_PAUSE = 5, 0.4', 'STEP_READS, STEP_PAUSE = 1, 0.4'),
    ("listener: Cancel = answered", "listener/listener.py", '"Cancel": "cancelled"', '"Kancel": "cancelled"'),
    ("listener: untick = tick", "listener/listener.py", '"ticked" if m[1] == " " else "unticked"', '"ticked"'),
    ("listener: typed text trimmed", "listener/listener.py", 'done = t("sent", label) if typed else pressed(label)', 'done = pressed(label)'),
    ("listener: redrawn = answered", "listener/listener.py", '            tg.answer_callback(cq["id"], pressed(d.label))\n            return', '            tg.answer_callback(cq["id"], pressed(d.label))'),
    ("listener: rejected redraw raises", "listener/listener.py", 'except (urllib.error.URLError, OSError, ValueError):\n        pass', 'except ZeroDivisionError:\n        pass'),
    ("listener: no t in callback", "listener/listener.py", r'([0-9]{1,2}|t)', r'([0-9]{1,2})'),
    ("listener: label keeps box", "listener/listener.py", r'"^t\. |(?<=\. )\[[^]]*\] "', r'"^t\. "'),
    ("listener: unknown machine ok", "listener/listener.py", 'return m and m[1] in MACHINES and Target(', 'return m and Target('),
    ("listener: machines allows m", "listener/listener.py", r're.fullmatch(r"([a-ln-z])\s+', r're.fullmatch(r"([a-z])\s+'),
    ("listener: machines any letters", "listener/listener.py", r're.fullmatch(r"([a-ln-z])\s+', r're.fullmatch(r"(\S+)\s+'),
    ("notify.sh: no t", "notify.sh", '(?<n>[0-9]+|t)', '(?<n>[0-9]+)'),
    ("notify.sh: no --machine", "notify.sh", '"$herdr" ${NOTIFY_HERDR_MACHINE:+--machine "$NOTIFY_HERDR_MACHINE"} "$@"', '"$herdr" "$@"'),
    ("notify.sh: button shows t.", "notify.sh", 'text: sub("^t\\\\. "; "")', 'text: .'),
    ("notify.sh: letter always m", "notify.sh", 'a1|\\($m)|', 'a1|m|'),
    ("install.sh: old messages unread", "install.sh", '  api getUpdates -d offset=$((last + 1)) -d timeout=0 >/dev/null\n', ''),
    ("install.sh: settings world-readable", "install.sh", "(umask 077; printf", "(printf"),
    ("install.sh: chat id from wrong field", "install.sh", ".message.chat.id // empty", ".message.from.id // empty"),
    ("install.sh: test message skipped", "install.sh", "api sendMessage -d chat_id=", "false && api sendMessage -d chat_id="),
    ("notify.sh: fp in display words", "notify.sh", 'fp=$(printf \'%s\\n\' "$screen" | awk -f', 'fp=$(printf \'%s\\n\' "$screen" | awk -v lang="$lang" -f'),
    ("notify.sh: language ignored", "notify.sh", 'zh-TW | zh) lang=zh ;;', 'zh-TW | zh) lang=en ;;'),
    ("notify.sh: Chinese by default", "notify.sh", '  *) lang=en ;;', '  *) lang=zh ;;'),
    ("install.sh: Chinese by default", "install.sh", '*) answer=en ;;', '*) answer=zh-TW ;;'),
    ("notify.sh: render sends", "notify.sh", "if [ -n \"${NOTIFY_RENDER:-}\" ]; then printf '%s\\n' \"${markup:-}\"; html; exit 0; fi", ":"),
]


def run(cwd, cmd):
    # no mutation may reach Telegram (curl honours these; the token is empty in render mode anyway)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HTTPS_PROXY": "http://127.0.0.1:9",
           "https_proxy": "http://127.0.0.1:9"}
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, r.stdout + r.stderr


def main():
    rows, bad = [], 0
    for name, path, old, new in [("baseline (unchanged)", None, None, None)] + M:
        d = tempfile.mkdtemp(dir=sys.argv[1] if len(sys.argv) > 1 else None)
        shutil.copytree(SRC, os.path.join(d, "r"), ignore=shutil.ignore_patterns(".git", "__pycache__"))
        r = os.path.join(d, "r")
        if path:
            f = os.path.join(r, path)
            text = open(f, encoding="utf-8").read()
            if text.count(old) != 1:
                rows.append((name, f"INVALID (found {text.count(old)} times)")); bad += 1; continue
            open(f, "w", encoding="utf-8").write(text.replace(old, new))
        g, gout = run(r, "sh tests/run.sh")
        i, iout = run(r, "sh tests/install_test.sh")
        pytest = "uv run --no-project --with pytest pytest -q -p no:cacheprovider"
        p, pout = run(os.path.join(r, "listener"), pytest)
        if p not in (0, 1):  # uv itself exits 2 when it cannot reach the package index: try once more
            p, pout = run(os.path.join(r, "listener"), pytest)
        if p not in (0, 1):
            last = (pout.strip().splitlines() or [""])[-1][:80]
            res = f"INVALID (pytest exit {p}: {last})"
        elif path is None:
            res = "green" if g == 0 and i == 0 and p == 0 else f"baseline not green golden={g} install={i} pytest={p}"
        else:
            caught = g != 0 or i != 0 or (p == 1 and "FAILED" in pout)
            res = "KILLED" if caught else "SURVIVED"
        if res not in ("green", "KILLED"):
            bad += 1
        rows.append((name, f"{res}  golden={g} install={i} pytest={p}"))
        shutil.rmtree(d)
    for n, r in rows:
        print(f"{n:<34} {r}")
    print("reached the end")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
