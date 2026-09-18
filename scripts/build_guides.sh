#!/usr/bin/env bash
# Build the illustrated guides in docs/guides/ into one PDF and one Word file.
#
#     scripts/build_guides.sh [output-directory]
#
# Default output directory: ~/Desktop/Consilium-deliverables (outside the
# repository: the built files are several tens of megabytes of pictures and
# are regenerated, not versioned).
#
# Produces:
#   Consilium-User-and-Configuration-Guide.pdf
#   Consilium-User-and-Configuration-Guide.docx
#
# How. pandoc combines README.md and the twelve chapters, in order, into
#   * a Word document (pandoc's own .docx writer, with a title page and a table
#     of contents that Word fills in when the document is opened), and
#   * an HTML book, which Google Chrome prints to PDF. No LaTeX engine is
#     needed, and nothing is downloaded: Chrome is the one already installed,
#     driven through the Playwright package in the repository's .venv. If that
#     is unavailable, LibreOffice (soffice) converts the Word file instead.
#
# A Lua filter (written below) makes the combined document work:
#   * a link to another chapter becomes a link inside the document;
#   * a link to a file outside docs/guides/ becomes plain text naming the file;
#   * each chapter starts on a new page;
#   * a picture taller than it is wide is limited in height, so that a
#     full-page screenshot fits on a printed page.
#
# Needs: pandoc (PANDOC=... to override), and either the .venv with Playwright
# and Google Chrome, or LibreOffice.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
GUIDES="$REPO/docs/guides"
OUT="${1:-$HOME/Desktop/Consilium-deliverables}"
NAME="Consilium-User-and-Configuration-Guide"
PANDOC="${PANDOC:-$(command -v pandoc || echo /opt/homebrew/bin/pandoc)}"
PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
SOFFICE="${SOFFICE:-$(command -v soffice || echo /Applications/LibreOffice.app/Contents/MacOS/soffice)}"

[ -x "$PANDOC" ] || { echo "pandoc not found (set PANDOC=...)" >&2; exit 1; }
mkdir -p "$OUT"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/consilium-guides.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

CHAPTERS=(README.md)
for f in "$GUIDES"/[0-9][0-9]-*.md; do CHAPTERS+=("$(basename "$f")"); done
TODAY="$(date +%-d\ %B\ %Y)"
SHOTS_TAKEN="$(sed -n 's/.*"generated_at": "\([0-9-]*\)T.*/\1/p' "$GUIDES/images/manifest.json" | head -1)"

# --------------------------------------------------------------------- filter
cat > "$WORK/guides.lua" <<'LUA'
-- Chapter links, outside links, page breaks and picture sizes for the
-- combined guide. See scripts/build_guides.sh.
local first_heading = {}   -- "forums.md" -> identifier of that file's first heading

local function png_size(path)
  local f = io.open(path, "rb")
  if not f then return nil end
  local head = f:read(24); f:close()
  if not head or #head < 24 or head:sub(2, 4) ~= "PNG" then return nil end
  local function u32(s) local a, b, c, d = s:byte(1, 4); return ((a * 256 + b) * 256 + c) * 256 + d end
  return u32(head:sub(17, 20)), u32(head:sub(21, 24))
end

local collect = {
  Header = function(h)
    local prefix = h.identifier:match("^(.-%.md)__")
    if prefix and not first_heading[prefix] then first_heading[prefix] = h.identifier end
  end,
}

