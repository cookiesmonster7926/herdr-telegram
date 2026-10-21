import io
import json
import os
import stat
from pathlib import Path

import pytest

import listener as L

FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OWNER = 123456789
REMOTE = "lab-pc"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    # after_key() pauses between reads of the screen; the fakes answer at once
    monkeypatch.setattr(L.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def machines(monkeypatch):
    # this Mac, plus one remote herdr machine reached as "w" (what a `machines` file would say)
    monkeypatch.setattr(L, "MACHINES", {"m": [], "w": ["--machine", REMOTE]})


@pytest.fixture(autouse=True)
def config(monkeypatch, tmp_path):
    # the plugin config directory; the tests below read the Chinese wording unless they switch
    d = tmp_path / "config"
    d.mkdir()
    (d / "language").write_text("zh-TW\n", encoding="utf-8")
    monkeypatch.setattr(L, "CONFIG_DIR", d)
    monkeypatch.setattr(L, "LANG", "zh-TW")
    return d


# --- language ---------------------------------------------------------------------------

def test_both_languages_have_every_message_with_the_same_blanks():
    zh, en = L.MESSAGES["zh-TW"], L.MESSAGES["en"]
    assert zh.keys() == en.keys()
    assert all(("{x}" in zh[k]) == ("{x}" in en[k]) for k in zh)


@pytest.mark.parametrize("text, lang", [("zh-TW\n", "zh-TW"), ("zh", "zh-TW"), ("en", "en"), ("", "en"),
                                        ("klingon", "en"), (None, "en")])
def test_read_language_defaults_to_english(tmp_path, text, lang):
    if text is not None:
        (tmp_path / "language").write_text(text, encoding="utf-8")
    assert L.read_language(tmp_path) == lang


def test_the_done_button_is_named_in_the_language(monkeypatch):
    monkeypatch.setattr(L, "LANG", "en")
    h = FakeHerdr(screen_text=screen("multi_select"), after=[screen("multi_review")])
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|t|{fp('multi_select')}"), OWNER, h, tg)
    assert ("answer", "cb1", "Pressed: Done with this question →") in tg.calls


def test_notes_follow_the_language(monkeypatch):
    monkeypatch.setattr(L, "LANG", "en")
    h = FakeHerdr(screen_text=screen("multi_review"), after=[screen("generic")], status_after="working")
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|2|{fp('multi_review')}"), OWNER, h, tg)
    assert "Cancelled" in next(c for c in tg.calls if c[0] == "edit")[3]
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('choice_wide')}"), OWNER, FakeHerdr(screen_text=screen("perm")), tg)
    assert tg.calls == [("answer", "cb1", "Not sent: the screen has changed")]


# --- machines file --------------------------------------------------------------------

def test_parse_machines_reads_letter_and_herdr_machine_name():
    text = "# remote herdr machines\nw lab-pc\n\nx  my desk box \n"
    assert L.parse_machines(text) == {"m": [], "w": ["--machine", "lab-pc"], "x": ["--machine", "my desk box"]}


@pytest.mark.parametrize("line", ["m other-mac", "W lab-pc", "ww lab-pc", "w", "1 lab-pc"])
def test_parse_machines_skips_lines_it_cannot_use(line):
    # "m" is always this Mac; a letter is one lower-case a-z
    assert L.parse_machines(line) == {"m": []}


def test_a_button_for_a_machine_not_in_the_file_is_unreadable():
    assert L.parse_callback("a1|q|w6:p1|3|4dcd4882") is None


def screen(name):
    return (FIX / f"{name}.txt").read_text(encoding="utf-8")


def fp(name):
    return (FIX / f"{name}.fp").read_text(encoding="utf-8").strip()


# --- parse_callback -------------------------------------------------------------------

def test_parse_callback_reads_the_button_format():
    t = L.parse_callback("a1|w|w6:p1|3|4dcd4882")
    assert t == L.Target(machine="w", pane="w6:p1", option="3", fp="4dcd4882")


def test_parse_callback_reads_the_tab_button():
    assert L.parse_callback("a1|m|wC:pE|t|17631fe8").option == "t"


@pytest.mark.parametrize("data", [
    "a1|x|w6:p1|3|4dcd4882",          # unknown machine
    "a1|m|w6:p1|tab|4dcd4882",
    "a1|m|w6:p1|enter|4dcd4882",
    "a1|m|w6:p1;rm -rf|3|4dcd4882",   # pane id with shell junk
    "a1|m|-v|3|4dcd4882",             # pane id that looks like a flag
    "a1|m|w6:p1|three|4dcd4882",
    "a1|m|w6:p1|3|4DCD4882",
    "a2|m|w6:p1|3|4dcd4882",
    "",
])
def test_parse_callback_rejects_anything_else(data):
    assert L.parse_callback(data) is None


# --- fingerprint / dialog: must agree with notify.sh and notify.ps1 -------------------

@pytest.mark.parametrize("name", ["perm", "perm_always", "choice_wide", "choice_narrow", "generic",
                                  "perm_numbered", "choice_footer", "multi_q1", "multi_select",
                                  "multi_review", "multi_typed", "select_single"])
def test_fingerprint_matches_what_the_notify_scripts_send(name):
    assert L.fingerprint(L.format_dialog(screen(name))) == fp(name)


# --- decide ---------------------------------------------------------------------------

