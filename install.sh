#!/bin/sh
# herdr-telegram setup for macOS: links the herdr plugin, asks for your bot token once (the chat id
# is found for you), and keeps the reply listener running in the background with launchd.
# Safe to run again (it updates the listener and keeps your settings).
#   ./install.sh               install or update
#   ./install.sh --uninstall   stop the listener and unlink the plugin (settings are kept)
set -eu
cd "$(dirname "$0")"
repo=$(pwd)
id=herdr-telegram
label=io.github.herdr-telegram.listener
plist="$HOME/Library/LaunchAgents/$label.plist"
log="$HOME/Library/Logs/herdr-telegram.log"
domain="gui/$(id -u)"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
api() { method=$1; shift; curl -s -m 20 "https://api.telegram.org/bot$token/$method" "$@"; }

if [ "${1:-}" = --uninstall ]; then
  launchctl bootout "$domain/$label" 2>/dev/null || true
  rm -f "$plist"
  herdr plugin unlink "$id" >/dev/null 2>&1 || true
  say "Removed the listener and the plugin link."
  say "Your bot settings are kept in $(herdr plugin config-dir "$id" 2>/dev/null || echo 'the plugin config directory')."
  exit 0
fi

[ "$(uname)" = Darwin ] || die "this script is for macOS (see README for Windows)"
for t in herdr jq curl uv awk md5; do
  command -v "$t" >/dev/null 2>&1 || die "'$t' not found; see Requirements in README.md"
done

# 1. the plugin: herdr runs notify.sh whenever an agent's status changes
if ! herdr plugin list 2>/dev/null | grep -qF "[local:$repo]"; then
  herdr plugin unlink "$id" >/dev/null 2>&1 || true   # linked from another folder before
  herdr plugin link "$repo" >/dev/null
fi
say "✓ plugin linked: $repo"

# the listener holds the bot's only update connection; stop it while this script talks to the bot
launchctl bootout "$domain/$label" 2>/dev/null || true

# 2. the bot: token and chat id, stored outside the repo (readable by you only)
dir=$(herdr plugin config-dir "$id")
cfg="$dir/telegram"
if [ -s "$cfg" ]; then
  token=$(sed -n 1p "$cfg")
  say "✓ bot settings found: $cfg"
else
  say ""
  say "In Telegram, open @BotFather, send /newbot, and follow it. It ends with a token like 123456:ABC-..."
  trap 'stty echo 2>/dev/null || true' EXIT INT
  printf 'Paste the token (hidden): '
  stty -echo 2>/dev/null || true; read -r token; stty echo 2>/dev/null || true; printf '\n'
  bot=$(api getMe | jq -r 'select(.ok) | .result.username')
  [ -n "$bot" ] || die "Telegram did not accept that token"
  say "Now open https://t.me/$bot in Telegram, press Start (or send it any message), then press Enter here."
  read -r _
  updates=$(api getUpdates)
  chat=$(printf '%s' "$updates" | jq -r '[.result[] | .message.chat.id // empty] | last // empty')
  [ -n "$chat" ] || die "no message reached @$bot yet; send it one and run ./install.sh again"
  # mark those messages as read, or the listener would answer them
  last=$(printf '%s' "$updates" | jq -r '[.result[].update_id] | max')
  api getUpdates -d offset=$((last + 1)) -d timeout=0 >/dev/null
  mkdir -p "$dir"
  (umask 077; printf '%s\n%s\n' "$token" "$chat" > "$cfg")
  say "✓ bot settings saved: $cfg"
fi

# 3. the listener: turns button taps and replies into key presses; restarted at login and on crashes
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(command -v uv)</string><string>run</string><string>--no-project</string>
    <string>--script</string><string>$repo/listener/listener.py</string>
  </array>
  <key>WorkingDirectory</key><string>$repo/listener</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$(dirname "$(command -v herdr)"):$(dirname "$(command -v uv)"):/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$log</string>
  <key>StandardErrorPath</key><string>$log</string>
</dict>
</plist>
EOF
lines=0
[ -f "$log" ] && lines=$(wc -l < "$log")
launchctl bootstrap "$domain" "$plist"
i=0
until tail -n +"$((lines + 1))" "$log" 2>/dev/null | grep -q listening; do
  i=$((i + 1)); [ "$i" -le 60 ] || die "the listener did not start; see $log"
  sleep 1
done
say "✓ listener running (log: $log)"

name=$(scutil --get ComputerName)
api sendMessage -d chat_id="$(sed -n 2p "$cfg")" \
  --data-urlencode text="herdr-telegram is ready on $name. When an agent waits for you, a message with buttons shows up here." \
  | grep -q '"ok":true' && say "✓ test message sent to Telegram" || say "! could not send the test message; check the token and chat id in $cfg"
