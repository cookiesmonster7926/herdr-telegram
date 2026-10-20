#!/bin/sh
# Golden tests for dialog.awk: every fixtures/<name>.txt screen must produce exactly
# <name>.dialog (headline + body) and <name>.options (the options that become buttons), and the
# English wording <name>.en.dialog / <name>.en.options where those exist. The fingerprint (.fp)
# always comes from the default wording, whatever language the messages are shown in.
cd "$(dirname "$0")/.." || exit 2
pass=0 fail=0
out=$(mktemp -d)
for screen in tests/fixtures/*.txt; do
  name=$(basename "$screen" .txt)
  # the fingerprint exactly as notify.sh computes it
  awk -f dialog.awk "$screen" > "$out/$name.dialog"
  printf '%s' "$(cat "$out/$name.dialog")" | md5 | cut -c1-8 > "$out/$name.fp"
  awk -v part=options -f dialog.awk "$screen" > "$out/$name.options"
  awk -v lang=en -f dialog.awk "$screen" > "$out/$name.en.dialog"
  awk -v lang=en -v part=options -f dialog.awk "$screen" > "$out/$name.en.options"
  for part in dialog options fp en.dialog en.options; do
    case $part in en.*) [ -f "tests/fixtures/$name.$part" ] || continue ;; esac
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