def target(name, option, machine="m"):
    return L.Target(machine=machine, pane="wC:pE", option=str(option), fp=fp(name))


def test_decide_moves_on_from_a_multi_select_question_with_enter_on_its_submit_row():
    # Tab would do, but not while the cursor is in the free-text row: there it only moves the
    # cursor down; Enter on "Submit"/"Next" works from anywhere (measured, tests/capture.py)
    d = L.decide(target("multi_select", "t"), "blocked", screen("multi_select"))
    assert (d.send, d.keys, d.label) == (True, ("down",) * 4 + ("enter",), "t. 這題選好了 →")


def test_decide_moves_up_to_a_next_row_below_the_cursor():
    # cursor on 3, rows 1 2 3 4 Next 5: two down, then Enter
    d = L.decide(target("multi_typed", "t"), "blocked", screen("multi_typed"))
    assert d.keys == ("down", "down", "enter")


def test_decide_refuses_tab_on_a_single_choice_question():
    # there a number key already moves on; a Tab would skip the question unanswered
    assert not L.decide(target("multi_q1", "t"), "blocked", screen("multi_q1")).send


def test_decide_ticks_a_box_from_its_own_row():
    # a number typed while the cursor sits in the free-text row becomes text (measured, capture.py),
    # so the cursor goes to the box first
    d = L.decide(target("multi_select", 2), "blocked", screen("multi_select"))
    assert (d.send, d.keys) == (True, ("down", "2"))
    assert L.decide(target("multi_typed", 1), "blocked", screen("multi_typed")).keys == ("up", "up", "1")


def test_decide_on_a_single_choice_question_presses_only_the_number():
    assert L.decide(target("multi_q1", 2), "blocked", screen("multi_q1")).keys == ("2",)


def test_decide_refuses_the_typed_row_of_a_multi_select_question():
    # "4. [✔] 西瓜" is what was typed; a "4" pressed there would be typed after it
    assert not L.decide(target("multi_typed", 4), "blocked", screen("multi_typed")).send


def test_layout_finds_the_rows_and_the_cursor_below_the_tab_bar():
    rows, cursor = L.layout(screen("multi_typed"))
    assert [r for r, _ in rows] == ["1", "2", "3", "4", "Next", "5"]
    assert rows[3] == ("4", "[✔] 西瓜") and cursor == 2


def test_short_label_drops_the_box_and_the_tab_marker():
    assert L.short_label("2. [ ] 香蕉") == "2. 香蕉"
    assert L.short_label("t. 這題選好了 →") == "這題選好了 →"
    assert L.short_label("3. 派一個 subagent") == "3. 派一個 subagent"


def test_decide_sends_the_option_key_when_the_dialog_is_unchanged():
    d = L.decide(target("choice_wide", 2), "blocked", screen("choice_wide"))
    assert (d.send, d.keys, d.label) == (True, ("2",), "2. web-ui-6c")


def test_decide_refuses_when_the_agent_is_no_longer_blocked():
    d = L.decide(target("choice_wide", 2), "working", screen("choice_wide"))
    assert not d.send


def test_decide_refuses_when_the_screen_shows_another_dialog():
    d = L.decide(target("choice_wide", 1), "blocked", screen("perm"))
    assert not d.send


def test_decide_refuses_an_option_that_never_becomes_a_button():
    # "2. Yes, and don't ask again" is on screen but must stay on the computer
    d = L.decide(target("perm_always", 2), "blocked", screen("perm_always"))
    assert not d.send


def test_decide_refuses_when_the_screen_cannot_be_read():
    assert not L.decide(target("perm", 1), "blocked", None).send


# --- Telegram.call: the long-poll "timeout" is a Telegram parameter, not the HTTP one ---

