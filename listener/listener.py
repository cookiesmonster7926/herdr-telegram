#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Turns taps on the notification buttons into key presses for the blocked agent.

Long-polls the bot (getUpdates), so nothing listens on a port. Only the owner's taps count,
and a key is pressed only if the agent is still blocked on the very dialog the notification
showed (same fingerprint) and the tapped option is one that may be a button at all.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIALOG_AWK = ROOT / "dialog.awk"
NOTIFY_SH = ROOT / "notify.sh"
PLUGIN_ID = "herdr-telegram"
# the machine letter in a button -> extra herdr arguments to reach that machine's server;
# "m" is this Mac, others come from the `machines` file in the plugin's config directory
MACHINES = {"m": []}
# option: a number key, or "t" for "done with this multi-select question"
CALLBACK = re.compile(r"a1\|([a-z])\|([A-Za-z0-9]+:[A-Za-z0-9]+)\|([0-9]{1,2}|t)\|([0-9a-f]{8})")
# after a key the agent may keep asking (the next question, a ticked box, the review page) and
# stays blocked throughout, so no new notification comes (measured: one networked plugin run for
# a whole two-question round in `herdr plugin log list`). herdr's reading of the screen may lag
# behind the key (a guess), so read up to 5 times, 0.4 s apart, before calling the screen unchanged
STEP_READS, STEP_PAUSE = 5, 0.4
# set by main() from the plugin config directory; notify.sh reads the same `language` file there
CONFIG_DIR = None
LANG = "en"
# what the listener says, per language ({x}: a button label or typed text)
MESSAGES = {
    "zh-TW": {
        "gone": "agent 已經不在等你", "unreadable": "讀不到畫面", "changed": "畫面已經變了",
        "not_a_button": "這個選項不能從手機按", "no_cursor": "看不出游標在哪，請到電腦上操作",
        "typed_once": "這題已經打過字了，要改請到電腦上", "no_typing": "這個問題不能打字回答，請用按鈕",
        "ticked": "已勾：{x}", "unticked": "已取消勾選：{x}", "pressed": "已按：{x}",
        "submitted": "已送出答案", "cancelled": "已取消，沒有送出答案", "answered": "已回答：{x}",
        "sent": "已送出：{x}", "unchanged": "{x}；畫面還沒變，請到電腦上確認",
        "see_computer": "{x}；下一步請到電腦上看", "not_sent": "沒送出：{x}",
        "bad_button": "看不懂這顆按鈕", "already": "這則已經回答過了",
        "how_to_reply": "要回答 agent，請對那則通知按「回覆」再打字。",
    },
    "en": {
        "gone": "the agent is no longer waiting", "unreadable": "could not read the screen",
        "changed": "the screen has changed", "not_a_button": "this option can't be pressed from the phone",
        "no_cursor": "can't tell where the cursor is; use the computer",
        "typed_once": "text was already typed here; change it on the computer",
        "no_typing": "this question takes no typed answer; use the buttons",
        "ticked": "Ticked: {x}", "unticked": "Unticked: {x}", "pressed": "Pressed: {x}",
        "submitted": "Answers submitted", "cancelled": "Cancelled; no answers sent", "answered": "Answered: {x}",
        "sent": "Sent: {x}", "unchanged": "{x}; the screen hasn't changed yet, check on the computer",
        "see_computer": "{x}; see the next step on the computer", "not_sent": "Not sent: {x}",
        "bad_button": "unknown button", "already": "already answered",
        "how_to_reply": "To answer an agent, reply to its notification.",
    },
}


def t(key, x=""):
    return MESSAGES[LANG][key].replace("{x}", x)


def read_language(config_dir):
    """The `language` file: "zh-TW" (or "zh") for Traditional Chinese, anything else English."""
    try:
        word = (Path(config_dir) / "language").read_text(encoding="utf-8").strip()
    except OSError:
        return "en"
    return "zh-TW" if word in ("zh-TW", "zh") else "en"


@dataclass(frozen=True)
class Target:
    machine: str
    pane: str
    option: str
    fp: str


@dataclass(frozen=True)
class Decision:
    send: bool
    keys: tuple = ()
    label: str = ""
    reason: str = ""
    enter: bool = True  # a typed answer: Enter after the text
    keep: bool = False  # a refusal: leave the message as it is (it may already show a newer screen)


def parse_machines(text):
    """The `machines` file: one "<letter> <herdr machine name>" per line, e.g. "w lab-pc"; the letter
    is what that machine's plugin puts in its buttons (notify.ps1 uses w unless told otherwise)."""
    machines = {"m": []}
    for line in (text or "").splitlines():
        if m := re.fullmatch(r"([a-ln-z])\s+(\S(?:.*\S)?)", line.strip()):
            machines[m[1]] = ["--machine", m[2]]
    return machines


