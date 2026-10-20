#!/bin/sh
# First-time install, end to end, with nothing real touched: a throwaway HOME, and stand-ins for
# herdr, curl, launchctl and uv on PATH. Types a token and Enter like a new user would, then checks
# what install.sh left behind.
#   sh tests/install_test.sh
cd "$(dirname "$0")/.." || exit 2
repo=$(pwd)
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

out=$(printf 'TEST-TOKEN\n\n' | HOME="$t/home" PATH="$t/bin:/usr/bin:/bin:/usr/sbin:/sbin" sh install.sh 2>&1)
code=$?
pass=0 fail=0
check() { if eval "$2"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL $1"; fi; }
check "exit 0" '[ "$code" -eq 0 ]'
check "plugin linked from the repo" 'grep -qF "herdr plugin link $repo" "$calls"'
check "settings: token then chat id" '[ "$(cat "$t/config/telegram")" = "$(printf "TEST-TOKEN\n42")" ]'
check "settings readable by owner only" '[ "$(stat -f %Lp "$t/config/telegram")" = 600 ]'
check "old messages marked read" 'grep -q "getUpdates -d offset=7" "$calls"'
check "listener plist points at the repo" 'grep -qF "$repo/listener/listener.py" "$t/home/Library/LaunchAgents/io.github.herdr-telegram.listener.plist"'
check "plist is valid" 'plutil -lint "$t/home/Library/LaunchAgents/io.github.herdr-telegram.listener.plist" >/dev/null'
check "listener started" 'grep -q "launchctl bootstrap" "$calls"'
check "test message to the chat" 'grep -q "sendMessage -d chat_id=42" "$calls"'
check "token never printed" '! printf "%s" "$out" | grep -q TEST-TOKEN'
[ "$fail" -eq 0 ] || { echo "--- install.sh said:"; echo "$out"; echo "--- calls:"; cat "$calls"; }
rm -rf "$t"
echo "pass=$pass fail=$fail"
echo "reached the end"
[ "$fail" -eq 0 ]
