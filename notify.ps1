# this pane's last notification with buttons, by message id, until the agent stops waiting (see
# the end); runtime state, so in the state directory where herdr provides one
$stateDir = if ($env:HERDR_PLUGIN_STATE_DIR) { $env:HERDR_PLUGIN_STATE_DIR } else { $env:HERDR_PLUGIN_CONFIG_DIR }
$sent = if ($env:HERDR_PANE_ID) { Join-Path (Join-Path $stateDir 'sent') ($env:HERDR_PANE_ID -replace ':', '_') } else { '' }
# ponytail: substring match on the event JSON; parse it if herdr adds other "blocked" fields
$leaving = $env:HERDR_PLUGIN_EVENT_JSON -notmatch '"blocked"'
# any other status: the agent is not waiting; most such events have no message to take back
if ($leaving -and -not ($sent -and (Test-Path -LiteralPath $sent))) { exit 0 }
# line 1 bot token, line 2 chat id, optional line 3 the name shown at the bottom of the message,
# optional line 4 the letter the Mac listener knows this machine by (its `machines` file; default w)
$cfg = @(Get-Content "$env:HERDR_PLUGIN_CONFIG_DIR\telegram" -Encoding UTF8 -ErrorAction Stop)
$token = $cfg[0].Trim(); $chat = $cfg[1].Trim()
$machine = if ($cfg.Count -ge 3 -and $cfg[2].Trim()) { $cfg[2].Trim() } else { $env:COMPUTERNAME }
$letter = if ($cfg.Count -ge 4 -and $cfg[3].Trim() -match '^[a-ln-z]$') { $cfg[3].Trim() } else { 'w' }
. "$PSScriptRoot\dialog.ps1"
# the `language` file next to `telegram`: zh-TW (or zh) for Traditional Chinese, else English
$langWord = try { (Get-Content "$env:HERDR_PLUGIN_CONFIG_DIR\language" -TotalCount 1 -ErrorAction Stop).Trim() } catch { '' }
$lang = if ($langWord -eq 'zh-TW' -or $langWord -eq 'zh') { 'zh' } else { 'en' }
$DialogLang = $lang
# Windows PowerShell 5.1 does not offer TLS 1.2 by default, and api.telegram.org requires it
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

# the reply as an object, or $null if Telegram refused or could not be reached
function Post([string]$method, $payload) {
  $bytes = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress -Depth 5))
  try {
    $r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "https://api.telegram.org/bot$token/$method" `
      -ContentType 'application/json; charset=utf-8' -Body $bytes -TimeoutSec 10
    # the reply names no charset, and PowerShell 5.1 would then not read it as UTF-8
    [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json
  } catch { $null }
}

# the agent stopped waiting (answered on the computer, interrupted): its last message loses its
# buttons and says so. After a tap from the phone the listener takes them off itself, with what
# was answered; then Telegram refuses ("message is not modified", measured) and that note stays.
# The listener writes it within about 3 s of the agent moving on (a 0.4 s pause and two herdr
# --machine reads of about 1.2 s each), so wait $wait seconds first rather than race it
function Remove-Buttons([int]$wait) {
  if (-not ($sent -and (Test-Path -LiteralPath $sent))) { return }
  $id = "$(Get-Content -LiteralPath $sent -TotalCount 1)".Trim()
  Remove-Item -LiteralPath $sent -ErrorAction SilentlyContinue
  if ($id -notmatch '^[0-9]+$') { return }
  if ($wait -gt 0) { Start-Sleep -Seconds $wait }
  $r = Post 'editMessageReplyMarkup' @{ chat_id = $chat; message_id = [long]$id; reply_markup = @{ inline_keyboard = @() } }
  if (-not $r.ok) { return }
  $p = @{ chat_id = $chat; message_id = [long]$id
          text = $r.result.text + "`n`n" + (L 'agent 已經不在等你了' 'The agent is no longer waiting') }
  if ($r.result.entities) { $p.entities = @($r.result.entities) }
  Post 'editMessageText' $p | Out-Null
}
if ($leaving) { Remove-Buttons 5; exit 0 }

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
  Post 'sendMessage' $payload
}

$pane = $env:HERDR_PANE_ID
$head = "agent $pane " + (L '需要你' 'needs you'); $meta = ''; $body = ''; $markup = ''
$info = try { Invoke-Herdr agent get $pane } catch { $null }
if ($info) {
  $a = ($info | ConvertFrom-Json).result.agent
  # the event also fires when leaving blocked; only notify if the agent is blocked right now
  if ($a.agent_status -ne 'blocked') { Remove-Buttons 5; exit 0 }
  $tabs = Invoke-Herdr tab list --workspace $a.workspace_id
  $label = if ($tabs) { (($tabs | ConvertFrom-Json).result.tabs | Where-Object { $_.tab_id -eq $a.tab_id }).label }
  $where = (L '分頁 ' 'tab ') + $(if ($label) { $label } else { $a.tab_id }) + $(if ($a.cwd) { ' · ' + (Split-Path $a.cwd -Leaf) } else { '' })
  $meta = Esc ((@($a.terminal_title_stripped, $where) | Where-Object { $_ }) -join "`n")
  $screen = Invoke-Herdr agent read $pane --source visible
  if ($screen) {
    $lines = $screen -split "`r?`n"
    # the fingerprint is taken from the default wording, so it does not depend on the language
    # setting of either machine
    $DialogLang = ''
    $fp = Get-Fingerprint @(Format-Dialog $lines)
    $DialogLang = $lang
    $d = @(Format-Dialog $lines)
    if ($d.Count -eq 2) {
      $head, $body = $d
      # one button per option: a1|machine|pane|option|fingerprint (machine = $letter; see the listener);
      # option "t" is "done with this multi-select question"
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
if ((Html).Length -gt 4000) { $body = L '（內容太長，請到電腦上看）' '(Too long to show here; see it on the computer)' }
$html = Html
# if the HTML or the buttons get rejected, still get the message itself through
$r = Send $html $true
if (-not $r.ok) {
  $plain = $html -replace '<[^>]*>', '' -replace '&lt;', '<' -replace '&gt;', '>' -replace '&amp;', '&'
  $r = Send $plain $false
  if (-not $r.ok) { $markup = ''; $r = Send $plain $false }
}
# a message with buttons is remembered until the agent stops waiting. If that happened while it
# was on its way, the event found nothing to take back, so look once more now (no tap yet to wait for)
if ($r.ok -and $markup -and $sent) {
  New-Item -ItemType Directory -Force -Path (Split-Path $sent) | Out-Null
  Set-Content -LiteralPath $sent -Value $r.result.message_id
  $now = try { (Invoke-Herdr agent get $pane | ConvertFrom-Json).result.agent.agent_status } catch { $null }
  if ($now -and $now -ne 'blocked') { Remove-Buttons 0 }
}
