#!/usr/bin/env bash
# check_syntax.sh — parse-check a built command center.
#
#   ./check_syntax.sh /path/to/index.html
#
# The app is one 9,000-line inline script. A duplicate `const`, a stray brace,
# or a template literal closed in the wrong place does not degrade a panel — it
# stops the whole file parsing and the page renders blank with the error only in
# the devtools console. That failure looks identical to "the connector is down",
# so it must be caught at build time. Always run this before shipping a
# template change; it has already caught one duplicate declaration.
set -euo pipefail

FILE="${1:?usage: check_syntax.sh BUILT_INDEX_HTML}"
command -v node >/dev/null || { echo "node not found — cannot parse-check"; exit 2; }

JS="$(mktemp /tmp/cc-app.XXXXXX.js)"
trap 'rm -f "$JS"' EXIT

python3 - "$FILE" "$JS" <<'PY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
# Inline blocks only: a src= tag is the CDN chart library, not ours.
blocks = re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', src, re.S)
if not blocks:
    sys.exit("no inline script blocks found — wrong file?")
open(sys.argv[2], "w", encoding="utf-8").write("\n;\n".join(blocks))
print(f"  {len(blocks)} inline block(s), "
      f"{sum(len(b) for b in blocks):,} bytes of JS")
PY

if node --check "$JS"; then
  echo "  syntax OK"
else
  echo "  SYNTAX ERROR — do not ship this build" >&2
  exit 1
fi

# Placeholder leak check: a {{TOKEN}} that survived build.py means a panel
# renders the literal token to the user.
if grep -oE '\{\{[A-Za-z_][A-Za-z_0-9]*\}\}' "$FILE" | sort -u | grep .; then
  echo "  ERROR: unreplaced placeholders above" >&2
  exit 1
fi
echo "  no unreplaced placeholders"