def test_telegram_call_sends_its_own_timeout_parameter(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return b'{"ok": true, "result": []}'

    def fake_urlopen(req, timeout):
        sent["http_timeout"], sent["body"], sent["url"] = timeout, req.data, req.full_url
        return Resp()

    monkeypatch.setattr(L.urllib.request, "urlopen", fake_urlopen)
    assert L.Telegram("T0KEN").call("getUpdates", http_timeout=60, timeout=50, offset=3)["ok"]
    assert sent["http_timeout"] == 60
    assert L.json.loads(sent["body"]) == {"timeout": 50, "offset": 3}
    assert sent["url"].endswith("/botT0KEN/getUpdates")


# --- handle_update --------------------------------------------------------------------

class FakeHerdr:
    """screen_text is what the agent shows until a key is sent; after it, `after` (one screen per
    read, the last one repeating) and `status_after`."""

    def __init__(self, status="blocked", screen_text=None, after=None, status_after=None,
                 page=("<b>next</b>", {"inline_keyboard": [[{"text": "x", "callback_data": "y"}]]})):
        self.status_value, self.screen_text, self.keys = status, screen_text, []
        self.after, self.status_after, self.page, self.rendered = list(after or []), status_after, page, []

    def status(self, t):
        return self.status_after if self.keys and self.status_after else self.status_value

    def screen(self, t):
        if self.keys and self.after:
            return self.after.pop(0) if len(self.after) > 1 else self.after[0]
        return self.screen_text

    def send_keys(self, t, *keys):
        self.keys.append((t.machine, t.pane, keys))

    def send_text(self, t, text):
        self.keys.append((t.machine, t.pane, ("text", text)))

    def render(self, t):
        self.rendered.append((t.machine, t.pane))
        return self.page


class FakeTelegram:
    def __init__(self, fail_html=False):
        self.calls, self.fail_html = [], fail_html

    def answer_callback(self, callback_id, text):
        self.calls.append(("answer", callback_id, text))

    def edit_message(self, chat_id, message_id, text, entities):
        self.calls.append(("edit", chat_id, message_id, text, entities))

    def edit_html(self, chat_id, message_id, html, markup):
        if self.fail_html:
            raise L.urllib.error.URLError("Bad Request")
        self.calls.append(("redraw", chat_id, message_id, html, markup))

    def send_message(self, chat_id, text, reply_to):
        self.calls.append(("send", chat_id, text, reply_to))


def callback_update(data, from_id=OWNER):
    entities = [{"type": "bold", "offset": 0, "length": 5}]
    return {"update_id": 7, "callback_query": {
        "id": "cb1", "from": {"id": from_id}, "data": data,
        "message": {"message_id": 22, "chat": {"id": OWNER}, "text": "等你回答：哪個分頁", "entities": entities},
    }}


def test_handle_update_presses_the_key_and_marks_the_message_answered():
    h = FakeHerdr(screen_text=screen("choice_wide"), after=[screen("generic")], status_after="working")
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|w|w6:p1|3|{fp('choice_wide')}"), OWNER, h, tg)
    assert h.keys == [("w", "w6:p1", ("3",))]
    edit = next(c for c in tg.calls if c[0] == "edit")
    assert edit[2] == 22 and edit[3].startswith("等你回答：哪個分頁") and "已回答：3. 派一個 subagent" in edit[3]
    assert edit[4] == [{"type": "bold", "offset": 0, "length": 5}]  # formatting kept
    assert any(c[0] == "answer" for c in tg.calls)


def test_a_key_the_screen_never_reacts_to_is_not_called_an_answer():
    # herdr's reading can lag behind (worse over --machine); "answered" would be a guess
    h, tg = FakeHerdr(screen_text=screen("choice_wide")), FakeTelegram()
    answered = set()
    L.handle_update(callback_update(f"a1|w|w6:p1|3|{fp('choice_wide')}"), OWNER, h, tg, answered)
    edit = next(c for c in tg.calls if c[0] == "edit")[3]
    assert "已按：3. 派一個 subagent" in edit and "電腦" in edit and "已回答" not in edit
    assert answered == {(OWNER, 22)}


def test_a_button_from_before_a_redraw_leaves_the_message_alone():
    # two quick taps on the same keyboard: the first redrew the message, the second carries the old
    # fingerprint; editing with the callback's text would put the old screen back and drop the buttons
    h, tg = FakeHerdr(screen_text=screen("perm")), FakeTelegram()
    answered = set()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('choice_wide')}"), OWNER, h, tg, answered)
    assert h.keys == []
    assert tg.calls == [("answer", "cb1", "沒送出：畫面已經變了")]
    assert answered == set()


def test_a_button_after_the_agent_moved_on_marks_the_message():
    h, tg = FakeHerdr(status="working", screen_text=screen("choice_wide")), FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('choice_wide')}"), OWNER, h, tg)
    assert h.keys == []
    assert "沒送出：agent 已經不在等你" in next(c for c in tg.calls if c[0] == "edit")[3]


def telegram_error(code, body):
    return L.urllib.error.HTTPError("https://api.telegram.org/botX/m", code, "Bad Request", {}, io.BytesIO(body))


def test_a_tap_that_arrives_late_still_marks_the_message(monkeypatch):
    # the Mac was offline for a while; Telegram refuses to show a toast for so old a tap
    tg, calls = L.Telegram("x"), []

    def call(method, http_timeout=15, **params):
        calls.append(method)
        if method == "answerCallbackQuery":
            raise telegram_error(400, b'{"ok":false,"description":"Bad Request: query is too old"}')
        return {"ok": True}

    monkeypatch.setattr(tg, "call", call)
    h = FakeHerdr(status="working", screen_text=screen("choice_wide"))
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('choice_wide')}"), OWNER, h, tg)
    assert calls == ["answerCallbackQuery", "editMessageText"]


def test_a_failed_update_is_logged_with_telegrams_reason():
    e = telegram_error(400, b'{"ok":false,"description":"Bad Request: message is not modified"}')
    assert L.describe(e) == "HTTP 400: Bad Request: message is not modified"
    assert L.describe(telegram_error(502, b"<html>")) == "<HTTPError 502: 'Bad Request'>"
    assert L.describe(ValueError("x")) == "ValueError('x')"


def test_herdr_that_hangs_reads_as_unknown(monkeypatch):
    def hang(argv, **kw):
        raise L.subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(L.subprocess, "run", hang)
    t = L.Target("m", "wC:pE", "1", "00000000")
    assert L.Herdr().screen(t) is None and L.Herdr().status(t) is None and L.Herdr().render(t) is None


def test_a_bracket_in_a_single_choice_label_is_not_a_box():
    # "1. [推薦] 紅" on a single-choice question: a number picks it, there is nothing to tick
    s = screen("multi_q1").replace("1. 紅", "1. [推薦] 紅")
    assert "t. 這題選好了 →" not in L.dialog_options(s)
    assert L.press("2", s) == ("2",)  # no cursor walk: the cursor is on 1


