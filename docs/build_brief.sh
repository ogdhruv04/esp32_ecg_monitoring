#!/usr/bin/env bash
# Rebuild the funder brief from brief.md.
#
#   ./build_brief.sh
#
# Edit brief.md (plain text), run this, and you get:
#   ECG_Ring_Project_Brief.html  - styled web version
#   ECG_Ring_Project_Brief.pdf   - print/email version
#   ECG_Ring_Project_Brief.docx  - Word / Google Docs, for editing with others
#
# Requires: pandoc, and Chrome on the Windows side (for the PDF step).
set -euo pipefail
cd "$(dirname "$0")"

CHROME="/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
WINWORK="/mnt/c/Users/dhruv/ecg_plan_export"

echo "-> markdown to html"
pandoc brief.md -f markdown -t html5 --wrap=none -o .brief_body.html

python3 - <<'PY'
import re, html

body = open('.brief_body.html').read()
css  = open('brief.css').read()
src  = open('brief.md').read()

def meta(field, default=''):
    m = re.search(rf'^{field}:\s*"(.*)"\s*$', src, re.M)
    return m.group(1) if m else default

title      = meta('title')
eyebrow    = meta('eyebrow')
standfirst = meta('standfirst')
footer     = meta('footer')

page = f"""<title>{html.escape(title)}</title>
<style>
{css}
</style>

<div class="wrap">
  <div class="eyebrow">{eyebrow}</div>
  <h1>{title}</h1>
  <p class="standfirst">{standfirst}</p>
{body}
  <div class="footer">{footer}</div>
</div>
"""
open('ECG_Ring_Project_Brief.html', 'w').write(page)
print("   wrote ECG_Ring_Project_Brief.html")
PY

rm -f .brief_body.html

echo "-> html to pdf"
mkdir -p "$WINWORK"
cp ECG_Ring_Project_Brief.html "$WINWORK/_brief_src.html"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="C:\\Users\\dhruv\\ecg_plan_export\\ECG_Ring_Project_Brief.pdf" \
  "C:\\Users\\dhruv\\ecg_plan_export\\_brief_src.html" 2>&1 | tail -1
cp "$WINWORK/ECG_Ring_Project_Brief.pdf" .
rm -f "$WINWORK/_brief_src.html"

echo "-> markdown to docx"
pandoc brief.md -f markdown -t docx -o ECG_Ring_Project_Brief.docx

echo
echo "Done:"
ls -la ECG_Ring_Project_Brief.* | awk '{printf "  %-34s %s\n", $9, $5}'
