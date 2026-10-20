#!/bin/sh
# Golden tests for dialog.awk: every fixtures/<name>.txt screen must produce exactly
# <name>.dialog (headline + body) and <name>.options (the options that become buttons).
cd "$(dirname "$0")/.." || exit 2
pass=0 fail=0
out=$(mktemp -d)
for screen in tests/fixtures/*.txt; do
  name=$(basename "$screen" .txt)
  # the fingerprint exactly as notify.sh computes it
  awk -f dialog.awk "$screen" > "$out/$name.dialog"
  printf '%s' "$(cat "$out/$name.dialog")" | md5 | cut -c1-8 > "$out/$name.fp"
  awk -v part=options -f dialog.awk "$screen" > "$out/$name.options"
  for part in dialog options fp; do
    if cmp -s "$out/$name.$part" "tests/fixtures/$name.$part"; then
      pass=$((pass + 1))
    else
      fail=$((fail + 1)); echo "FAIL $name.$part"; diff "tests/fixtures/$name.$part" "$out/$name.$part"
    fi
  done
done
rm -rf "$out"
echo "pass=$pass fail=$fail"
echo "reached the end"
[ "$fail" -eq 0 ]
