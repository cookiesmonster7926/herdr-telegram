#!/bin/sh
# The listener runs this too, to redraw a notification after a key (the next question, a ticked
# box): NOTIFY_RENDER=1 prints the reply markup on line 1 and the message HTML after it instead
# of sending; NOTIFY_LETTER / NOTIFY_HERDR_MACHINE name another machine's agent (w = the desktop)
if [ -z "${NOTIFY_RENDER:-}" ]; then
  # ponytail: substring match on the event JSON; parse with jq if herdr adds other "blocked" fields
  case "$HERDR_PLUGIN_EVENT_JSON" in *'"blocked"'*) ;; *) exit 0 ;; esac
  { read -r token; read -r chat; } < "$HERDR_PLUGIN_CONFIG_DIR/telegram" || exit 0
fi
herdr=$(command -v herdr || echo "$HOME/.local/bin/herdr")
hd() { "$herdr" ${NOTIFY_HERDR_MACHINE:+--machine "$NOTIFY_HERDR_MACHINE"} "$@"; }
esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
send() {
  curl -s -m 10 "https://api.telegram.org/bot$token/sendMessage" -d chat_id="$chat" "$@" --data-urlencode text@-
}
pane=${HERDR_PANE_ID:-}
letter=${NOTIFY_LETTER:-m}
machine=$(printf '%s' "${NOTIFY_HERDR_MACHINE:-$(scutil --get ComputerName)}" | esc)
# the `language` file next to `telegram`: zh-TW (or zh) for Traditional Chinese, else English
case $(head -n 1 "${HERDR_PLUGIN_CONFIG_DIR:-.}/language" 2>/dev/null | tr -d '[:space:]') in
  zh-TW | zh) lang=zh ;;
  *) lang=en ;;
esac
L() { if [ "$lang" = en ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
head="agent $pane $(L 需要你 'needs you')" meta="" body=""
if info=$(hd agent get "$pane" 2>/dev/null); then
  # the event also fires when leaving blocked; only notify if the agent is blocked right now
  [ "$(printf '%s' "$info" | jq -r '.result.agent.agent_status')" = blocked ] || exit 0
  ws=$(printf '%s' "$info" | jq -r '.result.agent.workspace_id')
  tab=$(printf '%s' "$info" | jq -r '.result.agent.tab_id')
  cwd=$(printf '%s' "$info" | jq -r '.result.agent.cwd // empty')
  title=$(printf '%s' "$info" | jq -r '.result.agent.terminal_title_stripped // empty')
  tab_label=$(hd tab list --workspace "$ws" 2>/dev/null | jq -r --arg id "$tab" '.result.tabs[] | select(.tab_id == $id) | .label')
  meta=$(printf '%s%s%s %s%s' "$title" "${title:+
}" "$(L 分頁 tab)" "${tab_label:-$tab}" "${cwd:+ · ${cwd##*/}}" | esc)
  screen=$(hd agent read "$pane" --source visible 2>/dev/null)
  dialog=$(printf '%s\n' "$screen" | awk -v lang="$lang" -f "$(dirname "$0")/dialog.awk")
  if [ -n "$dialog" ]; then
    head=$(printf '%s\n' "$dialog" | sed -n 1p)
    body=$(printf '%s\n' "$dialog" | sed 1d)
    # one button per option: a1|machine|pane|option|fingerprint (m = this Mac; see the listener);
    # option "t" is "done with this multi-select question". The fingerprint is taken from the
    # default wording, so it does not depend on the language setting of either machine
    fp=$(printf '%s\n' "$screen" | awk -f "$(dirname "$0")/dialog.awk")
    fp=$(printf '%s' "$fp" | md5 | cut -c1-8)
    markup=$(printf '%s\n' "$screen" | awk -v lang="$lang" -v part=options -f "$(dirname "$0")/dialog.awk" |
      jq -R -s -c --arg pane "$pane" --arg fp "$fp" --arg m "$letter" '
        [split("\n")[] | select(length > 0)
         | [{text: sub("^t\\. "; ""), callback_data: "a1|\($m)|\($pane)|\(capture("^(?<n>[0-9]+|t)").n)|\($fp)"}]]
        | if length > 0 then {inline_keyboard: .} else empty end')
  fi
fi
set --
[ -n "${markup:-}" ] && set -- --data-urlencode "reply_markup=$markup"
# a quote box already leaves a gap around it, so next to one a single newline is enough
html() {
  printf '<b>%s</b>' "$head"
  [ -n "$meta" ] && printf '\n%s' "$meta"
  case "$body" in '') ;; '<blockquote'*) printf '\n%s' "$body" ;; *) printf '\n\n%s' "$body" ;; esac
  case "$body" in *'</blockquote>') printf '\n%s' "$machine" ;; *) printf '\n\n%s' "$machine" ;; esac
}
# Telegram caps a message at 4096 characters; bytes overcount, which errs on the safe side
[ "$(html | wc -c)" -gt 4000 ] && body=$(L '（內容太長，請到電腦上看）' '(Too long to show here; see it on the computer)')
if [ -n "${NOTIFY_RENDER:-}" ]; then printf '%s\n' "${markup:-}"; html; exit 0; fi
plain() { html | sed -e 's/<[^>]*>//g' -e 's/&lt;/</g' -e 's/&gt;/>/g' -e 's/&amp;/\&/g'; }
# if the HTML or the buttons get rejected, still get the message itself through
html | send -d parse_mode=HTML "$@" | grep -q '"ok":true' ||
  plain | send "$@" | grep -q '"ok":true' ||
  plain | send >/dev/null