def test_handle_update_ignores_everyone_but_the_owner():
    h, tg = FakeHerdr(screen_text=screen("choice_wide")), FakeTelegram()
    L.handle_update(callback_update(f"a1|w|w6:p1|3|{fp('choice_wide')}", from_id=12345), OWNER, h, tg)
    assert h.keys == [] and tg.calls == []


def test_handle_update_ignores_a_malformed_button():
    h, tg = FakeHerdr(screen_text=screen("choice_wide")), FakeTelegram()
    L.handle_update(callback_update("a1|m|-v|3|4dcd4882"), OWNER, h, tg)
    assert h.keys == []


# --- free-text replies (Stage 3) ------------------------------------------------------

def reply_update(text, name="choice_wide", from_id=OWNER, markup=True, machine="w"):
    original = {"message_id": 30, "chat": {"id": OWNER}, "text": "等你回答：哪個分頁",
                "entities": [{"type": "bold", "offset": 0, "length": 5}]}
    if markup:
        original["reply_markup"] = {"inline_keyboard": [
            [{"text": "1. x", "callback_data": f"a1|{machine}|w6:p1|1|{fp(name)}"}]]}
    return {"update_id": 8, "message": {"message_id": 31, "from": {"id": from_id}, "chat": {"id": OWNER},
                                        "text": text, "reply_to_message": original}}


def test_type_option_finds_the_free_text_entry_on_screen():
    assert L.type_option(screen("choice_wide")) == 4
    assert L.type_option(screen("perm")) is None


def test_clean_text_keeps_one_line_so_enter_is_pressed_only_once():
    assert L.clean_text("  熱可可\n少糖  ") == "熱可可 少糖"
    assert len(L.clean_text("字" * 2000)) == 500


def test_reply_types_the_text_as_the_free_text_answer():
    h = FakeHerdr(screen_text=screen("choice_wide"), after=[screen("generic")], status_after="working")
    tg = FakeTelegram()
    L.handle_update(reply_update("熱可可\n少糖"), OWNER, h, tg)
    assert h.keys == [("w", "w6:p1", ("4",)), ("w", "w6:p1", ("text", "熱可可 少糖")), ("w", "w6:p1", ("enter",))]
    edit = next(c for c in tg.calls if c[0] == "edit")
    assert edit[2] == 30 and "已回答：熱可可 少糖" in edit[3] and edit[4][0]["type"] == "bold"


def test_reply_to_a_permission_dialog_is_refused():
    h, tg = FakeHerdr(screen_text=screen("perm")), FakeTelegram()
    L.handle_update(reply_update("yes", name="perm"), OWNER, h, tg)
    assert h.keys == []
    assert "沒送出" in next(c for c in tg.calls if c[0] == "send")[2]


def test_reply_after_the_screen_changed_is_refused():
    h, tg = FakeHerdr(screen_text=screen("perm")), FakeTelegram()
    L.handle_update(reply_update("茶"), OWNER, h, tg)
    assert h.keys == []


def test_reply_when_the_agent_moved_on_is_refused():
    h, tg = FakeHerdr(status="working", screen_text=screen("choice_wide")), FakeTelegram()
    L.handle_update(reply_update("茶"), OWNER, h, tg)
    assert h.keys == []


def test_reply_from_someone_else_is_ignored():
    h, tg = FakeHerdr(screen_text=screen("choice_wide")), FakeTelegram()
    L.handle_update(reply_update("茶", from_id=12345), OWNER, h, tg)
    assert h.keys == [] and tg.calls == []


def test_a_message_that_is_not_a_reply_to_a_notification_gets_a_hint():
    h, tg = FakeHerdr(screen_text=screen("choice_wide")), FakeTelegram()
    L.handle_update(reply_update("茶", markup=False), OWNER, h, tg)
    assert h.keys == []
    assert any(c[0] == "send" for c in tg.calls)


def test_herdr_send_text_passes_the_text_verbatim(monkeypatch):
    # herdr takes "--" as literal text (measured with herdr 0.9.3: the agent got "-- 牛肉麵加辣"),
    # and already treats a leading "-" in <TEXT> as text
    seen = []

    class Done:
        returncode, stdout = 0, ""

    monkeypatch.setattr(L.subprocess, "run", lambda argv, **kw: seen.append(argv) or Done())
    L.Herdr().send_text(L.Target("w", "w6:p1", 4, "4dcd4882"), "-牛肉麵")
    assert seen == [["herdr", "--machine", REMOTE, "pane", "send-text", "w6:p1", "-牛肉麵"]]


def test_a_second_tap_on_an_answered_notification_presses_nothing():
    # the dialog may still be on screen for a moment after the first key; the second tap must not
    # leave a stray "3" in whatever the agent shows next
    h, tg = FakeHerdr(screen_text=screen("choice_wide")), FakeTelegram()
    answered = set()
    data = f"a1|w|w6:p1|3|{fp('choice_wide')}"
    L.handle_update(callback_update(data), OWNER, h, tg, answered)
    L.handle_update(callback_update(data), OWNER, h, tg, answered)
    assert h.keys == [("w", "w6:p1", ("3",))]


def test_a_reply_to_an_answered_notification_types_nothing():
    h, tg = FakeHerdr(screen_text=screen("choice_wide")), FakeTelegram()
    answered = set()
    L.handle_update(reply_update("茶"), OWNER, h, tg, answered)
    L.handle_update(reply_update("咖啡"), OWNER, h, tg, answered)
    assert [k for k in h.keys if k[2][0] == "text"] == [("w", "w6:p1", ("text", "茶"))]