def parse_callback(data):
    m = CALLBACK.fullmatch(data or "")
    return m and m[1] in MACHINES and Target(machine=m[1], pane=m[2], option=m[3], fp=m[4]) or None


def _awk(screen, *args):
    return subprocess.run(["awk", *args, "-f", str(DIALOG_AWK)], input=screen, capture_output=True,
                          text=True, check=True).stdout


def format_dialog(screen):
    return _awk(screen)


def dialog_options(screen):
    # worded in LANG (only "t." has words of its own); fingerprints use format_dialog's default
    return [line for line in _awk(screen, "-v", "part=options", "-v", f"lang={LANG}").splitlines() if line]


def fingerprint(dialog):
    # same definition as notify.sh / Get-Fingerprint in dialog.ps1
    return hashlib.md5(dialog.rstrip("\n").encode()).hexdigest()[:8]


def stale(target, status, screen):
    """Why the agent is no longer waiting on the dialog the notification showed (and whether the
    message should stay as it is), or None."""
    if status != "blocked":
        return "gone", False
    if screen is None:
        return "unreadable", True
    if fingerprint(format_dialog(screen)) != target.fp:
        # a button from before a redraw: the message already shows the newer screen
        return "changed", True
    return None


# Rows of a question below its tab bar: "1. [ ] 蘋果" ... "4. [ ] Type something", then an
# unnumbered "Submit" ("Next" when more questions follow), then "5. Chat about this"; "❯" marks
# the cursor. In a multi-select question a number key ticks its box, but typed while the cursor
# sits in the free-text row it becomes text, and there Tab only moves the cursor (measured with tests/capture.py)
TAB_BAR = re.compile(r"^\s*←.*→\s*$")
ROW = re.compile(r"^\s*(❯)?\s*(?:([0-9]+)\. (.*?)|(Submit|Next))\s*$")
BOX = re.compile(r"\[(?: |✔)\] ")
NAV = ("Submit", "Next")


def layout(screen):
    """([(number or "Submit"/"Next", text), ...] top to bottom, index of the cursor's row or None)."""
    lines = (screen or "").replace("\xa0", " ").splitlines()
    bars = [i for i, line in enumerate(lines) if TAB_BAR.match(line)]
    rows, cursor = [], None
    for line in lines[bars[-1] + 1:] if bars else []:
        if m := ROW.match(line):
            if m[1]:
                cursor = len(rows)
            rows.append((m[2], m[3]) if m[2] else (m[4], ""))
    return rows, cursor


def multi_select(rows):
    return any(BOX.match(text) for row, text in rows if row not in NAV)


def move(cursor, to):
    return ("down",) * (to - cursor) if to > cursor else ("up",) * (cursor - to)


def press(option, screen):
    """The keys for a tap on `option`: the number alone on a single-choice question; on a
    multi-select one, the cursor first goes to that row (to "Submit"/"Next" plus Enter for "t").
    None if the cursor or the row is not on screen."""
    rows, cursor = layout(screen)
    if not multi_select(rows):
        return (option,)
    want = NAV if option == "t" else (option,)
    to = next((i for i, (row, _) in enumerate(rows) if row in want), None)
    if cursor is None or to is None:
        return None
    return move(cursor, to) + (("enter",) if option == "t" else (option,))


def decide(target, status, screen):
    if refused := stale(target, status, screen):
        return Decision(False, reason=t(refused[0]), keep=refused[1])
    label = next((o for o in dialog_options(screen) if o.startswith(f"{target.option}. ")), None)
    if label is None:
        return Decision(False, reason=t("not_a_button"))
    keys = press(target.option, screen)
    if keys is None:
        return Decision(False, reason=t("no_cursor"), keep=True)
    return Decision(True, keys=keys, label=label)


def short_label(label):
    # "2. [ ] 香蕉" -> "2. 香蕉": the box shows the state before the tap, not after
    return re.sub(r"^t\. |(?<=\. )\[[^]]*\] ", "", label)


def after_key(target, herdr):
    """What the agent does after a key: "next" (still blocked on choices, now different ones),
    "done" (not blocked, or no choices on screen), or "same" (screen unchanged for a while)."""
    for _ in range(STEP_READS):
        time.sleep(STEP_PAUSE)
        status, screen = herdr.status(target), herdr.screen(target)
        if status != "blocked" or screen is None:
            return "done"
        if fingerprint(format_dialog(screen)) != target.fp:
            return "next" if dialog_options(screen) else "done"
    return "same"


def pressed(label):
    """What a tap on a button did, in words: a box ticks or unticks, anything else is pressed."""
    if m := re.match(r"[0-9]+\. \[( |✔)\] ", label):
        return t("ticked" if m[1] == " " else "unticked", short_label(label))
    return t("pressed", short_label(label))