local rewrite = {
  Link = function(l)
    local t = l.target
    if t:match("^#[^_]+%.md$") then                      -- a whole chapter
      local id = first_heading[t:sub(2)]
      if id then l.target = "#" .. id end
      return l
    end
    if t:match("^%.%./") or (t:match("%.md") and not t:match("^#")) then
      -- a document outside the guides: name it rather than link to nothing
      local file = t:gsub("^%.%./", "docs/"):gsub("#.*$", "")
      local out = pandoc.List(l.content)
      if pandoc.utils.stringify(l.content) ~= file then
        out:insert(pandoc.Str(" ("))
        out:insert(pandoc.Code(file))
        out:insert(pandoc.Str(")"))
      end
      return out
    end
    return l
  end,
  Image = function(img)
    local src = img.src
    local w, h = png_size(src)
    if w and h then
      if FORMAT:match("docx") then
        -- Word places a picture at its natural size unless told otherwise.
        if h / w > 1.25 then img.attributes.height = "8.3in" else img.attributes.width = "6.3in" end
      else
        if h / w > 1.25 then img.classes:insert("tall") end
      end
    end
    return img
  end,
  Header = function(h)
    if h.level == 1 and FORMAT:match("docx") then
      local brk = pandoc.RawBlock("openxml", '<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
      return { brk, h }
    end
  end,
}

return { collect, rewrite }
LUA

# ------------------------------------------------------------------ the book
cat > "$WORK/book.css" <<'CSS'
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
html { font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; color: #1b2430; }
body { max-width: none; margin: 0; padding: 0; line-height: 1.45; }
h1, h2, h3 { color: #1d3557; line-height: 1.2; break-after: avoid; }
h1 { font-size: 22pt; border-bottom: 2px solid #1d3557; padding-bottom: 6px; break-before: page; margin-top: 0; }
h2 { font-size: 15pt; margin-top: 1.6em; }
h3 { font-size: 12pt; }
p, li { orphans: 3; widows: 3; }
img { display: block; max-width: 100%; margin: 8px auto 2px; border: 1px solid #c9d1db; }
img.tall { max-height: 235mm; width: auto; }
figure { margin: 10px 0 14px; break-inside: avoid; }
figcaption { font-size: 8.5pt; color: #5b6675; text-align: center; font-style: italic; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 8px 0 12px; }
th, td { border: 1px solid #c9d1db; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #eef2f7; }
tr { break-inside: avoid; }
code { font-family: Menlo, Consolas, monospace; font-size: 8.8pt; background: #f2f4f7; padding: 0 2px; }
pre { background: #f2f4f7; padding: 8px; font-size: 8.5pt; white-space: pre-wrap; break-inside: avoid; }
blockquote { border-left: 4px solid #0f6c8c; background: #f0f6f9; margin: 10px 0; padding: 6px 12px; }
a { color: #0f6c8c; text-decoration: none; }
#title-block-header { break-after: page; text-align: center; padding-top: 70mm; }
#title-block-header .title { font-size: 30pt; border: 0; color: #1d3557; }
#title-block-header .subtitle { font-size: 14pt; color: #0f6c8c; }
#title-block-header .date { margin-top: 40mm; color: #5b6675; }
nav#TOC { break-after: page; }
nav#TOC > ul { columns: 1; }
nav#TOC ul { list-style: none; padding-left: 1.2em; }
nav#TOC > ul > li { margin-top: 6px; font-weight: 600; }
nav#TOC > ul > li li { font-weight: normal; }
nav#TOC::before { content: "Contents"; display: block; font-size: 20pt; color: #1d3557; font-weight: 700; margin-bottom: 10px; }
CSS

COMMON=(--from=markdown+pipe_tables+grid_tables-smart --file-scope
  --lua-filter="$WORK/guides.lua"
  --metadata=title:"Consilium"
  --metadata=subtitle:"User and configuration guide"
  --metadata=date:"$TODAY${SHOTS_TAKEN:+ · screenshots taken $SHOTS_TAKEN}"
  --toc --toc-depth=2)

cd "$GUIDES"
echo "Building the Word document"
"$PANDOC" "${COMMON[@]}" "${CHAPTERS[@]}" --resource-path="$GUIDES" \
  -o "$OUT/$NAME.docx"

echo "Building the HTML book"
"$PANDOC" "${COMMON[@]}" --standalone --css="$WORK/book.css" \
  --metadata=pagetitle:"Consilium: user and configuration guide" \
  "${CHAPTERS[@]}" -o "$WORK/book.html"
# Pictures are referenced relative to docs/guides; the book lives elsewhere.
sed -i.bak "s#src=\"images/#src=\"file://$GUIDES/images/#g" "$WORK/book.html"

echo "Printing the PDF"
if "$PYTHON" - "$WORK/book.html" "$OUT/$NAME.pdf" <<'PY'
import sys
from playwright.sync_api import sync_playwright
src, dst = sys.argv[1], sys.argv[2]
with sync_playwright() as pw:
	browser = pw.chromium.launch(channel="chrome")
	page = browser.new_page()
	page.goto("file://" + src, wait_until="load")
	page.wait_for_timeout(1500)
	page.pdf(path=dst, format="A4", print_background=True, display_header_footer=True,
		header_template="<div></div>",
		footer_template='<div style="font-size:7pt;color:#5b6675;width:100%;padding:0 16mm;display:flex;justify-content:space-between;">'
			'<span>Consilium — user and configuration guide</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
		margin={"top": "16mm", "bottom": "18mm", "left": "14mm", "right": "14mm"})
	browser.close()
PY
then
	:
elif [ -x "$SOFFICE" ]; then
	echo "  Chrome unavailable; converting the Word document with LibreOffice"
	"$SOFFICE" --headless --convert-to pdf --outdir "$OUT" "$OUT/$NAME.docx" >/dev/null
else
	echo "Neither Chrome (through the .venv's Playwright) nor LibreOffice is available" >&2
	exit 1
fi

pages="$(mdls -raw -name kMDItemNumberOfPages "$OUT/$NAME.pdf" 2>/dev/null || true)"
if ! [[ "$pages" =~ ^[0-9]+$ ]]; then
	pages="$("$PYTHON" -c "import re,sys;print(len(re.findall(rb'/Type\s*/Page[^s]', open(sys.argv[1],'rb').read())))" "$OUT/$NAME.pdf")"
fi
echo
ls -lh "$OUT/$NAME.pdf" "$OUT/$NAME.docx" | awk '{print "  " $5 "  " $NF}'
echo "  $pages pages, ${#CHAPTERS[@]} files (index and chapters)"