# --- several questions / multi-select: the agent keeps asking after a key ----------------

def test_answering_one_question_of_several_redraws_the_notification_for_the_next():
    # the agent stays blocked from question to question, so no new notification comes;
    # the old one must show the next question with its own buttons
    h = FakeHerdr(screen_text=screen("multi_q1"), after=[screen("multi_select")])
    tg = FakeTelegram()
    answered = set()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_q1')}"), OWNER, h, tg, answered)
    assert h.keys == [("m", "wC:pE", ("1",))]
    assert h.rendered == [("m", "wC:pE")]
    assert ("redraw", OWNER, 22, *h.page) in tg.calls
    assert not any(c[0] == "edit" for c in tg.calls)
    assert ("answer", "cb1", "已按：1. 紅") in tg.calls
    assert answered == set()  # its new buttons must keep working


def test_ticking_a_box_redraws_the_notification_with_the_box_ticked():
    ticked = screen("multi_select").replace("2. [ ] 香蕉", "2. [✔] 香蕉")
    h, tg = FakeHerdr(screen_text=screen("multi_select"), after=[ticked]), FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|2|{fp('multi_select')}"), OWNER, h, tg)
    assert h.keys == [("m", "wC:pE", ("down", "2"))]
    assert any(c[0] == "redraw" for c in tg.calls)
    assert ("answer", "cb1", "已勾：2. 香蕉") in tg.calls


def test_unticking_a_box_says_so():
    unticked = screen("multi_select").replace("1. [✔] 蘋果", "1. [ ] 蘋果")
    h, tg = FakeHerdr(screen_text=screen("multi_select"), after=[unticked]), FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_select')}"), OWNER, h, tg)
    assert ("answer", "cb1", "已取消勾選：1. 蘋果") in tg.calls


def test_the_screen_is_read_again_and_again_for_about_two_seconds(monkeypatch):
    slept = []
    monkeypatch.setattr(L.time, "sleep", slept.append)
    assert L.after_key(target("multi_q1", 1), FakeHerdr(screen_text=screen("multi_q1"))) == "same"
    assert len(slept) == L.STEP_READS and sum(slept) == pytest.approx(2.0)


def test_the_redraw_waits_for_a_screen_that_lags_behind_the_key():
    h = FakeHerdr(screen_text=screen("multi_q1"), after=[screen("multi_q1"), screen("multi_q1"),
                                                         screen("multi_select")])
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_q1')}"), OWNER, h, tg)
    assert any(c[0] == "redraw" for c in tg.calls)


def test_submitting_the_review_page_marks_the_notification_answered():
    h = FakeHerdr(screen_text=screen("multi_review"), after=[screen("generic")], status_after="working")
    tg = FakeTelegram()
    answered = set()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_review')}"), OWNER, h, tg, answered)
    assert h.rendered == []
    assert "已送出答案" in next(c for c in tg.calls if c[0] == "edit")[3]
    assert answered == {(OWNER, 22)}


def test_cancelling_on_the_review_page_is_not_called_an_answer():
    h = FakeHerdr(screen_text=screen("multi_review"), after=[screen("generic")], status_after="working")
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|2|{fp('multi_review')}"), OWNER, h, tg)
    edit = next(c for c in tg.calls if c[0] == "edit")[3]
    assert "已取消" in edit and "已回答" not in edit


def test_a_redraw_with_no_buttons_to_show_leaves_a_note():
    # notify.sh renders (html, None) when the agent get fails or the screen has no dialog
    h = FakeHerdr(screen_text=screen("multi_q1"), after=[screen("multi_select")], page=("<b>x</b>", None))
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_q1')}"), OWNER, h, tg)
    assert not any(c[0] == "redraw" for c in tg.calls)
    assert "下一步請到電腦上看" in next(c for c in tg.calls if c[0] == "edit")[3]


def test_a_render_that_prints_broken_json_leaves_a_note(monkeypatch, tmp_path):
    broken = tmp_path / "notify.sh"
    broken.write_text("printf '{not json\\n<b>x</b>\\n'\n", encoding="utf-8")
    monkeypatch.setattr(L, "NOTIFY_SH", broken)
    h = FakeHerdr(screen_text=screen("multi_q1"), after=[screen("multi_select")])
    h.render = L.Herdr().render
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_q1')}"), OWNER, h, tg)
    assert "下一步請到電腦上看" in next(c for c in tg.calls if c[0] == "edit")[3]


def test_telegram_edit_html_sends_html_and_the_new_buttons(monkeypatch):
    sent = {}
    monkeypatch.setattr(L.Telegram, "call", lambda self, method, **p: sent.update(method=method, **p))
    kb = {"inline_keyboard": [[{"text": "x", "callback_data": "y"}]]}
    L.Telegram("T").edit_html(1, 2, "<b>h</b>", kb)
    assert sent == {"method": "editMessageText", "chat_id": 1, "message_id": 2, "text": "<b>h</b>",
                    "parse_mode": "HTML", "reply_markup": kb}