def answered_note(label):
    # the review page's two buttons end the questions in opposite ways
    end = {"Submit answers": "submitted", "Cancel": "cancelled"}.get(re.sub(r"^[0-9]+\. ", "", label))
    return t(end) if end else t("answered", label)


def follow_up(target, label, herdr, tg, chat_id, message_id, typed=False):
    """Redraws the notification while the agent keeps asking and returns None; otherwise returns
    the note to append to it (and its buttons go). label: the button's, or the typed text."""
    state = after_key(target, herdr)
    if state == "done":
        return t("answered", label) if typed else answered_note(label)
    done = t("sent", label) if typed else pressed(label)
    if state == "same":
        return t("unchanged", done)
    try:
        page = herdr.render(target)
        if page and page[1]:
            tg.edit_html(chat_id, message_id, *page)
            return None
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return t("see_computer", done)


TYPE_OPTION = re.compile(r"^\s*(?:❯\s*)?([0-9]+)\. Type something", re.M)


def type_option(screen):
    m = TYPE_OPTION.search(screen or "")
    return m and int(m[1])


def clean_text(text):
    # one line only: a newline would reach the agent as an early Enter
    return " ".join((text or "").split())[:500]


def decide_text(target, status, screen):
    if refused := stale(target, status, screen):
        return Decision(False, reason=t(refused[0]))
    rows, cursor = layout(screen)
    if multi_select(rows):
        # type straight into the free-text row (its box ticks itself); no Enter, so the question
        # stays open for more boxes
        nav = next((i for i, (row, _) in enumerate(rows) if row in NAV), None)
        if cursor is None or not nav:
            return Decision(False, reason=t("no_cursor"))
        if not rows[nav - 1][1].endswith("Type something"):
            return Decision(False, reason=t("typed_once"))
        return Decision(True, keys=move(cursor, nav - 1), enter=False)
    n = type_option(screen)
    if n is None:
        return Decision(False, reason=t("no_typing"))
    return Decision(True, keys=(str(n),))


def handle_update(update, owner_id, herdr, tg, answered=None):
    # answered: notifications already acted on, as (chat id, message id). The dialog can still be
    # on screen for a moment after the first key, so a second tap would pass every other check.
    answered = set() if answered is None else answered
    if "message" in update:
        return handle_reply(update["message"], owner_id, herdr, tg, answered)
    cq = update.get("callback_query")
    if not cq or cq.get("from", {}).get("id") != owner_id:
        return
    msg = cq.get("message") or {}
    target = parse_callback(cq.get("data"))
    if target is None:
        tg.answer_callback(cq["id"], t("bad_button"))
        return
    key = (msg.get("chat", {}).get("id"), msg.get("message_id"))
    if key in answered:
        tg.answer_callback(cq["id"], t("already"))
        return
    d = decide(target, herdr.status(target), herdr.screen(target))
    if d.send:
        herdr.send_keys(target, *d.keys)
        note = follow_up(target, d.label, herdr, tg, *key)
        if note is None:
            # redrawn with new buttons for the new screen; this message is not done yet
            tg.answer_callback(cq["id"], pressed(d.label))
            return
        answered.add(key)
    else:
        note = t("not_sent", d.reason)
    tg.answer_callback(cq["id"], note)
    if d.keep:
        return
    if msg.get("message_id"):
        # append to the original text; entities keep their offsets, so the formatting survives
        tg.edit_message(msg["chat"]["id"], msg["message_id"], f"{msg.get('text', '')}\n\n{note}",
                        msg.get("entities", []))


def handle_reply(msg, owner_id, herdr, tg, answered):
    if msg.get("from", {}).get("id") != owner_id:
        return
    chat_id, original = msg["chat"]["id"], msg.get("reply_to_message") or {}
    if (chat_id, original.get("message_id")) in answered:
        tg.send_message(chat_id, t("already"), msg.get("message_id"))
        return
    # the notification's own buttons say which agent and which dialog it was about
    rows = (original.get("reply_markup") or {}).get("inline_keyboard") or [[{}]]
    target = parse_callback(rows[0][0].get("callback_data"))
    text = clean_text(msg.get("text"))
    if target is None or not text:
        tg.send_message(chat_id, t("how_to_reply"), msg.get("message_id"))
        return
    d = decide_text(target, herdr.status(target), herdr.screen(target))
    if not d.send:
        tg.send_message(chat_id, t("not_sent", d.reason), msg.get("message_id"))
        return
    if d.keys:
        herdr.send_keys(target, *d.keys)
    herdr.send_text(target, text)
    if d.enter:
        herdr.send_keys(target, "enter")
    note = follow_up(target, text, herdr, tg, chat_id, original["message_id"], typed=True)
    if note is None:
        return
    answered.add((chat_id, original["message_id"]))
    tg.edit_message(chat_id, original["message_id"], f"{original.get('text', '')}\n\n{note}",
                    original.get("entities", []))


