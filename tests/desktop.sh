#!/bin/sh
# Runs the same golden tests against dialog.ps1 on a Windows machine over ssh (OpenSSH server with
# PowerShell as its shell), so the Mac and Windows notifications stay byte-for-byte identical.
#   sh tests/desktop.sh <ssh-host> [remote dir, relative to the remote home]
cd "$(dirname "$0")/.." || exit 2
host=${1:?usage: sh tests/desktop.sh <ssh-host> [remote-dir]}
remote=${2:-herdr-telegram-test}
ssh -o BatchMode=yes "$host" "Remove-Item -Recurse -Force $remote -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $remote/fixtures, $remote/out | Out-Null" || exit 2
scp -q dialog.ps1 tests/parity.ps1 "$host:$remote/" && scp -q tests/fixtures/*.txt "$host:$remote/fixtures/" || exit 2
ssh -o BatchMode=yes "$host" "powershell -NoProfile -ExecutionPolicy Bypass -File $remote/parity.ps1 -dir $remote" | grep -q done || { echo "parity.ps1 did not finish"; exit 2; }
out=$(mktemp -d)
scp -q "$host:$remote/out/*" "$out/" || exit 2
ssh -o BatchMode=yes "$host" "Remove-Item -Recurse -Force $remote"
pass=0 fail=0
for golden in tests/fixtures/*.dialog tests/fixtures/*.options tests/fixtures/*.fp; do
  name=$(basename "$golden")
  if cmp -s "$golden" "$out/$name"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL $name"; diff "$golden" "$out/$name"; fi
done
rm -rf "$out"
echo "pass=$pass fail=$fail"
echo "reached the end"
[ "$fail" -eq 0 ]