def test_a_screen_still_blocked_but_without_a_question_counts_as_answered():
    # herdr can report "blocked" a moment longer than the dialog is on screen
    h = FakeHerdr(screen_text=screen("multi_review"), after=[screen("generic")])
    tg = FakeTelegram()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_review')}"), OWNER, h, tg)
    assert h.rendered == [] and any(c[0] == "edit" for c in tg.calls)


def test_a_redraw_telegram_rejects_leaves_a_note_instead_of_a_false_answer():
    h = FakeHerdr(screen_text=screen("multi_q1"), after=[screen("multi_select")])
    tg = FakeTelegram(fail_html=True)
    answered = set()
    L.handle_update(callback_update(f"a1|m|wC:pE|1|{fp('multi_q1')}"), OWNER, h, tg, answered)
    edit = next(c for c in tg.calls if c[0] == "edit")[3]
    assert "已按：1. 紅" in edit and "已回答" not in edit and "電腦" in edit
    assert answered == {(OWNER, 22)}


def test_a_typed_answer_to_one_of_several_questions_redraws_too():
    h = FakeHerdr(screen_text=screen("multi_q1"), after=[screen("multi_select")])
    tg = FakeTelegram()
    L.handle_update(reply_update("紫", name="multi_q1", machine="m"), OWNER, h, tg)
    assert h.keys == [("m", "w6:p1", ("4",)), ("m", "w6:p1", ("text", "紫")), ("m", "w6:p1", ("enter",))]
    assert ("redraw", OWNER, 30, *h.page) in tg.calls
    assert not any(c[0] == "edit" for c in tg.calls)  # the redraw is the whole update


def test_a_typed_answer_keeps_its_words_in_the_note():
    # the button labels lose "t. " and "[ ] "; typed text must not
    h, tg = FakeHerdr(screen_text=screen("multi_q1")), FakeTelegram()
    L.handle_update(reply_update("t. 紅茶 [ ] 加冰", name="multi_q1", machine="m"), OWNER, h, tg)
    assert "已送出：t. 紅茶 [ ] 加冰；畫面還沒變" in next(c for c in tg.calls if c[0] == "edit")[3]


def test_a_typed_answer_to_a_multi_select_question_goes_into_its_free_text_row():
    # typing needs the cursor on that row (a "4" only ticks the box); the box ticks itself, and
    # Enter is left out so the question stays open for more boxes (measured, tests/capture.py)
    h = FakeHerdr(screen_text=screen("multi_select"), after=[screen("multi_typed")])
    tg = FakeTelegram()
    L.handle_update(reply_update("西瓜", name="multi_select", machine="m"), OWNER, h, tg)
    assert h.keys == [("m", "w6:p1", ("down", "down", "down")), ("m", "w6:p1", ("text", "西瓜"))]
    assert ("redraw", OWNER, 30, *h.page) in tg.calls


def test_a_second_typed_answer_to_a_multi_select_question_is_refused():
    # the row already holds text; typing again would append to it
    h, tg = FakeHerdr(screen_text=screen("multi_typed")), FakeTelegram()
    L.handle_update(reply_update("葡萄", name="multi_typed"), OWNER, h, tg)
    assert h.keys == []
    assert "已經打過" in next(c for c in tg.calls if c[0] == "send")[2]


# --- notify.sh in render mode: what a redraw shows, built the same way as the notification --