class Herdr:
    def _run(self, target, *args):
        try:
            r = subprocess.run(["herdr", *MACHINES[target.machine], *args], capture_output=True, text=True,
                               timeout=20)
        except subprocess.TimeoutExpired:
            return None  # read as "could not tell"; the callers already handle None
        return r.stdout if r.returncode == 0 else None

    def status(self, target):
        out = self._run(target, "agent", "get", target.pane)
        return out and json.loads(out)["result"]["agent"]["agent_status"]

    def screen(self, target):
        return self._run(target, "agent", "read", target.pane, "--source", "visible")

    def send_keys(self, target, *keys):
        self._run(target, "agent", "send-keys", target.pane, *keys)

    def send_text(self, target, text):
        # no "--": herdr would type it literally, and it already reads a leading "-" in <TEXT> as text
        self._run(target, "pane", "send-text", target.pane, text)

    def render(self, target):
        """(HTML, reply markup) for the agent's current dialog, exactly as notify.sh would send it;
        None if the agent is no longer blocked."""
        extra = MACHINES[target.machine]
        env = {**os.environ, "NOTIFY_RENDER": "1", "HERDR_PANE_ID": target.pane,
               "NOTIFY_LETTER": target.machine, "NOTIFY_HERDR_MACHINE": extra[1] if extra else "",
               "HERDR_PLUGIN_CONFIG_DIR": str(CONFIG_DIR or "")}
        try:
            r = subprocess.run(["sh", str(NOTIFY_SH)], env=env, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0 or not r.stdout.strip():
            return None
        markup, _, html = r.stdout.partition("\n")
        return html.rstrip("\n"), json.loads(markup) if markup else None


class Telegram:
    def __init__(self, token):
        self._token = token

    # http_timeout bounds the HTTP request; a "timeout" in params is getUpdates' long-poll length
    def call(self, method, http_timeout=15, **params):
        req = urllib.request.Request(f"https://api.telegram.org/bot{self._token}/{method}",
                                     data=json.dumps(params).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=http_timeout) as r:
            return json.load(r)

    def answer_callback(self, callback_id, text):
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def send_message(self, chat_id, text, reply_to):
        self.call("sendMessage", chat_id=chat_id, text=text, reply_parameters={"message_id": reply_to})

    def edit_message(self, chat_id, message_id, text, entities):
        # no reply_markup: the buttons go away
        self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text, entities=entities)

    def edit_html(self, chat_id, message_id, html, markup):
        self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=html, parse_mode="HTML",
                  reply_markup=markup)


def log(token, *parts):
    # never let the token reach the log, whatever an exception message contains
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *(str(p).replace(token, "***") for p in parts), flush=True)


def main():
    global MACHINES, CONFIG_DIR, LANG
    config = Path(subprocess.run(["herdr", "plugin", "config-dir", PLUGIN_ID], capture_output=True, text=True,
                                 check=True, timeout=30).stdout.strip())
    token, chat = (line.strip() for line in (config / "telegram").read_text(encoding="utf-8").splitlines()[:2])
    if (config / "machines").exists():
        MACHINES = parse_machines((config / "machines").read_text(encoding="utf-8"))
    CONFIG_DIR, LANG = config, read_language(config)
    tg, herdr, offset, answered = Telegram(token), Herdr(), None, set()
    # launchd starts us with a bare environment (no login shell, no ssh agent); say up front
    # whether every machine's herdr is reachable
    for letter, extra in MACHINES.items():
        try:
            r = subprocess.run(["herdr", *extra, "agent", "list"], capture_output=True, text=True, timeout=30)
            agents = json.loads(r.stdout)["result"]["agents"] if r.returncode == 0 else None
            log(token, f"herdr[{letter}] ok: {len(agents)} agents" if agents is not None
                else f"herdr[{letter}] failed: {r.stderr[:200]}")
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError) as e:
            log(token, f"herdr[{letter}] unreachable:", repr(e))
    log(token, "listening")
    while True:
        try:
            params = {"timeout": 50, "allowed_updates": ["callback_query", "message"]}
            if offset is not None:
                params["offset"] = offset
            updates = tg.call("getUpdates", http_timeout=60, **params).get("result", [])
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            log(token, "getUpdates failed:", e)
            time.sleep(10)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                handle_update(u, int(chat), herdr, tg, answered)
                if "callback_query" in u:
                    log(token, "callback", u["callback_query"].get("data"))
            except Exception as e:  # one bad update must not stop the loop
                log(token, "update", u.get("update_id"), "failed:", repr(e))


if __name__ == "__main__":
    sys.exit(main())
