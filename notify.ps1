# ponytail: substring match on the event JSON; parse it if herdr adds other "blocked" fields
if ($env:HERDR_PLUGIN_EVENT_JSON -notmatch '"blocked"') { exit 0 }
# line 1 bot token, line 2 chat id, optional line 3 the name shown at the bottom of the message,
# optional line 4 the letter the Mac listener knows this machine by (its `machines` file; default w)
$cfg = @(Get-Content "$env:HERDR_PLUGIN_CONFIG_DIR\telegram" -Encoding UTF8 -ErrorAction Stop)
$token = $cfg[0].Trim(); $chat = $cfg[1].Trim()
$machine = if ($cfg.Count -ge 3 -and $cfg[2].Trim()) { $cfg[2].Trim() } else { $env:COMPUTERNAME }
$letter = if ($cfg.Count -ge 4 -and $cfg[3].Trim() -match '^[a-ln-z]$') { $cfg[3].Trim() } else { 'w' }
. "$PSScriptRoot\dialog.ps1"
# Windows PowerShell 5.1 does not offer TLS 1.2 by default, and api.telegram.org requires it
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# herdr prints UTF-8; read it as such instead of through the console code page (Big5 here)
function Invoke-Herdr {
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = (Get-Command herdr -ErrorAction Stop).Source
  $psi.Arguments = $args -join ' '
  $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $psi.RedirectStandardOutput = $true; $psi.StandardOutputEncoding = [Text.Encoding]::UTF8
  $p = [Diagnostics.Process]::Start($psi)
  $out = $p.StandardOutput.ReadToEnd(); $p.WaitForExit()
  if ($p.ExitCode -eq 0) { $out }
}

function Send([string]$text, [bool]$html) {
  $payload = @{ chat_id = $chat; text = $text }
  if ($html) { $payload.parse_mode = 'HTML' }
  if ($markup) { $payload.reply_markup = $markup }
  $bytes = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
  try {
    (Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/sendMessage" `
      -ContentType 'application/json; charset=utf-8' -Body $bytes -TimeoutSec 10).ok
  } catch { $false }
}

$pane = $env:HERDR_PANE_ID
$head = "agent $pane 需要你"; $meta = ''; $body = ''; $markup = ''
$info = try { Invoke-Herdr agent get $pane } catch { $null }
if ($info) {
  $a = ($info | ConvertFrom-Json).result.agent
  # the event also fires when leaving blocked; only notify if the agent is blocked right now
  if ($a.agent_status -ne 'blocked') { exit 0 }
  $tabs = Invoke-Herdr tab list --workspace $a.workspace_id
  $label = if ($tabs) { (($tabs | ConvertFrom-Json).result.tabs | Where-Object { $_.tab_id -eq $a.tab_id }).label }
  $where = '分頁 ' + $(if ($label) { $label } else { $a.tab_id }) + $(if ($a.cwd) { ' · ' + (Split-Path $a.cwd -Leaf) } else { '' })
  $meta = Esc ((@($a.terminal_title_stripped, $where) | Where-Object { $_ }) -join "`n")
  $screen = Invoke-Herdr agent read $pane --source visible
  if ($screen) {
    $lines = $screen -split "`r?`n"
    $d = @(Format-Dialog $lines)
    if ($d.Count -eq 2) {
      $head, $body = $d
      # one button per option: a1|machine|pane|option|fingerprint (machine = $letter; see the listener);
      # option "t" is the Tab that leaves a multi-select question
      $fp = Get-Fingerprint $d
      $rows = foreach ($o in @(Get-DialogOptions $lines)) {
        $cb = "a1|$letter|$pane|$(($o -split '\.')[0])|$fp"
        '[{"text":' + (ConvertTo-Json ($o -replace '^t\. ', '')) + ',"callback_data":' + (ConvertTo-Json $cb) + '}]'
      }
      # Telegram accepts the keyboard as a JSON-serialized string
      if ($rows) { $markup = '{"inline_keyboard":[' + (@($rows) -join ',') + ']}' }
    }
  }
}
# a quote box already leaves a gap around it, so next to one a single newline is enough
function Html {
  "<b>$head</b>" + $(if ($meta) { "`n$meta" }) +
    $(if ($body) { $(if ($body.StartsWith('<blockquote')) { "`n" } else { "`n`n" }) + $body }) +
    $(if ($body.EndsWith('</blockquote>')) { "`n" } else { "`n`n" }) + (Esc $machine)
}
# Telegram caps a message at 4096 characters
if ((Html).Length -gt 4000) { $body = '（內容太長，請到電腦上看）' }
$html = Html
# if the HTML or the buttons get rejected, still get the message itself through
if (-not (Send $html $true)) {
  $plain = $html -replace '<[^>]*>', '' -replace '&lt;', '<' -replace '&gt;', '>' -replace '&amp;', '&'
  if (-not (Send $plain $false)) { $markup = ''; Send $plain $false | Out-Null }
}