def fake_herdr_bin(tmp_path, screen_name):
    log = tmp_path / "argv.log"
    agent = {"result": {"agent": {"agent_status": "blocked", "workspace_id": "wC", "tab_id": "wC:t1",
                                  "cwd": "/x/mod-pane", "terminal_title_stripped": "測試"}}}
    tabs = {"result": {"tabs": [{"tab_id": "wC:t1", "label": "qmp"}]}}
    (tmp_path / "agent.json").write_text(json.dumps(agent), encoding="utf-8")
    (tmp_path / "tabs.json").write_text(json.dumps(tabs), encoding="utf-8")
    (tmp_path / "screen.txt").write_text(screen(screen_name), encoding="utf-8")
    script = tmp_path / "herdr"
    script.write_text(f"""#!/bin/sh
echo "$*" >> {log}
case "$*" in
  # agent<N>.json, if there is one, answers the Nth "agent get"
  *"agent get"*) n=$(( $(cat {tmp_path}/gets 2>/dev/null || echo 0) + 1 )); echo $n > {tmp_path}/gets
    if [ -f {tmp_path}/agent$n.json ]; then cat {tmp_path}/agent$n.json; else cat {tmp_path}/agent.json; fi ;;
  *"tab list"*) cat {tmp_path}/tabs.json ;;
  *"agent read"*) cat {tmp_path}/screen.txt ;;
  *) exit 1 ;;
esac
""", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return log


def test_render_builds_the_desktop_page_over_herdr_machine(tmp_path, monkeypatch):
    log = fake_herdr_bin(tmp_path, "multi_select")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    html, markup = L.Herdr().render(L.Target("w", "wC:pE", "1", "00000000"))
    assert html.startswith("<b>等你回答：☒ 顏色 · ☒ 水果</b>\n測試\n分頁 qmp · mod-pane\n<blockquote>")
    assert html.endswith(f"</blockquote>\n{REMOTE}")
    rows = [r[0] for r in markup["inline_keyboard"]]
    assert [r["text"] for r in rows] == ["1. [✔] 蘋果", "2. [ ] 香蕉", "3. [✔] 橘子", "這題選好了 →"]
    assert rows[-1]["callback_data"] == f"a1|w|wC:pE|t|{fp('multi_select')}"
    assert all(line.startswith(f"--machine {REMOTE} ") for line in log.read_text().splitlines())


def test_render_in_english_keeps_the_fingerprint(tmp_path, monkeypatch, config):
    # the language changes the words around the screen, not the fingerprint: a Mac listener and a
    # Windows plugin set to different languages still agree on which dialog a button belongs to
    (config / "language").write_text("en\n", encoding="utf-8")
    fake_herdr_bin(tmp_path, "multi_select")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    html, markup = L.Herdr().render(L.Target("w", "wC:pE", "1", "00000000"))
    assert html.startswith("<b>Waiting for your answer: ☒ 顏色 · ☒ 水果</b>\n測試\ntab qmp · mod-pane\n<blockquote>")
    rows = [r[0] for r in markup["inline_keyboard"]]
    assert rows[-1] == {"text": "Done with this question →", "callback_data": f"a1|w|wC:pE|t|{fp('multi_select')}"}


def test_render_without_a_language_file_is_english(tmp_path, monkeypatch, config):
    (config / "language").unlink()
    fake_herdr_bin(tmp_path, "multi_q1")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    html, _ = L.Herdr().render(L.Target("m", "wC:pE", "1", "00000000"))
    assert html.startswith("<b>Waiting for your answer: ")


def test_render_of_a_mac_agent_uses_the_local_server(tmp_path, monkeypatch):
    log = fake_herdr_bin(tmp_path, "multi_q1")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    html, markup = L.Herdr().render(L.Target("m", "wC:pE", "1", "00000000"))
    assert markup["inline_keyboard"][0][0]["callback_data"] == f"a1|m|wC:pE|1|{fp('multi_q1')}"
    assert not any("--machine" in line for line in log.read_text().splitlines())


def test_render_of_an_agent_that_moved_on_is_nothing(tmp_path, monkeypatch):
    fake_herdr_bin(tmp_path, "multi_q1")
    (tmp_path / "agent.json").write_text('{"result":{"agent":{"agent_status":"working"}}}', encoding="utf-8")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    assert L.Herdr().render(L.Target("m", "wC:pE", "1", "00000000")) is None


# --- notify.sh as the plugin: the message is remembered, and loses its buttons when the agent stops
# waiting (answered on the computer, interrupted) -------------------------------------------------

UNBUTTONED = {"ok": True, "result": {"message_id": 555, "chat": {"id": 42}, "text": "等你回答：哪個\n\n甲",
                                     "entities": [{"offset": 0, "length": 5, "type": "bold"}]}}
NOT_MODIFIED = {"ok": False, "description": "Bad Request: message is not modified: specified new message "
                "content and reply markup are exactly the same as a current content and reply markup of the message"}


def fake_curl_bin(tmp_path, unbutton=UNBUTTONED):
    # each call: "<method>\t<what came on stdin>" (both the form posts and the JSON posts pipe it),
    # ended by a record separator because a message has newlines
    log = tmp_path / "curl.log"
    (tmp_path / "unbutton.json").write_text(json.dumps(unbutton), encoding="utf-8")
    script = tmp_path / "curl"
    script.write_text(f"""#!/bin/sh
for a; do case $a in https://*) url=$a ;; esac; done
printf '%s\\t%s\\036' "${{url##*/}}" "$(cat)" >> {log}
case ${{url##*/}} in
  sendMessage) echo '{{"ok":true,"result":{{"message_id":555}}}}' ;;
  editMessageReplyMarkup) cat {tmp_path}/unbutton.json ;;
  *) echo '{{"ok":true}}' ;;
esac
""", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    # sleep goes into the same log, so a test sees whether the plugin waited before a call
    pause = tmp_path / "sleep"
    pause.write_text(f"#!/bin/sh\nprintf 'sleep\\t%s\\036' \"$*\" >> {log}\n", encoding="utf-8")
    pause.chmod(pause.stat().st_mode | stat.S_IEXEC)
    return log


def sent_file(tmp_path):
    return tmp_path / "state" / "sent" / "wC_pE"


def remember(tmp_path, message_id):
    sent_file(tmp_path).parent.mkdir(parents=True)
    sent_file(tmp_path).write_text(f"{message_id}\n")


def run_plugin(tmp_path, config, status, state=True, **extra):
    (config / "telegram").write_text("TOKEN\n42\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "HERDR_PANE_ID": "wC:pE",
           "HERDR_PLUGIN_CONFIG_DIR": str(config), "NOTIFY_HERDR_MACHINE": REMOTE,
           "HERDR_PLUGIN_EVENT_JSON": json.dumps({"type": "pane_agent_status_changed", "pane_id": "wC:pE",
                                                  "workspace_id": "wC", "agent_status": status}), **extra}
    env.pop("HERDR_PLUGIN_STATE_DIR", None)
    if state:
        env["HERDR_PLUGIN_STATE_DIR"] = str(tmp_path / "state")
    r = L.subprocess.run(["sh", str(L.NOTIFY_SH)], env=env, stdin=L.subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def curl_calls(log):
    if not log.exists():
        return []
    return [(m, json.loads(b) if b.startswith("{") else b)
            for m, b in (rec.split("\t", 1) for rec in log.read_text(encoding="utf-8").split("\x1e")[:-1])]


def test_a_notification_is_remembered_by_pane_in_the_state_directory(tmp_path, config):
    fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path)
    run_plugin(tmp_path, config, "blocked")
    assert [m for m, _ in curl_calls(log)] == ["sendMessage"]
    assert sent_file(tmp_path).read_text() == "555\n"


def test_without_a_state_directory_it_is_remembered_in_the_config_directory(tmp_path, config):
    # herdr versions that do not hand plugins a state directory
    fake_herdr_bin(tmp_path, "multi_q1")
    fake_curl_bin(tmp_path)
    run_plugin(tmp_path, config, "blocked", state=False)
    assert (config / "sent" / "wC_pE").read_text() == "555\n"


def test_a_notification_without_buttons_is_not_remembered(tmp_path, config):
    # nothing to take off later (here herdr cannot say what the agent shows)
    fake_herdr_bin(tmp_path, "multi_q1")
    (tmp_path / "agent.json").unlink()
    log = fake_curl_bin(tmp_path)
    run_plugin(tmp_path, config, "blocked")
    assert [m for m, _ in curl_calls(log)] == ["sendMessage"]
    assert not sent_file(tmp_path).exists()


def test_when_the_agent_stops_waiting_its_message_loses_the_buttons(tmp_path, config):
    herdr_log = fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path)
    remember(tmp_path, 555)
    run_plugin(tmp_path, config, "working")
    calls = curl_calls(log)
    assert calls == [
        # first give a tap from the phone time to land its own note
        ("sleep", "5"),
        ("editMessageReplyMarkup", {"chat_id": "42", "message_id": 555, "reply_markup": {"inline_keyboard": []}}),
        ("editMessageText", {"chat_id": 42, "message_id": 555, "text": "等你回答：哪個\n\n甲\n\nagent 已經不在等你了",
                             "entities": UNBUTTONED["result"]["entities"]}),
    ]
    assert not sent_file(tmp_path).exists()
    # it needs nothing from herdr to do this
    assert not herdr_log.exists()


def test_the_note_follows_the_language(tmp_path, config):
    (config / "language").write_text("en\n", encoding="utf-8")
    fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path)
    remember(tmp_path, 555)
    run_plugin(tmp_path, config, "idle")
    assert curl_calls(log)[-1][1]["text"].endswith("\n\nThe agent is no longer waiting")


