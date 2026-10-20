# Turns a herdr "visible" snapshot of a blocked agent into Telegram HTML.
# Output line 1 is the headline (already escaped); the rest is the message body.
# With -v part=options it prints instead the options that may become buttons, one per line.
# -v lang=en words the parts this script adds in English; the screen's own text is never
# translated. Without it the wording is Traditional Chinese, which is also what fingerprints use.
function L(zh, en) { return lang == "en" ? en : zh }
function esc(s) { gsub(/&/, "\\&amp;", s); gsub(/</, "\\&lt;", s); gsub(/>/, "\\&gt;", s); return s }
function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
function unbar(s) { s = trim(s); sub(/^│ ?/, "", s); sub(/^❯ */, "", s); return s }
# Claude Code wraps text to the pane width itself, so glue continuation lines back together
# (the wrap ate a space wherever either side is ASCII; between two CJK characters there was none)
function glue(a, b) { return a == "" ? b : a ((a ~ /[!-~]$/ || b ~ /^[!-~]/) ? " " : "") b }

/^ *─/ { rule[++nr] = n; next }
/^[[:space:]]*$/ { next }
/Enter to select|Esc to cancel/ { footer = n; next }
{ raw[++n] = $0 }

END {
  # the footer can wrap ("Esc to" / "cancel"); drop what follows it
  if (footer && n - footer <= 1) n = footer
  # the dialog starts at the last solid rule with >= 3 lines below it (a choice list has a
  # second rule above "Chat about this"); without one, fall back to the last 12 lines
  s = n > 12 ? n - 12 : 0
  for (k = nr; k >= 1; k--) if (n - rule[k] >= 3) { s = rule[k]; break }
  for (i = s + 1; i <= n; i++) if (raw[i] ~ /^ *╌/) { permit = 1; break }
  # a single question starts with "☐ header"; several questions, or a multi-select one, start
  # with a tab bar instead: "←  ☐ header  ☒ header  ✔ Submit  →"
  ask = trim(raw[s + 1]) ~ /^(☐|☒|✔)|^←.*→$/
  if (part == "options") { if (permit) options(s, 1); else if (ask) options(s, 0) }
  else if (permit) permission(s)
  else if (ask) choice(s)
  else generic(s)
}

# options that are free text or "Chat about this" (multi-select ones carry a "[ ] " box)
function freeform(t) { return t ~ /^[0-9]+\. (\[[^]]*\] )?(Type something|Chat about this)/ }
# a multi-select question ends in an unnumbered "Submit" row ("Next" when more questions follow);
# the option just above it is the free-text one, whatever has been typed into it
function navrow(t) { return t ~ /^(Submit|Next)$/ }
# a multi-select option: "1. [ ] ..." / "1. [✔] ..." (not "1. [推薦] ..." on a single-choice one)
function boxed(t) { return t ~ /^[0-9]+\. \[( |✔)\] / }

# a permission dialog lists its options after "Do you want to ..."; options that widen
# permissions for good, free text, and "Chat about this" stay on the computer.
# A multi-select question ("1. [ ] ...", where a number key only ticks the box) gets one more
# entry, "t.", for moving on to the next question or the review page
function options(s, permit,   i, t, on, multi, k, m, opts, keep) {
  on = !permit
  for (i = s + 2; i <= n; i++) {
    if (raw[i] ~ /Do you want to/) { on = 1; continue }
    t = unbar(raw[i])
    if (multi && navrow(t)) { keep[k] = 0; continue }
    if (!on || t !~ /^[0-9]+\. /) continue
    if (boxed(t)) multi = 1
    opts[++k] = t; keep[k] = !(t ~ /ask again|[Aa]lways/ || freeform(t))
  }
  for (m = 1; m <= k; m++) if (keep[m]) print opts[m]
  if (multi) print "t. " L("這題選好了 →", "Done with this question →")
}

function permission(s,   i, l, sec, desc, cmd, reason, nc) {
  print L("等你批准：", "Needs your approval: ") esc(trim(raw[s + 1]))
  for (i = s + 2; i <= n; i++) {
    l = raw[i]
    if (l ~ /^ *╌/) { sec++; continue }
    if (l ~ /Do you want to/) break
    if (sec == 0) desc = glue(desc, unbar(l))
    else if (sec == 1) { if (++nc <= 20) cmd = cmd (cmd == "" ? "" : "\n") substr(l, 2) }
    else reason = glue(reason, unbar(l))
  }
  if (desc != "") print esc(desc)
  if (cmd != "") print "<pre>" esc(cmd) "</pre>"
  if (reason != "") print "<blockquote expandable>" esc(reason) "</blockquote>"
}

function choice(s,   i, l, t, q, opt, desc, skip, review) {
  t = trim(raw[s + 1])
  if (t ~ /^←/) {
    # the tab bar: keep the questions and their boxes, drop the arrows and the Submit tab
    sub(/^← */, "", t); sub(/ *→$/, "", t); sub(/ *✔ Submit$/, "", t); gsub(/  +/, " · ", t)
    review = trim(raw[s + 2]) == "Review your answers"
  } else sub(/^(☐|☒|✔) */, "", t)
  # the review page lists "● question" / "→ answer" pairs, one per line
  print review ? L("等你確認答案", "Confirm your answers") : L("等你回答：", "Waiting for your answer: ") esc(t)
  for (i = s + 2 + review; i <= n; i++) {
    l = raw[i]; t = unbar(l)
    if (t ~ /^[0-9]+\. /) {
      flush(opt, desc, skip); opt = t; desc = ""
      skip = freeform(t)
    } else if (boxed(opt) && navrow(t)) { if (!skip) desc = L("（你打的字）", "(what you typed)"); continue }
    else if (review && t == "Ready to submit your answers?") continue
    else if (review && opt == "" && t ~ /^(●|→)/) q = q (q == "" ? "" : "\n") t
    else if (opt == "") q = glue(q, t)
    else desc = glue(desc, t)
  }
  flush(opt, desc, skip)
  # the question goes first, so collect options into a buffer; frame both in one quote box
  sub(/\n$/, "", out)
  print "<blockquote>" (q != "" ? esc(q) "\n" : "") out "</blockquote>"
}
function flush(opt, desc, skip) {
  if (opt == "" || skip) return
  out = out "\n<b>" esc(opt) "</b>\n" (desc != "" ? esc(desc) "\n" : "")
}

function generic(s,   i, body) {
  print L("等你處理", "Waiting for you")
  for (i = s + 1; i <= n; i++) body = body (body == "" ? "" : "\n") unbar(raw[i])
  print "<blockquote expandable>" esc(body) "</blockquote>"
}
