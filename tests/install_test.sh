#!/bin/sh
# First-time install, end to end, with nothing real touched: a throwaway HOME, and stand-ins for
# herdr, curl, launchctl and uv on PATH. Types what a new user would (token, Enter, language) and
# checks what install.sh left behind. Runs twice: choosing Chinese, and taking the default.
#   sh tests/install_test.sh
cd "$(dirname "$0")/.." || exit 2
repo=$(pwd)
pass=0 fail=0
check() { if eval "$2"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL [$round] $1"; fi; }

# install_once <what the user types at the language prompt>: sets t, calls, out, code
install_once() {
  t=$(mktemp -d)
  mkdir -p "$t/bin" "$t/home"
  calls="$t/calls.log"
  cat > "$t/bin/herdr" <<EOF
#!/bin/sh
echo "herdr \$*" >> "$calls"
case "\$*" in
  "plugin config-dir herdr-telegram") echo "$t/config" ;;
  "plugin list") ;;
esac
EOF
  cat > "$t/bin/curl" <<EOF
#!/bin/sh
echo "curl \$*" >> "$calls"
case "\$*" in
  *getMe*) echo '{"ok":true,"result":{"username":"testbot"}}' ;;
  *offset=*) echo '{"ok":true,"result":[]}' ;;
  *getUpdates*) echo '{"ok":true,"result":[{"update_id":5,"message":{"chat":{"id":42},"text":"/start"}},{"update_id":6,"message":{"chat":{"id":42},"text":"hi"}}]}' ;;
  *sendMessage*) echo '{"ok":true}' ;;
esac
EOF
  cat > "$t/bin/launchctl" <<EOF
#!/bin/sh
echo "launchctl \$*" >> "$calls"
case "\$1" in bootstrap) echo "listening" >> "$t/home/Library/Logs/herdr-telegram.log" ;; esac
EOF
  printf '#!/bin/sh\n' > "$t/bin/uv"
  chmod +x "$t/bin/"*
  out=$(printf 'TEST-TOKEN\n\n%s\n' "$1" | HOME="$t/home" PATH="$t/bin:/usr/bin:/bin:/usr/sbin:/sbin" sh install.sh 2>&1)
  code=$?
}

report() {
  [ "$fail" -eq "$1" ] || { echo "--- install.sh said:"; echo "$out"; echo "--- calls:"; cat "$calls"; }
  rm -rf "$t"
}

round=zh-TW
install_once zh-TW
before=$fail
check "exit 0" '[ "$code" -eq 0 ]'
check "plugin linked from the repo" 'grep -qF "herdr plugin link $repo" "$calls"'
check "settings: token then chat id" '[ "$(cat "$t/config/telegram")" = "$(printf "TEST-TOKEN\n42")" ]'
check "settings readable by owner only" '[ "$(stat -f %Lp "$t/config/telegram")" = 600 ]'
check "old messages marked read" 'grep -q "getUpdates -d offset=7" "$calls"'
check "language saved" '[ "$(cat "$t/config/language")" = zh-TW ]'
check "listener plist points at the repo" 'grep -qF "$repo/listener/listener.py" "$t/home/Library/LaunchAgents/io.github.herdr-telegram.listener.plist"'
check "plist is valid" 'plutil -lint "$t/home/Library/LaunchAgents/io.github.herdr-telegram.listener.plist" >/dev/null'
check "listener started" 'grep -q "launchctl bootstrap" "$calls"'
check "test message to the chat, in Chinese" 'grep "sendMessage -d chat_id=42" "$calls" | grep -q "設定好了"'
check "token never printed" '! printf "%s" "$out" | grep -q TEST-TOKEN'
report "$before"

round=default
install_once ""
before=$fail
check "exit 0" '[ "$code" -eq 0 ]'
check "English when nothing is chosen" '[ "$(cat "$t/config/language")" = en ]'
check "test message in English" 'grep "sendMessage -d chat_id=42" "$calls" | grep -q "is ready on"'
report "$before"

echo "pass=$pass fail=$fail"
echo "reached the end"
[ "$fail" -eq 0 ]
