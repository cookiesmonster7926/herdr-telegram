# Turns a herdr "visible" snapshot of a blocked agent into Telegram HTML (port of dialog.awk).
# Format-Dialog returns the headline (already escaped) and the message body.
# $DialogLang = 'en' words the parts this script adds in English (dialog.awk's -v lang=en); the
# screen's own text is never translated. Unset: Traditional Chinese, which fingerprints use.
$DialogLang = ''
function L([string]$zh, [string]$en) { if ($script:DialogLang -eq 'en') { $en } else { $zh } }
function Esc([string]$s) { $s.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;') }
function Unbar([string]$s) { $s.Trim() -replace '^│ ?', '' -replace '^❯ *', '' }
# Claude Code wraps text to the pane width itself, so glue continuation lines back together
# (the wrap ate a space wherever either side is ASCII; between two CJK characters there was none)
function Glue([string]$a, [string]$b) {
  if ($a -eq '') { return $b }
  if ($a -match '[!-~]$' -or $b -match '^[!-~]') { return "$a $b" }
  "$a$b"
}

function Format-Dialog([string[]]$screen) {
  $lines = Select-Dialog $screen
  if (-not $lines) { return $null }
  if (@($lines -match '^ *╌').Count) { return Format-Permission $lines }
  if (Test-Ask $lines) { return Format-Choice $lines }
  Format-Generic $lines
}

# a single question starts with "☐ header"; several questions, or a multi-select one, start
# with a tab bar instead: "←  ☐ header  ☒ header  ✔ Submit  →"
function Test-Ask([string[]]$lines) { $lines[0].Trim() -match '^(☐|☒|✔)|^←.*→$' }
# options that are free text or "Chat about this" (multi-select ones carry a "[ ] " box)
function Test-Freeform([string]$t) { $t -cmatch '^[0-9]+\. (\[[^]]*\] )?(Type something|Chat about this)' }
# a multi-select question ends in an unnumbered "Submit" row ("Next" when more questions follow);
# the option just above it is the free-text one, whatever has been typed into it
function Test-NavRow([string]$t) { $t -cmatch '^(Submit|Next)$' }
# a multi-select option: "1. [ ] ..." / "1. [✔] ..." (not "1. [推薦] ..." on a single-choice one)
function Test-Boxed([string]$t) { $t -match '^[0-9]+\. \[( |✔)\] ' }

# a permission dialog lists its options after "Do you want to ..."; options that widen
# permissions for good, free text, and "Chat about this" stay on the computer.
# A multi-select question ("1. [ ] ...", where a number key only ticks the box) gets one more
# entry, "t.", for moving on to the next question or the review page
function Get-DialogOptions([string[]]$screen) {
  $lines = Select-Dialog $screen
  if (-not $lines) { return }
  $permit = [bool]@($lines -match '^ *╌').Count
  if (-not $permit -and -not (Test-Ask $lines)) { return }
  $on = -not $permit; $multi = $false
  $opts = New-Object System.Collections.Generic.List[object]
  for ($i = 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'Do you want to') { $on = $true; continue }
    $t = Unbar $lines[$i]
    if ($multi -and (Test-NavRow $t)) { if ($opts.Count) { $opts[$opts.Count - 1].keep = $false }; continue }
    if (-not $on -or $t -notmatch '^[0-9]+\. ') { continue }
    if (Test-Boxed $t) { $multi = $true }
    $opts.Add(@{ t = $t; keep = -not ($t -cmatch 'ask again|[Aa]lways' -or (Test-Freeform $t)) })
  }
  foreach ($o in $opts) { if ($o.keep) { $o.t } }
  if ($multi) { 't. ' + (L '這題選好了 →' 'Done with this question →') }
}

# first 8 hex digits of the MD5 of the formatted dialog (lines joined by "\n"); the buttons carry
# it so the listener can tell whether the screen is still the one the notification showed
function Get-Fingerprint([string[]]$dialog) {
  $hash = [Security.Cryptography.MD5]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($dialog -join "`n"))
  -join ($hash[0..3] | ForEach-Object { $_.ToString('x2') })
}