def test_after_a_tap_from_the_phone_the_listeners_note_stays(tmp_path, config):
    # the listener took the buttons off with its own note; Telegram refuses a second take
    fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path, unbutton=NOT_MODIFIED)
    remember(tmp_path, 555)
    run_plugin(tmp_path, config, "working")
    assert [m for m, _ in curl_calls(log)] == ["sleep", "editMessageReplyMarkup"]
    assert not sent_file(tmp_path).exists()


def test_a_leftover_leaving_flag_does_not_swallow_a_notification(tmp_path, config):
    fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path)
    run_plugin(tmp_path, config, "blocked", leaving="1")
    assert [m for m, _ in curl_calls(log)] == ["sendMessage"]


def test_a_redraw_touches_neither_telegram_nor_the_remembered_message(tmp_path, config):
    # the listener runs notify.sh in render mode while the agent may be anything
    fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path)
    remember(tmp_path, 555)
    for status in ("working", "blocked"):
        (tmp_path / "agent.json").write_text(json.dumps({"result": {"agent": {"agent_status": status}}}))
        run_plugin(tmp_path, config, status, NOTIFY_RENDER="1")
    assert curl_calls(log) == []
    assert sent_file(tmp_path).read_text() == "555\n"


def test_other_events_with_no_message_cost_nothing(tmp_path, config):
    herdr_log = fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path)
    run_plugin(tmp_path, config, "working")
    assert curl_calls(log) == []
    assert not herdr_log.exists()


def test_answered_on_the_computer_while_the_message_was_on_its_way(tmp_path, config):
    # the leaving event ran before the message was remembered; the plugin looks once more
    fake_herdr_bin(tmp_path, "multi_q1")
    (tmp_path / "agent2.json").write_text('{"result":{"agent":{"agent_status":"working"}}}', encoding="utf-8")
    log = fake_curl_bin(tmp_path)
    run_plugin(tmp_path, config, "blocked")
    # no tap can have come yet, so no waiting
    assert [m for m, _ in curl_calls(log)] == ["sendMessage", "editMessageReplyMarkup", "editMessageText"]
    assert not sent_file(tmp_path).exists()


def test_still_waiting_after_sending_keeps_the_buttons(tmp_path, config):
    fake_herdr_bin(tmp_path, "multi_q1")
    log = fake_curl_bin(tmp_path)
    run_plugin(tmp_path, config, "blocked")
    assert [m for m, _ in curl_calls(log)] == ["sendMessage"]


def test_a_blocked_event_that_is_already_over_takes_the_old_message_back(tmp_path, config):
    fake_herdr_bin(tmp_path, "multi_q1")
    (tmp_path / "agent.json").write_text('{"result":{"agent":{"agent_status":"working"}}}', encoding="utf-8")
    log = fake_curl_bin(tmp_path)
    remember(tmp_path, 444)
    run_plugin(tmp_path, config, "blocked")
    calls = curl_calls(log)
    assert [m for m, _ in calls] == ["sleep", "editMessageReplyMarkup", "editMessageText"]
    assert calls[1][1]["message_id"] == 444