function Select-Dialog([string[]]$screen) {
  $raw = New-Object System.Collections.Generic.List[string]
  $rules = @(); $footer = 0
  foreach ($l in $screen) {
    if ($l -match '^ *─') { $rules += $raw.Count; continue }
    if ($l -match '^\s*$') { continue }
    if ($l -match 'Enter to select|Esc to cancel') { $footer = $raw.Count; continue }
    $raw.Add($l)
  }
  $n = $raw.Count
  # the footer can wrap ("Esc to" / "cancel"); drop what follows it
  if ($footer -and $n - $footer -le 1) { $n = $footer }
  if ($n -eq 0) { return $null }
  # the dialog starts at the last solid rule with >= 3 lines below it (a choice list has a
  # second rule above "Chat about this"); without one, fall back to the last 12 lines
  $s = if ($n -gt 12) { $n - 12 } else { 0 }
  for ($k = $rules.Count - 1; $k -ge 0; $k--) { if ($n - $rules[$k] -ge 3) { $s = $rules[$k]; break } }
  , @($raw[$s..($n - 1)])
}

function Format-Permission([string[]]$lines) {
  $sec = 0; $desc = ''; $cmd = @(); $reason = ''
  for ($i = 1; $i -lt $lines.Count; $i++) {
    $l = $lines[$i]
    if ($l -match '^ *╌') { $sec++; continue }
    if ($l -match 'Do you want to') { break }
    if ($sec -eq 0) { $desc = Glue $desc (Unbar $l) }
    elseif ($sec -eq 1) { if ($cmd.Count -lt 20) { $cmd += $l.Substring(1) } }
    else { $reason = Glue $reason (Unbar $l) }
  }
  $body = @()
  if ($desc) { $body += Esc $desc }
  if ($cmd.Count) { $body += '<pre>' + (Esc ($cmd -join "`n")) + '</pre>' }
  if ($reason) { $body += '<blockquote expandable>' + (Esc $reason) + '</blockquote>' }
  ((L '等你批准：' 'Needs your approval: ') + (Esc $lines[0].Trim())), ($body -join "`n")
}

function Format-Choice([string[]]$lines) {
  $q = ''; $opts = New-Object System.Collections.Generic.List[object]; $cur = $null
  $head = $lines[0].Trim(); $review = $false
  if ($head -match '^←') {
    # the tab bar: keep the questions and their boxes, drop the arrows and the Submit tab
    $head = $head -replace '^← *', '' -replace ' *→$', '' -replace ' *✔ Submit$', '' -replace '  +', ' · '
    $review = $lines.Count -gt 1 -and $lines[1].Trim() -ceq 'Review your answers'
  } else { $head = $head -replace '^(☐|☒|✔) *', '' }
  # the review page lists "● question" / "→ answer" pairs, one per line
  for ($i = $(if ($review) { 2 } else { 1 }); $i -lt $lines.Count; $i++) {
    $t = Unbar $lines[$i]
    if ($t -match '^[0-9]+\. ') {
      $cur = @{ opt = $t; desc = ''; skip = Test-Freeform $t }
      $opts.Add($cur)
    } elseif ($cur -and (Test-Boxed $cur.opt) -and (Test-NavRow $t)) {
      if (-not $cur.skip) { $cur.desc = L '（你打的字）' '(what you typed)' }; continue
    } elseif ($review -and $t -ceq 'Ready to submit your answers?') { continue }
    elseif ($review -and -not $cur -and $t -match '^(●|→)') { $q = $(if ($q) { "$q`n$t" } else { $t }) }
    elseif (-not $cur) { $q = Glue $q $t }
    else { $cur.desc = Glue $cur.desc $t }
  }
  $items = foreach ($o in $opts) {
    if (-not $o.skip) { '<b>' + (Esc $o.opt) + '</b>' + $(if ($o.desc) { "`n" + (Esc $o.desc) } else { '' }) }
  }
  # frame the question and its options in one quote box
  $intro = if ($q) { (Esc $q) + "`n`n" } else { "`n" }
  $(if ($review) { L '等你確認答案' 'Confirm your answers' } else { (L '等你回答：' 'Waiting for your answer: ') + (Esc $head) }),
    ('<blockquote>' + $intro + (@($items) -join "`n`n") + '</blockquote>')
}

function Format-Generic([string[]]$lines) {
  (L '等你處理' 'Waiting for you'), ('<blockquote expandable>' + (Esc ((@($lines | ForEach-Object { Unbar $_ })) -join "`n")) + '</blockquote>')
}
