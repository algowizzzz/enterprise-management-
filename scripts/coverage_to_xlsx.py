#!/usr/bin/env python3
"""Turn the measured requirements-coverage matrix into an Excel workbook.

    .venv/bin/python scripts/coverage_to_xlsx.py [--out PATH] [--repo PATH]

Reads three Markdown files and writes one workbook:

  * docs/delivery/REQUIREMENTS-COVERAGE.md   the measured matrix (source of truth)
  * docs/product/01-requirements-baseline.md full statement, priority, planned
                                             satisfaction and decision marks
  * docs/delivery/EPICS.md                   stories, sizes, epic state and the
                                             requirement ids each epic traces to

The Markdown stays authoritative. The workbook is a generated view of it: edit
the Markdown and run this again. Parsing is driven by table *headers*, not by
section numbers or column positions, so a re-measured matrix with re-ordered or
added columns still regenerates. Anything that cannot be parsed is not dropped
silently: it is printed, written to the "Parse log" tab, and makes the script
exit 2 when --strict is given.

Summary counts are COUNTIFS formulas over the "All requirements" sheet, so
editing a class or result in the workbook updates the summary and the chart.
The file is written with "recalculate on open" set; a spreadsheet application
computes the formulas when it opens the file.

Only openpyxl is needed. Nothing here reaches the network.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.table import Table, TableStyleInfo

REPO_DEFAULT = Path(__file__).resolve().parent.parent
COVERAGE_MD = Path("docs/delivery/REQUIREMENTS-COVERAGE.md")
BASELINE_MD = Path("docs/product/01-requirements-baseline.md")
EPICS_MD = Path("docs/delivery/EPICS.md")
OUT_DEFAULT = Path.home() / "Desktop" / "Consilium-deliverables" / "Consilium-Requirements-Coverage.xlsx"

MODULES = [  # (id prefix, module code, sheet name, long name)
    ("G", "CGF", "Governance", "Committee & Governance Forum"),
    ("P", "POL", "Policy", "Policy"),
    ("E", "ESC", "Escalation", "Escalation"),
    ("O", "Supplementary", "Supplementary", "Supplementary (O-1…O-7)"),
]
PREFIX_TO_MODULE = {p: m for p, m, _, _ in MODULES}
CLASSES = ["a", "b", "c", "d"]
CLASS_LABEL = {
    "a": "(a) Portal screen",
    "b": "(b) Desk / config / job by design",
    "c": "(c) Partly reachable",
    "d": "(d) Not implemented (whole or mandatory part)",
}
PRIMARY_DOCTYPE = {"G": "Governance Forum", "P": "Governing Document", "E": "Escalation Matter"}
MODULE_PAGES = {  # fallback only, for class (a) rows whose text says "register"/"detail" without a route
    "G": {"register": "/forums", "detail": "/forum?name=…"},
    "P": {"register": "/policies", "detail": "/policy?name=…"},
    "E": {"register": "/escalations", "detail": "/escalation?name=…"},
}
CLASS_WORDS = {  # the Requirements map spells the class out
    "a": "(a) Through a purpose-built portal screen",
    "b": "(b) Through the desk, configuration or a scheduled job — by design",
    "c": "(c) Partly: the backend exists, but a step has no screen, is desk-only where a custom screen is "
         "called for, or is reachable only from code",
    "d": "(d) Not implemented, wholly or in a mandatory clause",
}
REQ_ID_RE = re.compile(r"\b([GPEO])-(\d{1,3})\b")
REQ_RANGE_RE = re.compile(r"\b([GPEO])-(\d{1,3})\s*(?:…|\.\.\.?|–|—|-|to)\s*\1-(\d{1,3})\b")

# ---------------------------------------------------------------- styling

FONT = "Arial"
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(name=FONT, bold=True, color="FFFFFF", size=10)
BODY_FONT = Font(name=FONT, size=10)
BOLD = Font(name=FONT, size=10, bold=True)
TITLE_FONT = Font(name=FONT, size=16, bold=True, color="1F3A5F")
SUBTITLE_FONT = Font(name=FONT, size=12, bold=True, color="1F3A5F")
NOTE_FONT = Font(name=FONT, size=9, italic=True, color="555555")
WRAP_TOP = Alignment(wrap_text=True, vertical="top")
CENTER_TOP = Alignment(horizontal="center", vertical="top", wrap_text=True)
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# One palette for the class cells, the result cells and the chart series.
CLASS_COLOURS = {"a": "C6EFCE", "b": "DDEBF7", "c": "FFEB9C", "d": "FFC7CE"}
CHART_COLOURS = {"a": "4E9A57", "b": "4F81BD", "c": "E0A526", "d": "C0504D"}
RESULT_COLOURS = {
    "Pass": "C6EFCE",
    "Pass (qualified)": "E2EFDA",
    "No direct test": "FFEB9C",
    "Fail": "FFC7CE",
}
STATE_COLOURS = {  # Deployment readiness and Epics state words
    "open": "FFC7CE",
    "changed": "FFEB9C",
    "new finding": "FFEB9C",
    "superseded": "C6EFCE",
    "done": "C6EFCE",
    "partial": "FFEB9C",
    "mostly done": "E2EFDA",
    "in progress": "DDEBF7",
    "not started": "FFC7CE",
}


# ---------------------------------------------------------------- parse log


@dataclass
class Log:
    entries: list[tuple[str, str, str]] = field(default_factory=list)  # level, where, message

    def warn(self, where: str, msg: str) -> None:
        self.entries.append(("WARN", where, msg))

    def info(self, where: str, msg: str) -> None:
        self.entries.append(("INFO", where, msg))

    @property
    def warnings(self) -> list[tuple[str, str, str]]:
        return [e for e in self.entries if e[0] == "WARN"]


# ---------------------------------------------------------------- Markdown helpers


def clean(text: str) -> str:
    """Markdown cell → plain text a spreadsheet reader can use."""
    t = text.strip()
    t = re.sub(r"~~(.+?)~~", r"[struck through: \1]", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)  # links → their text
    t = t.replace("`", "")
    t = t.replace("<br>", "\n").replace("<br/>", "\n")
    return re.sub(r"[ \t]+", " ", t).strip()


def split_row(line: str) -> list[str]:
    """Split a Markdown table row on pipes, ignoring pipes in code spans or escaped."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, buf, in_code, i = [], [], False, 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf))
    return [c.strip() for c in cells]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", line.strip()))


@dataclass
class MdTable:
    header: list[str]
    rows: list[tuple[int, list[str]]]  # (1-based line number, raw cells)
    heading: str  # nearest heading above the table
    headings: list[str]  # full heading path (h1..hN) above the table
    line: int

    def col(self, *needles: str) -> int | None:
        """Index of the first header containing any needle (case-insensitive)."""
        low = [clean(h).lower() for h in self.header]
        for n in needles:
            for i, h in enumerate(low):
                if n.lower() in h:
                    return i
        return None


def parse_tables(text: str) -> list[MdTable]:
    lines = text.splitlines()
    tables: list[MdTable] = []
    path: dict[int, str] = {}
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            path = {k: v for k, v in path.items() if k < level}
            path[level] = clean(m.group(2))
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            header = [clean(c) for c in split_row(line)]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append((j + 1, split_row(lines[j])))
                j += 1
            heads = [path[k] for k in sorted(path)]
            tables.append(MdTable(header, rows, heads[-1] if heads else "", heads, i + 1))
            i = j
            continue
        i += 1
    return tables


def ids_in(text: str) -> list[str]:
    """Requirement ids named in text, expanding ranges such as 'E-1 … E-6'."""
    found: list[str] = []
    for m in REQ_RANGE_RE.finditer(text):
        p, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        if a <= b <= a + 60:
            found += [f"{p}-{n}" for n in range(a, b + 1)]
    found += [f"{p}-{n}" for p, n in REQ_ID_RE.findall(text)]
    return sorted(set(found), key=req_sort_key)


def req_sort_key(rid: str) -> tuple[int, int]:
    order = {"G": 0, "P": 1, "E": 2, "O": 3}
    p, n = rid.split("-")
    return order.get(p, 9), int(n)


# ---------------------------------------------------------------- source models


@dataclass
class Requirement:
    rid: str
    module: str
    title: str = ""  # short, from the matrix
    baseline_title: str = ""
    statement: str = ""
    baseline_module: str = ""
    priority: str = ""
    planned: str = ""
    delta: str = ""
    satisfies: str = ""
    klass: str = ""
    klass_raw: str = ""
    demo: str = ""
    tests: str = ""
    result_raw: str = ""
    result: str = ""
    evidence: str = ""
    cited_tests: int | None = None
    gap_refs: list[str] = field(default_factory=list)
    epics: list[str] = field(default_factory=list)
    stories: int = 0
    src_line: int = 0
    satisfies_raw: str = ""
    demo_raw: str = ""
    tests_raw: str = ""
    portal: list[str] = field(default_factory=list)
    workspace: list[str] = field(default_factory=list)
    code: list[str] = field(default_factory=list)
    test_refs: list[dict] = field(default_factory=list)


def classify_result(raw: str) -> tuple[str, str]:
    """(result status, test evidence) from a Result cell such as '✅ (engine only)'."""
    t = raw.strip()
    low = t.lower()
    if "❌" in t or re.search(r"\bfail", low):
        return "Fail", "Failing test"
    if "⚠" in t:
        return "No direct test", "No direct test"
    if "✅" in t or low.startswith("pass"):
        qualified = bool(re.search(r"\(.+\)", t)) or len(clean(t).replace("✅", "").strip()) > 0
        return ("Pass (qualified)" if qualified else "Pass"), "Direct test"
    return "Unknown", "Unknown"


def count_cited_tests(tests: str) -> int | None:
    """Rough count of test methods a Tests cell cites: '(all N)' blocks plus named methods."""
    if not tests or clean(tests).lower().startswith("none"):
        return 0
    total = sum(int(n) for n in re.findall(r"\(all (\d+)", tests))
    # Individually named methods, not those already inside an '(all N)' class.
    total += len(re.findall(r"(?:…|\.)test_\w+", tests))
    total += len(re.findall(r"^\s*test_\w+|[;,]\s*test_\w+", tests))
    return total or None


def parse_coverage(text: str, log: Log) -> dict:
    tables = parse_tables(text)
    out: dict = {"requirements": [], "screens": [], "classes": {}, "stated": {}, "evidence": [],
                 "gaps": [], "readiness": [], "meta": {}}

    m = re.search(r"Date measured:\**\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
    out["meta"]["measured"] = m.group(1) if m else ""
    if not m:
        log.warn("coverage §Method", "no 'Date measured:' line found")
    runs = re.findall(r"Ran (\d+) tests in ([0-9.]+)s\s*\n\s*(OK|FAILED[^\n]*)", text)
    if runs:
        out["meta"]["tests_run"], out["meta"]["run_secs"], out["meta"]["run_outcome"] = runs[0]
    else:
        log.warn("coverage §Method", "no 'Ran N tests … OK/FAILED' block found")
    m = re.search(r"\*\*(\d+) passed, (\d+) failed\.\*\*", text)
    if m:
        out["meta"]["passed"], out["meta"]["failed"] = m.group(1), m.group(2)

    seen: set[str] = set()
    for t in tables:
        hdr = " ".join(t.header).lower()
        # ---- matrix: an ID column plus Reachable, Test and Result columns
        if (t.col("id") == 0 and t.col("close") is None and t.col("result") is not None
                and any(clean(h).lower().startswith(("reachable", "class")) for h in t.header)):
            cols = {
                "title": t.col("requirement"),
                "satisfies": t.col("what satisfies"),
                "klass": next((i for i, h in enumerate(t.header)
                               if clean(h).lower().startswith(("reachable", "class"))), None),
                "demo": t.col("demo"),
                "tests": t.col("test"),
                "result": t.col("result"),
            }
            for key, idx in cols.items():
                if idx is None:
                    log.warn(f"coverage line {t.line}", f"matrix table under '{t.heading}' has no '{key}' column")
            for ln, cells in t.rows:
                where = f"coverage line {ln}"
                if len(cells) != len(t.header):
                    log.warn(where, f"row has {len(cells)} cells, header has {len(t.header)}; parsed by position anyway")
                rid = clean(cells[0]) if cells else ""
                mm = REQ_ID_RE.fullmatch(rid)
                if not mm:
                    log.warn(where, f"first cell '{rid[:40]}' is not a requirement id; row skipped")
                    continue
                if rid in seen:
                    log.warn(where, f"{rid} appears twice in the matrix; later row kept")

                def cell(key: str) -> str:
                    idx = cols[key]
                    return cells[idx] if idx is not None and idx < len(cells) else ""

                req = Requirement(rid=rid, module=PREFIX_TO_MODULE[mm.group(1)], src_line=ln)
                req.title = clean(cell("title"))
                req.satisfies = clean(cell("satisfies"))
                req.satisfies_raw, req.tests_raw = cell("satisfies"), cell("tests")
                req.demo_raw = cell("demo")
                req.klass_raw = clean(cell("klass"))
                km = re.match(r"^\(?([a-dA-D])\)?(?:\W|$)", req.klass_raw)
                req.klass = km.group(1).lower() if km else ""
                if not km:
                    log.warn(where, f"{rid}: reachability '{req.klass_raw}' is not a class a–d")
                req.demo = clean(cell("demo"))
                req.tests = clean(cell("tests"))
                req.result_raw = clean(cell("result"))
                req.result, req.evidence = classify_result(req.result_raw)
                if req.result == "Unknown":
                    log.warn(where, f"{rid}: result '{req.result_raw}' not recognised (expected ✅ / ⚠️ / ❌)")
                req.cited_tests = count_cited_tests(cell("tests"))
                out["requirements"] = [r for r in out["requirements"] if r.rid != rid] + [req]
                seen.add(rid)
        # ---- screen map
        elif t.col("key") == 0 and t.col("surface") is not None:
            for ln, cells in t.rows:
                if len(cells) < len(t.header):
                    log.warn(f"coverage line {ln}", "screen-map row is short; padded")
                    cells = cells + [""] * (len(t.header) - len(cells))
                out["screens"].append({
                    "key": clean(cells[0]),
                    "surface": clean(cells[t.col("surface")]),
                    "exists_raw": cells[t.col("exists")] if t.col("exists") is not None else "",
                    "exists": clean(cells[t.col("exists")]) if t.col("exists") is not None else "",
                    "acts": clean(cells[t.col("acts", "view")]) if t.col("acts", "view") is not None else "",
                    "line": ln,
                })
        # ---- reachability class legend
        elif t.col("class") == 0 and t.col("meaning") is not None:
            for ln, cells in t.rows:
                k = clean(cells[0]).lower().strip("()")
                if k in CLASSES:
                    out["classes"][k] = clean(cells[t.col("meaning")])
        # ---- stated summary
        elif t.col("module") == 0 and t.col("total") is not None:
            idx = {k: t.col(f"({k})") for k in CLASSES}
            for ln, cells in t.rows:
                label = clean(cells[0])
                key = next((code for _, code, _, _ in MODULES if label.startswith(code)), None)
                if key is None and "mandatory" in label.lower():
                    key = "Mandatory"
                if key is None:
                    log.warn(f"coverage line {ln}", f"summary row '{label}' not recognised")
                    continue
                vals = {}
                for k, i in list(idx.items()) + [("total", t.col("total"))]:
                    try:
                        vals[k] = int(clean(cells[i]))
                    except (TypeError, ValueError, IndexError):
                        vals[k] = None
                out["stated"][key] = vals
        # ---- stated test evidence
        elif t.col("evidence") == 0 and t.col("mandatory") is not None:
            for ln, cells in t.rows:
                out["evidence"].append((clean(cells[0]), clean(cells[1]) if len(cells) > 1 else ""))
        # ---- gap tables (4.1 / 4.2 / 4.3): an ID column and a "what would close it" column
        elif t.col("id") == 0 and t.col("close") is not None:
            detail = t.col("missing", "unreachable", "situation", "step")
            close = t.col("close")
            kind = t.heading
            hl = kind.lower()
            short = ("Class (d)" if "(d)" in hl else "Class (c)" if "(c)" in hl
                     else "No direct test" if "test" in hl else kind)
            for ln, cells in t.rows:
                cells = cells + [""] * (len(t.header) - len(cells))
                ids_raw = clean(cells[0])
                out["gaps"].append({
                    "section": kind, "kind": short, "ids_raw": ids_raw, "ids": ids_in(ids_raw),
                    "detail": clean(cells[detail]) if detail is not None else "",
                    "close": clean(cells[close]), "line": ln,
                })
        # ---- deployment readiness
        elif t.col("item") == 0 and t.col("still true", "status") is not None:
            for ln, cells in t.rows:
                cells = cells + [""] * (len(t.header) - len(cells))
                still = clean(cells[t.col("still true", "status")])
                out["readiness"].append({
                    "item": clean(cells[0]), "still": still, "state": readiness_state(still),
                    "evidence": clean(cells[t.col("evidence")]) if t.col("evidence") is not None else "",
                })
        elif "id" in hdr or "module" in hdr:
            log.info(f"coverage line {t.line}", f"table under '{t.heading}' not used (header: {' | '.join(t.header)[:80]})")

    if not out["requirements"]:
        log.warn("coverage", "no matrix rows found at all")
    for key, label in (("screens", "screen map"), ("gaps", "gap tables"), ("readiness", "deployment readiness")):
        if not out[key]:
            log.warn("coverage", f"no {label} table found")
    return out


def readiness_state(still: str) -> str:
    s = still.lower()
    for needle, state in (("superseded", "Superseded"), ("not enabled", "Open"), ("open", "Open"),
                          ("newly", "New finding"), ("changed", "Changed"), ("closed", "Closed"),
                          ("no longer", "Closed"), ("done", "Closed")):
        if needle in s:
            return state
    return "Other"


def parse_baseline(text: str, log: Log) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in parse_tables(text):
        if t.col("id") != 0:
            continue
        stmt = t.col("statement", "requirement")
        if stmt is None:
            continue
        for ln, cells in t.rows:
            rid = clean(cells[0])
            if not REQ_ID_RE.fullmatch(rid):
                continue
            def get(*n: str) -> str:
                i = t.col(*n)
                return clean(cells[i]) if i is not None and i < len(cells) else ""
            supplementary = rid.startswith("O-")
            out[rid] = {
                "title": get("title"),
                "statement": clean(cells[stmt]) if stmt < len(cells) else "",
                "module": get("module"),
                "priority": get("priority") or ("Supplementary" if supplementary else ""),
                "planned": get("how satisfied"),
                "planned_raw": cells[t.col("how satisfied")] if t.col("how satisfied") is not None
                and t.col("how satisfied") < len(cells) else "",
                "delta": "Δ" if "Δ" in get("δ") else "",
            }
    if not out:
        log.warn("baseline", "no requirement rows found")
    return out


STATUS_EMOJI = {"✅": "Done", "🟡": "Partial", "🔄": "In progress", "⬜": "Not started", "❌": "Blocked"}
STATUS_ORDER = ["Done", "Partial", "In progress", "Not started", "Blocked"]


def split_status(cell: str, evidence: str = "") -> dict:
    """'🔄 In progress (WS2). `routing.preview` …' → status word, label 'In progress (WS2)', and the notes."""
    t = cell.strip()
    m = re.match(r"^\s*([✅🟡🔄⬜❌])?\ufe0f?\s*(done|partial|in progress|not started|blocked)?\s*\.?\s*"
                 r"(\([^)]*\))?\s*\.?\s*(.*)$", t, re.I | re.S)
    emoji, word, paren, rest = m.groups() if m else (None, None, None, t)
    status_word = (next((w for w in STATUS_ORDER if word and w.lower() == word.lower()), None)
                   or STATUS_EMOJI.get(emoji or "", ""))
    if not status_word:
        rest = t
    label = " ".join(x for x in (status_word, paren or "") if x)
    notes = " ".join(x for x in (rest.strip(), evidence) if x)
    return {"status": label, "status_word": status_word, "evidence": notes}


def parse_epics(text: str, log: Log) -> dict:
    lines = text.splitlines()
    epics: dict[str, dict] = {}
    phase = ""
    current: str | None = None
    # Headings and trace lines
    for i, line in enumerate(lines):
        m = re.match(r"^#\s+(Phase\s+\d+\s*[—-]\s*.+)$", line)
        if m:
            phase = m.group(1).strip()
        m = re.match(r"^##\s+(E\d+)\s*[—-]\s*(.+)$", line)
        if m:
            current = m.group(1)
            # the outcome/trace paragraph runs until the first table or blank-after-text
            para = []
            for nxt in lines[i + 1:]:
                if nxt.strip().startswith("|") or nxt.startswith("#"):
                    break
                para.append(nxt)
            para_text = " ".join(para)
            tm = re.search(r"Trace:\s*(.+?)(?:\.\s*$|\.\s+[A-Z]|$)", para_text)
            trace_raw = tm.group(1).strip() if tm else ""
            epics[current] = {"title": clean(m.group(2)), "phase": phase, "trace_raw": trace_raw,
                              "trace_ids": ids_in(trace_raw), "state": "", "state_evidence": ""}
    stories = []
    stated_counts: dict[str, tuple[dict, int]] = {}
    status_cols_seen: set[str] = set()
    for t in parse_tables(text):
        id_i = t.col("id")
        if id_i == 0 and t.col("story") is not None:
            epic_heading = next((h for h in reversed(t.headings) if re.match(r"^E\d+\b", h)), "")
            epic = epic_heading.split()[0] if epic_heading else ""
            extra_cols = [c for c in t.header if clean(c).lower() not in {"id", "story", "size"}]
            status_cols_seen.update(extra_cols)
            for ln, cells in t.rows:
                cells = cells + [""] * (len(t.header) - len(cells))
                sid = clean(cells[0])
                if not re.fullmatch(r"E\d+-S\d+", sid):
                    log.warn(f"epics line {ln}", f"story id '{sid[:30]}' not recognised; row skipped")
                    continue
                if not epic:
                    epic = sid.split("-")[0]
                story_raw = cells[t.col("story")]
                story = clean(story_raw)
                ac = ""
                am = re.search(r"\s*AC:\s*", story)
                if am:
                    story, ac = story[: am.start()].strip(), story[am.end():].strip()

                def get(*n: str) -> str:
                    i = t.col(*n)
                    return clean(cells[i]) if i is not None and i < len(cells) else ""

                own_trace = get("trace", "requirement", "req")
                own_ids = ids_in(own_trace) or ids_in(story_raw)
                ep = epics.get(epic, {})
                others = {h: clean(cells[t.header.index(h)]) for h in extra_cols
                          if clean(h).lower() not in {"status", "state", "evidence"}
                          and not re.search(r"trace|requirement|req", h, re.I)}
                stories.append({
                    "id": sid, "epic": epic, "epic_title": ep.get("title", ""), "phase": ep.get("phase", ""),
                    "size": get("size"),
                    **split_status(get("status", "state"), get("evidence")),
                    "story": story, "ac": ac,
                    "req_ids": own_ids or ep.get("trace_ids", []),
                    "trace_source": "story" if own_ids else ("epic trace" if ep.get("trace_ids") else "none"),
                    "others": others, "line": ln,
                })
        elif t.col("epic") == 0 and any(STATUS_EMOJI.get(e) for h in t.header for e in h) and t.col("total"):
            # "Status at a glance": Epic | ✅ Done | 🟡 Partial | 🔄 In progress | ⬜ Not started | Total
            label_of = {i: STATUS_EMOJI[e] for i, h in enumerate(t.header) for e in h if e in STATUS_EMOJI}
            for ln, cells in t.rows:
                m = re.match(r"^E(\d+)\b", clean(cells[0]))
                if not m:
                    continue
                counts = {}
                for i, lab in label_of.items():
                    try:
                        counts[lab] = int(clean(cells[i]))
                    except (ValueError, IndexError):
                        counts[lab] = None
                stated_counts[f"E{m.group(1)}"] = (counts, ln)
        elif t.col("epic") == 0 and t.col("state", "status") is not None:
            for ln, cells in t.rows:
                label = clean(cells[0])
                m = re.match(r"^E(\d+)(?:\s*[–—-]\s*E(\d+))?\b", label)
                if not m:
                    log.warn(f"epics line {ln}", f"status row '{label[:40]}' has no epic id")
                    continue
                a = int(m.group(1))
                b = int(m.group(2) or a)
                state = clean(cells[t.col("state", "status")])
                ev = clean(cells[t.col("evidence")]) if t.col("evidence") is not None and t.col("evidence") < len(cells) else ""
                for n in range(a, b + 1):
                    e = epics.setdefault(f"E{n}", {"title": "", "phase": "", "trace_raw": "", "trace_ids": []})
                    e["state"], e["state_evidence"] = state, ev
    # Epic state: counted from its stories, and checked against the at-a-glance table when there is one.
    for code, e in epics.items():
        mine = [st["status_word"] for st in stories if st["epic"] == code and st["status_word"]]
        if mine and not e.get("state"):
            e["state"] = ", ".join(f"{w} {mine.count(w)}" for w in STATUS_ORDER if mine.count(w))
        if code in stated_counts:
            counts, ln = stated_counts[code]
            for w, n in counts.items():
                if n is not None and n != mine.count(w):
                    log.warn(f"epics line {ln}", f"{code}: at-a-glance says {n} {w}, story rows say {mine.count(w)}")
    has_status = any(c.lower() in {"status", "state"} for c in status_cols_seen)
    if not stories:
        log.warn("epics", "no story rows found")
    return {"epics": epics, "stories": stories, "has_story_status": has_status,
            "extra_cols": sorted(status_cols_seen)}


# ---------------------------------------------------------------- provenance


def git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=20, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def provenance(repo: Path, rel: Path) -> dict:
    data = (repo / rel).read_bytes()
    status = git(repo, "status", "--porcelain", "--", str(rel))
    last = git(repo, "log", "-1", "--format=%h %cs", "--", str(rel))
    if status.startswith("??"):
        state = "untracked (not yet committed)"
    elif status:
        state = "modified since last commit"
    else:
        state = "clean"
    return {"path": str(rel), "sha256": hashlib.sha256(data).hexdigest()[:16], "state": state,
            "last_commit": last or "—", "lines": data.decode("utf-8", "replace").count("\n")}


# ---------------------------------------------------------------- code index
#
# The matrix names entities and functions ("`Governance Forum`", "`inventory.search`",
# "`charters.record_challenge`") but rarely a path. The index below turns those names
# into paths by reading the application tree (ast for Python, JSON for DocTypes), so
# the "Where it lives" columns are looked up, not typed, and follow the code when it moves.

APP_REL = Path("apps/consilium/consilium")  # the Python package; displayed paths are relative to apps/consilium
PACKAGE_OF_PREFIX = {"G": "governance", "P": "policy", "E": "escalation", "O": "governance"}
GENERIC_NAMES = {"validate", "on_update", "before_save", "before_insert", "after_insert", "on_submit",
                 "on_trash", "generate", "execute", "get_context", "run", "main", "setUp", "tearDown"}


@dataclass
class TestClass:
    module: str  # dotted, without the leading "consilium."
    name: str
    path: str
    methods: list[str]


class CodeIndex:
    def __init__(self, repo: Path, log: Log) -> None:
        import ast
        import json

        self.root = repo / APP_REL
        self.display_root = self.root.parent  # apps/consilium → paths read "consilium/policy/lifecycle.py"
        self.ok = self.root.is_dir()
        self.defs: dict[str, list[tuple[str, str]]] = {}  # bare name → [(path, qualname)]
        self.stems: dict[str, list[str]] = {}  # module stem → [path]
        self.classes: dict[str, list[str]] = {}  # class name → [path]
        self.doctypes: dict[str, dict] = {}  # DocType name → info
        self.parents: dict[str, list[str]] = {}  # child-table DocType → DocTypes that embed it
        self.series: dict[str, str] = {}  # naming-series prefix (e.g. "ESC") → DocType
        self.test_classes: dict[str, list[TestClass]] = {}
        self.test_modules: dict[str, list[TestClass]] = {}  # dotted module → classes
        self.test_module_paths: dict[str, str] = {}
        self.workflows: set[str] = set()
        self.js: dict[str, str] = {}  # path → source (desk scripts only)
        self.www: dict[str, dict] = {}  # route → {"py": path, "detail": bool}
        if not self.ok:
            log.warn("code index", f"{APP_REL} not found; 'Where it lives' and test lookups will be sparse")
            return
        for py in sorted(self.root.rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            rel = self.rel(py)
            src = py.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                log.info("code index", f"could not parse {rel}; skipped")
                continue
            dotted = ".".join(py.relative_to(self.root).with_suffix("").parts)
            is_test = py.name.startswith("test_")
            for m in re.finditer(r'(?:WORKFLOW_NAME|workflow_name)["\']?\s*[:=]\s*["\']([^"\']+)["\']', src):
                if not is_test:
                    self.workflows.add(m.group(1))
            if is_test:
                self.test_module_paths[dotted] = rel
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        tc = TestClass(dotted, node.name, rel,
                                       [f.name for f in node.body
                                        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                                        and f.name.startswith("test")])
                        self.test_classes.setdefault(node.name, []).append(tc)
                        self.test_modules.setdefault(dotted, []).append(tc)
                self.test_modules.setdefault(dotted, [])
                continue
            if "tests" in py.parts:
                continue
            self.stems.setdefault(py.stem, []).append(rel)
            if py.parent.name == "www":
                route = "/" if py.stem == "index" else "/" + py.stem.replace("_", "-")
                self.www[route] = {"py": rel, "detail": bool(re.search(r'form_dict\.get\(\s*["\']name["\']', src))}
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.defs.setdefault(node.name, []).append((rel, node.name))
                elif isinstance(node, ast.ClassDef):
                    self.classes.setdefault(node.name, []).append(rel)
                    for f in node.body:
                        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.defs.setdefault(f.name, []).append((rel, f"{node.name}.{f.name}"))
        for js in sorted(self.root.rglob("*.js")):
            if "public" in js.parts or "node_modules" in js.parts:
                continue
            self.js[self.rel(js)] = js.read_text(encoding="utf-8", errors="replace")
        ws_links: dict[str, str] = {}
        for wj in self.root.glob("*/workspace/*/*.json"):
            try:
                d = json.loads(wj.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for link in d.get("links", []):
                if link.get("link_type") in (None, "DocType") and link.get("link_to"):
                    ws_links.setdefault(link["link_to"], d.get("name", ""))
        for dj in self.root.glob("*/doctype/*/*.json"):
            try:
                d = json.loads(dj.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if d.get("doctype") != "DocType" or not d.get("name"):
                continue
            ctrl = dj.with_suffix(".py")
            sm = re.match(r"^(?:format:)?([A-Z]{2,8})-[.{]", d.get("autoname") or "")
            if sm and not d.get("istable"):
                self.series.setdefault(sm.group(1), d["name"])
            for f in d.get("fields", []):
                if f.get("fieldtype") in ("Table", "Table MultiSelect") and f.get("options"):
                    self.parents.setdefault(f["options"], [])
                    if d["name"] not in self.parents[f["options"]]:
                        self.parents[f["options"]].append(d["name"])
            self.doctypes[d["name"]] = {
                "controller": self.rel(ctrl) if ctrl.exists() else self.rel(dj),
                "module": d.get("module", ""),
                "child": bool(d.get("istable")),
                "workspace": ws_links.get(d["name"], ""),
                "slug": d["name"].lower().replace(" ", "-"),
            }
        # longest first, so "Governing Document Lifecycle" never matches "Governing Document" first
        self.doctype_re = re.compile(
            r"(?<![\w-])(" + "|".join(re.escape(n) for n in sorted(self.doctypes, key=len, reverse=True)
                                       if " " in n) + r")(?![\w-])") if self.doctypes else None

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.display_root))

    @staticmethod
    def prefer(paths: list[str], package: str) -> list[str]:
        """Order candidate paths: the requirement's own module first, then Core, then the rest."""
        def rank(p: str) -> int:
            parts = p.split("/")
            pkg = parts[1] if len(parts) > 1 else ""
            return 0 if pkg == package else 1 if pkg == "consilium_core" else 2
        return sorted(paths, key=rank)

    # -- where it lives

    def locate(self, raw: str, rid: str, screens_detail: set[str]) -> dict[str, list[str]]:
        package = PACKAGE_OF_PREFIX.get(rid[0], "")
        portal: list[str] = []
        workspace: list[str] = []
        code: list[str] = []
        funcs: list[str] = []

        def add(lst: list[str], item: str) -> None:
            if item and item not in lst:
                lst.append(item)

        tokens = re.findall(r"`([^`]+)`", raw)
        # routes
        for t in tokens:
            if t.startswith("/"):
                route = t.split("?")[0].rstrip("/") or "/"
                info = self.www.get(route)
                detail = route in screens_detail or (info and info["detail"])
                shown = f"{route}?name=…" if detail and "?" not in t else t
                add(portal, "/ (home)" if route == "/" else shown)
        # DocTypes: backticked names, then multi-word names in running text
        names = [t for t in tokens if t in self.doctypes]
        if self.doctype_re:
            names += self.doctype_re.findall(clean(raw))
        seen_dt: list[str] = []
        for n in names:
            if n not in seen_dt:
                seen_dt.append(n)
        for n in seen_dt:
            d = self.doctypes[n]
            if d["child"]:
                hosts = [h for h in self.parents.get(n, []) if h in self.doctypes]
                if hosts:
                    for h in hosts[:2]:
                        add(workspace, f"/app/{self.doctypes[h]['slug']} → '{n}' table")
                else:
                    add(workspace, f"{n} (child table, edited inside its parent form)")
            else:
                add(workspace, self.workspace_entry(n))
        for wf in sorted(self.workflows):
            if wf in raw:
                add(workspace, f"/app/workflow/{wf} (framework Workflow)")
        # functions, classes, files
        for t in tokens:
            t = t.strip().rstrip("()")
            if t.startswith("/") or t in self.doctypes or " " in t:
                continue
            if t.endswith(".py"):
                stem = Path(t).stem
                hits = self.prefer(self.stems.get(stem, []), package)
                if not hits and (self.root.parent.parent.parent / t).exists():
                    hits = [t]
                for h in hits[:2]:
                    add(code, h + (" (portal page)" if "/www/" in h else ""))
                continue
            parts = t.split(".")
            if len(parts) == 2 and re.fullmatch(r"[A-Za-z_]\w*", parts[0]) and re.fullmatch(r"\w+", parts[1]):
                head, fn = parts
                files = self.classes.get(head) if head[:1].isupper() else self.stems.get(head)
                files = self.prefer(files or [], package)
                hit = next((f for f in files if any(p == f and (q == fn or q.endswith("." + fn))
                                                    for p, q in self.defs.get(fn, []))), None)
                if hit:
                    add(code, f"{hit} → {head + '.' if head[:1].isupper() else ''}{fn}()")
                    funcs.append(fn)
                elif files:
                    add(code, files[0])
                continue
            if len(parts) > 2 and parts[1] == "doctype":  # consilium_core.doctype.guide_article
                p = self.root.joinpath(*parts)
                if p.is_dir():
                    add(code, self.rel(p / f"{parts[-1]}.py") if (p / f"{parts[-1]}.py").exists() else self.rel(p))
                continue
            if re.fullmatch(r"[a-z_][a-z0-9_]*", t) and t not in GENERIC_NAMES:
                cands = self.defs.get(t, [])
                if not cands:
                    continue
                ranked = self.prefer(sorted({p for p, _ in cands}), package)
                first_pkg = ranked[0].split("/")[1]
                same = [p for p in ranked if p.split("/")[1] == first_pkg]
                if len(same) <= 2:
                    for p in same:
                        q = next(q for pp, q in cands if pp == p)
                        add(code, f"{p} → {q}()")
                    funcs.append(t)
        # desk scripts that call a resolved function (custom desk buttons)
        for path, src in self.js.items():
            if "add_custom_button" in src and any(f in src for f in funcs):
                add(workspace, f"desk button — {path}")
        # page controllers for the routes named
        for p in portal:
            info = self.www.get(p.split("?")[0].split(" ")[0])
            if info and not any(c.split(" ")[0] == info["py"] for c in code):
                add(code, info["py"] + " (portal page)")
        # DocType controllers last
        for n in seen_dt:
            if not self.doctypes[n]["child"]:
                add(code, f"{self.doctypes[n]['controller']} ({n})")
        return {"portal": portal, "workspace": workspace, "code": code}

    def workspace_entry(self, name: str) -> str:
        d = self.doctypes[name]
        return f"/app/{d['slug']}" + (f" — {d['workspace']} workspace" if d["workspace"] else "")

    def doctypes_of_records(self, text: str) -> list[str]:
        """DocTypes of record names such as ESC-2026-00010 or GDOC-00012, via their naming series."""
        out: list[str] = []
        prefixes = re.findall(r"\b([A-Z]{2,8})-(?:\d{4}-)?\d{3,6}\b", text)
        prefixes += [p for p in re.findall(r"\b([A-Z]{3,8})\b", text) if p in self.series]  # "any GDOC"
        for prefix in prefixes:
            name = self.series.get(prefix)
            if name and name not in out:
                out.append(name)
        return out

    # -- tests

    def resolve_tests(self, raw: str, rid: str, log: Log, where: str) -> list[dict]:
        """Turn a Test(s) cell into fully qualified references, in the order cited."""
        refs: list[dict] = []
        ctx_mod = ""
        ctx_cls: TestClass | None = None
        package = PACKAGE_OF_PREFIX.get(rid[0], "")

        def pick_module(stem_path: list[str]) -> list[str]:
            want = ".".join(stem_path)
            mods = [m for m in self.test_modules if m == want or m.endswith("." + want)]
            ctx_pkg = ctx_mod.split(".")[0] if ctx_mod else package
            return sorted(mods, key=lambda m: (m.split(".")[0] != ctx_pkg, m.split(".")[0] != package,
                                                "doctype" in m, m))

        for m in re.finditer(r"`([^`]+)`", raw):
            tok = m.group(1).strip()
            after = raw[m.end(): m.end() + 40]
            stated = re.match(r"\s*\((?:all|every)\s+(\d+)", after)
            stated_n = int(stated.group(1)) if stated else None
            if tok.startswith("consilium."):
                tok = tok[len("consilium."):]
            if "test" not in tok.lower() and ".doctype." not in tok:
                continue
            elided = "…" in tok
            parts = [p for p in tok.replace("…", ".").split(".") if p]
            cls_i = next((i for i, p in enumerate(parts) if re.fullmatch(r"Test[A-Z]\w*", p)), None)
            method = parts[-1] if parts[-1].startswith("test_") and (cls_i is not None or elided) else None
            if method is None and len(parts) == 1 and parts[0].startswith("test_") and not pick_module(parts):
                method = parts[0]  # a bare method name, cited under the class before it
            mod_parts = parts[:cls_i] if cls_i is not None else [p for p in parts if p != method]
            tc: TestClass | None = None
            if cls_i is not None:
                cname = parts[cls_i]
                cands = self.test_classes.get(cname, [])
                if mod_parts:
                    want = ".".join(mod_parts)
                    cands = [c for c in cands if c.module == want or c.module.endswith("." + want)]
                ctx_pkg = ctx_mod.split(".")[0] if ctx_mod else package
                cands = sorted(cands, key=lambda c: (c.module != ctx_mod, c.module.split(".")[0] != ctx_pkg,
                                                     c.module.split(".")[0] != package))
                tc = cands[0] if cands else None
                if tc is None:
                    log.warn(where, f"{rid}: test class '{tok}' not found in the code")
                    refs.append({"module": ".".join(mod_parts), "cls": cname, "method": method, "kind":
                                 "method" if method else "class", "stated": stated_n, "path": "",
                                 "found": False, "methods": []})
                    continue
            elif method:
                if mod_parts:
                    mods = pick_module(mod_parts)
                    if ctx_cls and ctx_cls.module in mods and method in ctx_cls.methods:
                        tc = ctx_cls
                    else:
                        tc = next((c for mname in mods for c in self.test_modules.get(mname, [])
                                   if method in c.methods), ctx_cls)
                else:
                    tc = ctx_cls
                    if tc and method not in tc.methods:
                        tc = next((c for c in self.test_modules.get(tc.module, []) if method in c.methods), tc)
                if tc is None:
                    log.warn(where, f"{rid}: test '{tok}' has no class to attach to")
                    continue
            else:  # a whole module
                mods = pick_module(mod_parts)
                if not mods:  # a package, e.g. consilium_core.doctype.guide_article → its test module
                    mods = sorted(m for m in self.test_modules if m.startswith(".".join(mod_parts) + "."))
                if not mods:
                    log.warn(where, f"{rid}: test module '{tok}' not found in the code")
                    refs.append({"module": tok, "cls": "", "method": None, "kind": "module", "stated": stated_n,
                                 "path": "", "found": False, "methods": []})
                    continue
                mname = mods[0]
                methods = [(c.name, t) for c in self.test_modules.get(mname, []) for t in c.methods]
                refs.append({"module": mname, "cls": "", "method": None, "kind": "module", "stated": stated_n,
                             "path": self.test_module_paths.get(mname, ""), "found": True, "methods": methods})
                ctx_mod, ctx_cls = mname, None
                continue
            found = method is None or method in tc.methods
            if not found:
                log.warn(where, f"{rid}: {tc.module}.{tc.name} has no method {method}")
            refs.append({"module": tc.module, "cls": tc.name, "method": method,
                         "kind": "method" if method else "class", "stated": stated_n, "path": tc.path,
                         "found": found, "methods": [(tc.name, t) for t in tc.methods] if not method else []})
            ctx_mod, ctx_cls = tc.module, tc
        # "`TestX` permission tests (`test_a`, `test_b`)" cites methods, not the whole class;
        # "`TestX` (all 15), including `test_a`" cites the whole class, and test_a is inside it.
        whole = {(r["module"], r["cls"]) for r in refs if r["kind"] == "class" and r["stated"] is not None}
        named = {(r["module"], r["cls"]) for r in refs if r["kind"] == "method"}
        refs = [r for r in refs
                if not (r["kind"] == "class" and r["stated"] is None and (r["module"], r["cls"]) in named)
                and not (r["kind"] == "method" and (r["module"], r["cls"]) in whole)]
        return refs


def test_lines(refs: list[dict]) -> str:
    out = []
    for r in refs:
        if r["kind"] == "method":
            out.append(f"{r['module']}.{r['cls']}.{r['method']}" + ("" if r["found"] else "  [not found in code]"))
        else:
            name = f"{r['module']}.{r['cls']}" if r["cls"] else r["module"]
            n = r["stated"] if r["stated"] is not None else len(r["methods"])
            out.append(f"{name}.* (all {n})" + ("" if r["found"] else "  [not found in code]"))
    return "\n".join(dict.fromkeys(out))


# ---------------------------------------------------------------- sheet helpers


def estimate_height(values: list[tuple[str, float]], base: float = 13.0) -> float:
    lines = 1
    for text, width in values:
        if not text:
            continue
        chars = max(int(width * 1.15), 1)
        n = sum(max(1, math.ceil(len(part) / chars)) for part in str(text).split("\n"))
        lines = max(lines, n)
    return min(409.0, base * lines + 4)


def write_table(ws, top: int, left: int, columns: list[tuple[str, float]], rows: list[list],
                name: str, style: str = "TableStyleMedium2", wrap_cols: set[str] | None = None,
                center_cols: set[str] | None = None, freeze: bool = True) -> tuple[int, int]:
    """Write a header + rows as an Excel Table. Returns (first data row, last data row)."""
    wrap_cols = wrap_cols or set()
    center_cols = center_cols or set()
    for j, (head, width) in enumerate(columns):
        c = ws.cell(row=top, column=left + j, value=head)
        c.font, c.fill, c.alignment, c.border = HEADER_FONT, HEADER_FILL, CENTER_TOP, BOX
        letter = get_column_letter(left + j)
        if (ws.column_dimensions[letter].width or 0) < width:
            ws.column_dimensions[letter].width = width
    ws.row_dimensions[top].height = estimate_height([(h, w) for h, w in columns])
    for i, row in enumerate(rows, start=1):
        r = top + i
        for j, value in enumerate(row):
            c = ws.cell(row=r, column=left + j, value=value)
            head = columns[j][0]
            c.font, c.border = BODY_FONT, BOX
            c.alignment = CENTER_TOP if head in center_cols else WRAP_TOP
        ws.row_dimensions[r].height = estimate_height(
            [(str(v) if v is not None else "", columns[j][1]) for j, v in enumerate(row)]
        )
    last = top + max(len(rows), 1)
    if not rows:  # a Table needs at least one data row
        ws.cell(row=top + 1, column=left, value="(none)").font = NOTE_FONT
    ref = f"{get_column_letter(left)}{top}:{get_column_letter(left + len(columns) - 1)}{last}"
    tab = Table(displayName=name, ref=ref)
    tab.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=True, showColumnStripes=False)
    ws.add_table(tab)
    if freeze:
        ws.freeze_panes = ws.cell(row=top + 1, column=left + 1)
    ws.print_title_rows = f"{top}:{top}"
    return top + 1, last


def page_setup(ws, landscape: bool = True) -> None:
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.gridLines = False
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    ws.oddFooter.center.text = "&A — page &P of &N"
    ws.oddFooter.center.font = FONT


def fill_rule(ws, rng: str, first_cell: str, value: str, colour: str, contains: bool = False) -> None:
    formula = (f'ISNUMBER(SEARCH("{value}",{first_cell}))' if contains
               else f'{first_cell}="{value}"')
    ws.conditional_formatting.add(
        rng, FormulaRule(formula=[formula], fill=PatternFill("solid", fgColor=colour, bgColor=colour),
                         stopIfTrue=True))


# ---------------------------------------------------------------- build


REQ_COLUMNS = [  # header, width — order is the order on every requirements sheet
    ("ID", 7), ("Module", 13), ("Priority", 12), ("Short title", 26), ("Baseline title", 22),
    ("Requirement (baseline statement)", 60), ("What satisfies it", 60), ("Class", 7),
    ("Class meaning", 20), ("Demo data / workflow", 42), ("Test(s)", 52), ("Result", 16),
    ("Result as measured", 18), ("Test evidence", 14), ("Cited test methods (est.)", 11),
    ("Planned satisfaction (baseline)", 34), ("Δ decision", 8), ("Gap sections citing it", 20),
    ("Epics tracing it", 16), ("Stories tracing it", 9),
]


def req_row(r: Requirement) -> list:
    return [
        r.rid, r.module, r.priority, r.title, r.baseline_title, r.statement, r.satisfies, r.klass or r.klass_raw,
        CLASS_LABEL.get(r.klass, ""), r.demo, r.tests, r.result, r.result_raw, r.evidence, r.cited_tests,
        r.planned, r.delta, ", ".join(r.gap_refs), ", ".join(r.epics), r.stories or None,
    ]


def add_requirement_formats(ws, first: int, last: int) -> None:
    heads = [h for h, _ in REQ_COLUMNS]
    ccol = get_column_letter(heads.index("Class") + 1)
    rcol = get_column_letter(heads.index("Result") + 1)
    ecol = get_column_letter(heads.index("Test evidence") + 1)
    for k, colour in CLASS_COLOURS.items():
        fill_rule(ws, f"{ccol}{first}:{ccol}{last}", f"{ccol}{first}", k, colour)
    for k, colour in RESULT_COLOURS.items():
        fill_rule(ws, f"{rcol}{first}:{rcol}{last}", f"{rcol}{first}", k, colour)
    fill_rule(ws, f"{ecol}{first}:{ecol}{last}", f"{ecol}{first}", "No direct test", RESULT_COLOURS["No direct test"])
    fill_rule(ws, f"{ecol}{first}:{ecol}{last}", f"{ecol}{first}", "Failing test", RESULT_COLOURS["Fail"])


def build(repo: Path, out_path: Path, log: Log) -> dict:
    cov_text = (repo / COVERAGE_MD).read_text(encoding="utf-8")
    base_text = (repo / BASELINE_MD).read_text(encoding="utf-8")
    epic_text = (repo / EPICS_MD).read_text(encoding="utf-8") if (repo / EPICS_MD).exists() else ""
    if not epic_text:
        log.warn("epics", f"{EPICS_MD} not found; Epics tab left empty")

    cov = parse_coverage(cov_text, log)
    base = parse_baseline(base_text, log)
    ep = parse_epics(epic_text, log) if epic_text else {"epics": {}, "stories": [], "has_story_status": False,
                                                           "extra_cols": []}
    reqs: list[Requirement] = sorted(cov["requirements"], key=lambda r: req_sort_key(r.rid))

    # ---- join baseline
    for r in reqs:
        b = base.get(r.rid)
        if not b:
            log.warn("join", f"{r.rid} is in the matrix but not in the baseline")
            r.priority = "Supplementary" if r.rid.startswith("O-") else ""
            continue
        r.baseline_title, r.statement, r.baseline_module = b["title"], b["statement"], b["module"]
        r.priority, r.planned, r.delta = b["priority"], b["planned"], b["delta"]
    for rid in sorted(set(base) - {r.rid for r in reqs}, key=req_sort_key):
        log.warn("join", f"{rid} is in the baseline but has no matrix row")

    # ---- join gaps
    by_id = {r.rid: r for r in reqs}
    for g in cov["gaps"]:
        for rid in g["ids"]:
            if rid in by_id and g["kind"] not in by_id[rid].gap_refs:
                by_id[rid].gap_refs.append(g["kind"])
            elif rid not in by_id:
                log.warn(f"coverage line {g['line']}", f"gap row cites {rid}, which has no matrix row")
    for r in reqs:
        if r.klass in ("c", "d") and not r.gap_refs:
            log.warn("gaps", f"{r.rid} is class ({r.klass}) but no gap table row names it")
        if r.evidence == "No direct test" and "No direct test" not in r.gap_refs:
            log.warn("gaps", f"{r.rid} has no direct test but §4.3 does not list it")

    # ---- join epics
    for s in ep["stories"]:
        for rid in s["req_ids"]:
            if rid in by_id:
                by_id[rid].stories += 1
                if s["epic"] not in by_id[rid].epics:
                    by_id[rid].epics.append(s["epic"])
    for r in reqs:
        r.epics.sort(key=lambda e: int(e[1:]))

    # ---- where it lives, and the tests, looked up in the code
    idx = CodeIndex(repo, log)
    detail_routes = {m.group(1) for s in cov["screens"]
                     for m in re.finditer(r"`(/[a-z0-9\-]*)\?name=", s["exists_raw"])}
    base_raw = {rid: b.get("planned_raw", "") for rid, b in base.items()}
    as_re = re.compile(r"\b(?:As|Same as|as for)\s+([GPEO]-\d+)\b")
    empty = {"portal": [], "workspace": [], "code": []}
    for r in reqs:
        loc = idx.locate(r.satisfies_raw, r.rid, detail_routes) if idx.ok else empty
        r.portal, r.workspace, r.code = loc["portal"], loc["workspace"], loc["code"]
        r.test_refs = idx.resolve_tests(r.tests_raw, r.rid, log, f"coverage line {r.src_line}") if idx.ok else []
    # "As G-16." / "Same as G-14." — the row defers to another; inherit what that one resolved to.
    for _ in range(2):  # two passes so a chain (O-7 → O-6) resolves whatever the order
        for r in reqs:
            for ref in as_re.findall(r.satisfies_raw):
                src = by_id.get(ref)
                if src and src is not r:
                    for attr in ("portal", "workspace", "code"):
                        getattr(r, attr).extend(x for x in getattr(src, attr) if x not in getattr(r, attr))
            for ref in as_re.findall(r.tests_raw):
                src = by_id.get(ref)
                if src and src is not r and not r.test_refs:
                    r.test_refs = list(src.test_refs)
    for r in reqs:
        where = f"coverage line {r.src_line}"
        # The modules the cited tests exercise (test_x.py → x.py in the same package) live here too.
        for ref in r.test_refs:
            stem = ref["module"].split(".")[-1].removeprefix("test_")
            pkg = ref["module"].split(".")[0]
            for path in idx.stems.get(stem, []) if idx.ok else []:
                if path.split("/")[1] == pkg and not any(c.split(" ")[0] == path for c in r.code):
                    r.code.append(f"{path} (module under the cited tests)")
        # A class (a) row that names "register"/"detail" rather than a route: the module's own pages.
        if r.klass == "a" and not r.portal:
            pages = MODULE_PAGES.get(r.rid[0], {})
            text = clean(r.satisfies_raw).lower()
            r.portal = [route for word, route in pages.items() if word in text]
        if "report builder" in clean(r.satisfies_raw).lower() and r.rid[0] in PRIMARY_DOCTYPE and idx.ok:
            name = PRIMARY_DOCTYPE[r.rid[0]]
            if name in idx.doctypes:
                r.workspace.append(f"/app/{idx.doctypes[name]['slug']}/view/report (framework report builder)")
        # No entity named: the DocTypes of the demo records (by naming series) are where it lives on the desk.
        if not r.workspace and idx.ok:
            for name in idx.doctypes_of_records(clean(r.demo_raw)):
                r.workspace.append(idx.workspace_entry(name))
                if not any(name in c for c in r.code):
                    r.code.append(f"{idx.doctypes[name]['controller']} ({name})")
        if not r.code and idx.ok:
            # Nothing named in the text and no tests: the the entities the demo column or the baseline's "How satisfied" names.
            for raw in (r.demo_raw, base_raw.get(r.rid, "")):
                if r.code or not raw:
                    continue
                loc = idx.locate(raw, r.rid, detail_routes)
                r.code = [c for c in loc["code"] if "(portal page)" not in c]
                r.workspace = r.workspace or loc["workspace"]
            if r.code:
                log.info(where, f"{r.rid}: code located indirectly (tests, demo or baseline), not from the matrix text")
            elif clean(r.satisfies_raw).lower().startswith("native"):
                r.code = ["framework-native (no application code)"]
                log.info(where, f"{r.rid}: framework-native; no application code to point at")
            else:
                log.warn(where, f"{r.rid}: no code path could be resolved")
        if not r.test_refs and r.evidence == "Direct test":
            log.warn(where, f"{r.rid}: result says tested but no test reference resolved")

    wb = Workbook()
    wb.properties.creator = "scripts/coverage_to_xlsx.py"
    wb.properties.title = "Consilium — requirements coverage"
    wb.calculation = CalcProperties(fullCalcOnLoad=True)

    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = git(repo, "rev-parse", "--short", "HEAD") or "unknown"
    head_subject = git(repo, "log", "-1", "--format=%cs")
    dirty = bool(git(repo, "status", "--porcelain"))
    prov = [provenance(repo, p) for p in (COVERAGE_MD, BASELINE_MD, EPICS_MD) if (repo / p).exists()]

    # ================================================================ All requirements
    ws_all = wb.active
    ws_all.title = "All requirements"
    all_first, all_last = write_table(
        ws_all, 1, 1, REQ_COLUMNS, [req_row(r) for r in reqs], "Requirements",
        center_cols={"ID", "Class", "Priority", "Δ decision", "Cited test methods (est.)", "Stories tracing it"},
    )
    add_requirement_formats(ws_all, all_first, all_last)
    page_setup(ws_all)

    # ranges the Summary formulas count over — generous, so rows added by hand are counted too
    heads = [h for h, _ in REQ_COLUMNS]
    span = max(all_last, 500)
    sheet = quote_sheetname("All requirements")

    def rng(col: str) -> str:
        c = get_column_letter(heads.index(col) + 1)
        return f"{sheet}!${c}$2:${c}${span}"

    R_MOD, R_CLASS, R_PRI, R_EVID, R_RES = rng("Module"), rng("Class"), rng("Priority"), rng("Test evidence"), rng("Result")

    # ================================================================ module sheets
    module_counts = {}
    for _prefix, code, sheet_name, _long in MODULES:
        ws = wb.create_sheet(sheet_name)
        rows = [req_row(r) for r in reqs if r.module == code]
        module_counts[sheet_name] = len(rows)
        first, last = write_table(ws, 1, 1, REQ_COLUMNS, rows, f"Req_{code}",
                                  center_cols={"ID", "Class", "Priority", "Δ decision",
                                               "Cited test methods (est.)", "Stories tracing it"})
        add_requirement_formats(ws, first, last)
        page_setup(ws)

    # ================================================================ Gaps
    ws_gap = wb.create_sheet("Gaps")
    gap_cols = [("Gap list", 16), ("Section in source", 30), ("IDs", 16), ("Requirement ids (parsed)", 18),
                ("Classes of those ids", 12), ("Missing / situation", 60), ("What would close it", 60)]
    gap_rows = []
    for g in cov["gaps"]:
        classes = sorted({by_id[i].klass for i in g["ids"] if i in by_id and by_id[i].klass})
        gap_rows.append([g["kind"], g["section"], g["ids_raw"], ", ".join(g["ids"]),
                         ", ".join(classes), g["detail"], g["close"]])
    gfirst, glast = write_table(ws_gap, 1, 1, gap_cols, gap_rows, "Gaps", center_cols={"Classes of those ids"})
    for kind, colour in (("Class (d)", CLASS_COLOURS["d"]), ("Class (c)", CLASS_COLOURS["c"]),
                         ("No direct test", RESULT_COLOURS["No direct test"])):
        fill_rule(ws_gap, f"A{gfirst}:A{glast}", f"A{gfirst}", kind, colour)
    page_setup(ws_gap)

    # ================================================================ Screens
    ws_scr = wb.create_sheet("Screens")
    route_re = re.compile(r"`(/[a-z0-9\-]*)(?:\?[^`]*)?`")
    req_routes = {r.rid: set(route_re.findall(r.satisfies_raw)) for r in reqs}
    scr_rows = []
    for s in cov["screens"]:
        routes = set(route_re.findall(s["exists_raw"]))
        low = s["exists"].lower()
        status = ("Missing" if "does not exist" in low else "Desk" if s["key"].upper() == "DK"
                  else "Built")
        citing = sorted((rid for rid, rr in req_routes.items() if routes & rr), key=req_sort_key)
        scr_rows.append([s["key"], s["surface"], s["exists"], ", ".join(sorted(routes)), status,
                         s["acts"], ", ".join(citing)])
    scr_cols = [("Key", 7), ("Surface", 26), ("Exists as", 42), ("Routes", 22), ("Status", 10),
                ("Acts or views", 60), ("Requirements whose 'What satisfies it' names these routes", 34)]
    sfirst, slast = write_table(ws_scr, 1, 1, scr_cols, scr_rows, "Screens", center_cols={"Key", "Status"})
    for k, colour in (("Built", "C6EFCE"), ("Missing", "FFC7CE"), ("Desk", "DDEBF7")):
        fill_rule(ws_scr, f"E{sfirst}:E{slast}", f"E{sfirst}", k, colour)
    page_setup(ws_scr)

    # ================================================================ Deployment readiness
    ws_dep = wb.create_sheet("Deployment readiness")
    dep_cols = [("Item", 34), ("State", 12), ("Still true? (as written)", 22), ("Evidence", 90)]
    dep_rows = [[d["item"], d["state"], d["still"], d["evidence"]] for d in cov["readiness"]]
    dfirst, dlast = write_table(ws_dep, 1, 1, dep_cols, dep_rows, "Readiness", center_cols={"State"})
    for k, colour in (("Open", "FFC7CE"), ("Changed", "FFEB9C"), ("New finding", "FFEB9C"),
                      ("Superseded", "C6EFCE"), ("Closed", "C6EFCE")):
        fill_rule(ws_dep, f"B{dfirst}:B{dlast}", f"B{dfirst}", k, colour)
    page_setup(ws_dep)

    # ================================================================ Epics
    ws_ep = wb.create_sheet("Epics")
    extra_other = sorted({k for s in ep["stories"] for k in s["others"]})
    ep_cols = [("Story ID", 9), ("Epic", 6), ("Epic title", 24), ("Phase", 18), ("Size", 6),
               ("Story status", 14), ("Story evidence", 55), ("Epic state (from its stories)", 18),
               ("Epic evidence", 30),
               ("Requirement ids", 22), ("Trace source", 11), ("Story", 50), ("Acceptance criteria", 60)]
    ep_cols += [(c, 20) for c in extra_other]
    ep_rows = []
    for s in ep["stories"]:
        e = ep["epics"].get(s["epic"], {})
        ep_rows.append([s["id"], s["epic"], s["epic_title"], s["phase"], s["size"], s["status"],
                        s["evidence"], e.get("state", ""), e.get("state_evidence", ""),
                        ", ".join(s["req_ids"]), s["trace_source"], s["story"], s["ac"]]
                       + [s["others"].get(c, "") for c in extra_other])
    # the old per-epic "State | Evidence" table may be gone; drop a column no row fills
    heads_ep = [h for h, _ in ep_cols]
    k = heads_ep.index("Epic evidence")
    if not any(row[k] for row in ep_rows):
        ep_cols.pop(k)
        ep_rows = [row[:k] + row[k + 1:] for row in ep_rows]
    efirst, elast = write_table(ws_ep, 1, 1, ep_cols, ep_rows, "Stories",
                                center_cols={"Story ID", "Epic", "Size", "Story status", "Trace source"})
    for col in ("F", "H"):  # story status, epic state
        for k, colour in STATE_COLOURS.items():
            fill_rule(ws_ep, f"{col}{efirst}:{col}{elast}", f"{col}{efirst}", k, colour, contains=True)
    page_setup(ws_ep)

    # ================================================================ Test cases (one row per requirement × test method)
    ws_tc = wb.create_sheet("Test cases")
    tc_cols = [("Req ID", 7), ("Module", 13), ("Test module", 34), ("Class", 30), ("Test method", 50),
               ("Cited as", 14), ("Stated count", 9), ("Methods found", 9), ("File", 46)]
    tc_rows = []
    for r in reqs:
        for ref in r.test_refs:
            if ref["kind"] == "method":
                tc_rows.append([r.rid, r.module, ref["module"], ref["cls"], ref["method"],
                                "named method" if ref["found"] else "named method (NOT FOUND)",
                                None, 1 if ref["found"] else 0, ref["path"]])
                continue
            cited = "whole class" if ref["kind"] == "class" else "whole module"
            if not ref["found"]:
                tc_rows.append([r.rid, r.module, ref["module"], ref["cls"], "", f"{cited} (NOT FOUND)",
                                ref["stated"], 0, ""])
                continue
            for cname, meth in ref["methods"] or [(ref["cls"], "")]:
                tc_rows.append([r.rid, r.module, ref["module"], cname, meth, cited, ref["stated"],
                                len(ref["methods"]), ref["path"]])
            if ref["stated"] is not None and ref["stated"] != len(ref["methods"]):
                log.info("tests", f"{r.rid}: {ref['module']}{'.' + ref['cls'] if ref['cls'] else ''} "
                                  f"cited as 'all {ref['stated']}', code now has {len(ref['methods'])}")
    tfirst, tlast = write_table(ws_tc, 1, 1, tc_cols, tc_rows, "TestCases",
                                center_cols={"Req ID", "Stated count", "Methods found"})
    fill_rule(ws_tc, f"F{tfirst}:F{tlast}", f"F{tfirst}", "NOT FOUND", "FFC7CE", contains=True)
    page_setup(ws_tc)

    # ================================================================ Requirements map (first tab)
    ws_map = wb.create_sheet("Requirements map", 0)
    map_cols = [("Req ID", 7), ("Module", 13), ("Priority", 12), ("Requirement", 58), ("What we built", 58),
                ("Portal screen", 22), ("Workspace", 34), ("Code", 52), ("How a user reaches it", 26),
                ("Test cases", 64), ("Result", 14), ("Explanation / demo example", 44)]
    map_rows = []
    for r in reqs:
        map_rows.append([
            r.rid, r.module, r.priority, r.statement or r.title, r.satisfies,
            "\n".join(r.portal) or "— (no portal screen)",
            "\n".join(r.workspace) or "—",
            "\n".join(r.code) or "—",
            CLASS_WORDS.get(r.klass, r.klass_raw),
            test_lines(r.test_refs) or ("none" if r.evidence == "No direct test" else r.tests),
            r.result_raw, r.demo,
        ])
    mfirst, mlast = write_table(ws_map, 1, 1, map_cols, map_rows, "RequirementsMap",
                                center_cols={"Req ID", "Priority", "Result"})
    for k, colour in CLASS_COLOURS.items():
        fill_rule(ws_map, f"I{mfirst}:I{mlast}", f"I{mfirst}", f"({k})", colour, contains=True)
    for sym, colour in (("❌", RESULT_COLOURS["Fail"]), ("⚠", RESULT_COLOURS["No direct test"]),
                        ("✅ (", RESULT_COLOURS["Pass (qualified)"]), ("✅", RESULT_COLOURS["Pass"])):
        fill_rule(ws_map, f"K{mfirst}:K{mlast}", f"K{mfirst}", sym, colour, contains=True)
    page_setup(ws_map)

    # ================================================================ Parse log
    ws_log = wb.create_sheet("Parse log")
    log_rows = [list(e) for e in log.entries] or [["INFO", "—", "No parse problems."]]
    lfirst, llast = write_table(ws_log, 1, 1, [("Level", 8), ("Where", 26), ("Message", 100)], log_rows,
                                "ParseLog", center_cols={"Level"})
    fill_rule(ws_log, f"A{lfirst}:A{llast}", f"A{lfirst}", "WARN", "FFEB9C")
    page_setup(ws_log)

    # ================================================================ Summary (first tab)
    ws = wb.create_sheet("Summary", 1)
    ws.sheet_view.showGridLines = False
    widths = {"A": 40, "B": 14, "C": 15, "D": 14, "E": 14, "F": 10, "G": 3, "H": 9, "I": 9, "J": 9,
              "K": 9, "L": 9, "M": 12}
    for k, v in widths.items():
        ws.column_dimensions[k].width = v
    meta = cov["meta"]
    ws["A1"] = "Consilium — requirements coverage"
    ws["A1"].font = TITLE_FONT
    info = [
        ("Generated on", generated),
        ("Measured on (per source)", meta.get("measured", "")),
        ("Source", f"{COVERAGE_MD} (matrix); {BASELINE_MD} (statements); {EPICS_MD} (stories)"),
        ("Git commit", f"{head} ({head_subject}){' — working tree has uncommitted changes' if dirty else ''}"),
        ("Coverage source state", next((f"{p['state']}; sha256 {p['sha256']}…" for p in prov
                                         if p["path"] == str(COVERAGE_MD)), "")),
        ("Test run (per source)", f"Ran {meta.get('tests_run', '?')} tests, {meta.get('run_outcome', '?')}"
                                  + (f" — {meta['passed']} passed, {meta['failed']} failed" if "passed" in meta else "")),
        ("Generator", "scripts/coverage_to_xlsx.py — regenerate after editing the Markdown; do not hand-edit"),
    ]
    r = 3
    for k, v in info:
        ws.cell(row=r, column=1, value=k).font = BOLD
        ws.cell(row=r, column=2, value=v).font = BODY_FONT
        r += 1

    # ---- classes by module
    r += 1
    ws.cell(row=r, column=1, value="Reachability class by module (live formulas over 'All requirements')").font = SUBTITLE_FONT
    ws.cell(row=r, column=8, value="As stated in the source's §2 summary").font = SUBTITLE_FONT
    r += 1
    hdr = ["Module", "(a) Portal", "(b) Desk/config", "(c) Partly", "(d) Not impl.", "Total"]
    stated_hdr = ["a", "b", "c", "d", "Total", "Agrees?"]
    for j, h in enumerate(hdr, start=1):
        c = ws.cell(row=r, column=j, value=h)
        c.font, c.fill, c.alignment, c.border = HEADER_FONT, HEADER_FILL, CENTER_TOP, BOX
    for j, h in enumerate(stated_hdr, start=8):
        c = ws.cell(row=r, column=j, value=h)
        c.font, c.fill, c.alignment, c.border = HEADER_FONT, HEADER_FILL, CENTER_TOP, BOX
    grid_top = r + 1
    labels = {"CGF": "CGF — Governance", "POL": "POL — Policy", "ESC": "ESC — Escalation",
              "Mandatory": "Mandatory total", "Supplementary": "Supplementary (O-…)"}
    order = ["CGF", "POL", "ESC", "Mandatory", "Supplementary"]
    row_of = {}
    for i, key in enumerate(order):
        rr = grid_top + i
        row_of[key] = rr
        ws.cell(row=rr, column=1, value=labels[key]).font = BOLD if key == "Mandatory" else BODY_FONT
        for j, k in enumerate(CLASSES, start=2):
            if key == "Mandatory":
                f = f'=COUNTIFS({R_PRI},"Mandatory",{R_CLASS},"{k}")'
            else:
                f = f'=COUNTIFS({R_MOD},"{key}",{R_CLASS},"{k}")'
            ws.cell(row=rr, column=j, value=f)
        ws.cell(row=rr, column=6, value=(f'=COUNTIFS({R_PRI},"Mandatory")' if key == "Mandatory"
                                         else f'=COUNTIFS({R_MOD},"{key}")'))
        stated = cov["stated"].get(key, {})
        for j, k in enumerate(CLASSES + ["total"], start=8):
            ws.cell(row=rr, column=j, value=stated.get(k))
        ws.cell(row=rr, column=13, value=(
            f'=IF(COUNT(H{rr}:L{rr})=0,"not stated",IF(AND(B{rr}=H{rr},C{rr}=I{rr},D{rr}=J{rr},'
            f'E{rr}=K{rr},F{rr}=L{rr}),"Yes","NO"))'))
        for j in list(range(1, 7)) + list(range(8, 14)):
            c = ws.cell(row=rr, column=j)
            c.border = BOX
            if j > 1:
                c.alignment = Alignment(horizontal="center")
            if not c.font or c.font.name != FONT:
                c.font = BOLD if key == "Mandatory" else BODY_FONT
            if key == "Mandatory":
                c.fill = PatternFill("solid", fgColor="EDEDED")
    grid_last = grid_top + len(order) - 1
    fill_rule(ws, f"M{grid_top}:M{grid_last}", f"M{grid_top}", "NO", "FFC7CE")
    fill_rule(ws, f"M{grid_top}:M{grid_last}", f"M{grid_top}", "Yes", "C6EFCE")
    for j, k in enumerate(CLASSES, start=2):
        ws.cell(row=grid_top - 1, column=j).fill = PatternFill("solid", fgColor=CHART_COLOURS[k])
    note_r = grid_last + 1
    ws.cell(row=note_r, column=1, value=(
        "Left: computed from the rows. Right: typed in the source's summary table and copied here as-is, "
        "so a stale summary in the Markdown shows up as 'NO'.")).font = NOTE_FONT

    # ---- test evidence
    r = note_r + 2
    ws.cell(row=r, column=1, value="Test evidence").font = SUBTITLE_FONT
    r += 1
    for j, h in enumerate(["Evidence", "Mandatory", "Supplementary", "All"], start=1):
        c = ws.cell(row=r, column=j, value=h)
        c.font, c.fill, c.alignment, c.border = HEADER_FONT, HEADER_FILL, CENTER_TOP, BOX
    ev_top = r + 1
    for i, (label, crit) in enumerate([("At least one direct test, all passing", "Direct test"),
                                       ("No direct test", "No direct test"),
                                       ("Failing tests", "Failing test")]):
        rr = ev_top + i
        ws.cell(row=rr, column=1, value=label).alignment = Alignment(wrap_text=True)
        ws.cell(row=rr, column=2, value=f'=COUNTIFS({R_PRI},"Mandatory",{R_EVID},"{crit}")')
        ws.cell(row=rr, column=3, value=f'=COUNTIFS({R_MOD},"Supplementary",{R_EVID},"{crit}")')
        ws.cell(row=rr, column=4, value=f'=COUNTIFS({R_EVID},"{crit}")')
    rr = ev_top + 3
    ws.cell(row=rr, column=1, value="…of which the pass is qualified (e.g. 'engine only')")
    ws.cell(row=rr, column=2, value=f'=COUNTIFS({R_PRI},"Mandatory",{R_RES},"Pass (qualified)")')
    ws.cell(row=rr, column=3, value=f'=COUNTIFS({R_MOD},"Supplementary",{R_RES},"Pass (qualified)")')
    ws.cell(row=rr, column=4, value=f'=COUNTIFS({R_RES},"Pass (qualified)")')
    for rr in range(ev_top, ev_top + 4):
        for j in range(1, 5):
            c = ws.cell(row=rr, column=j)
            c.font, c.border = BODY_FONT, BOX
            if j > 1:
                c.alignment = Alignment(horizontal="center")
    rr = ev_top + 4
    ws.cell(row=rr, column=1, value=(
        f"Suite as measured: {meta.get('tests_run', '?')} test methods run, outcome "
        f"{meta.get('run_outcome', '?')} (typed from the source's Method section). A passing test proves only "
        "the part of a requirement it exercises.")).font = NOTE_FONT

    # ---- stories by status (live formulas over the Epics sheet)
    r = rr + 2
    ws.cell(row=r, column=1, value="Backlog stories by status (live formulas over 'Epics')").font = SUBTITLE_FONT
    r += 1
    for j, h in enumerate(["Status", "Stories"], start=1):
        c = ws.cell(row=r, column=j, value=h)
        c.font, c.fill, c.alignment, c.border = HEADER_FONT, HEADER_FILL, CENTER_TOP, BOX
    ep_heads = [h for h, _ in ep_cols]
    st_col = get_column_letter(ep_heads.index("Story status") + 1)
    id_col = get_column_letter(ep_heads.index("Story ID") + 1)
    ep_span = max(elast, 1000)
    st_rng = f"{quote_sheetname('Epics')}!${st_col}$2:${st_col}${ep_span}"
    id_rng = f"{quote_sheetname('Epics')}!${id_col}$2:${id_col}${ep_span}"
    for w in STATUS_ORDER + ["No status recorded", "Total"]:
        r += 1
        ws.cell(row=r, column=1, value=w)
        if w == "Total":
            f = f'=COUNTIFS({id_rng},"E*")'
        elif w == "No status recorded":
            f = f'=COUNTIFS({id_rng},"E*",{st_rng},"")'
        else:
            f = f'=COUNTIFS({st_rng},"{w}*")'
        ws.cell(row=r, column=2, value=f)
        for j in (1, 2):
            c = ws.cell(row=r, column=j)
            c.font, c.border = (BOLD if w == "Total" else BODY_FONT), BOX
            if j == 2:
                c.alignment = Alignment(horizontal="center")
        if w in ("Done", "Partial", "In progress", "Not started"):
            ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=STATE_COLOURS[w.lower()])
    rr = r

    # ---- legend
    r = rr + 2
    ws.cell(row=r, column=1, value="Legend").font = SUBTITLE_FONT
    r += 1
    legend = [(f"Class {k}", cov["classes"].get(k, CLASS_LABEL[k]), CLASS_COLOURS[k]) for k in CLASSES]
    legend += [
        ("Pass", "✅ — the cited tests exist and passed in the measured run.", RESULT_COLOURS["Pass"]),
        ("Pass (qualified)", "✅ with a qualifier such as '(engine only)' or '(flags only)': the tests pass "
                             "but do not reach the missing clause.", RESULT_COLOURS["Pass (qualified)"]),
        ("No direct test", "⚠️ — nothing tests this requirement directly.", RESULT_COLOURS["No direct test"]),
        ("Fail", "❌ — a cited test failed.", RESULT_COLOURS["Fail"]),
        ("Priority", "All 64 G/P/E requirements are Mandatory; O-1…O-7 are supplementary requirements brought "
                     "into scope (baseline Appendix A).", None),
        ("Cited test methods (est.)", "Sum of '(all N)' plus individually named methods in the Test(s) cell. "
                                      "An estimate: shared engine tests are counted under every requirement "
                                      "that cites them.", None),
    ]
    for label, text, colour in legend:
        lc = ws.cell(row=r, column=1, value=label)
        lc.font, lc.alignment = BOLD, Alignment(vertical="top")
        c = ws.cell(row=r, column=2, value=text)
        c.font, c.alignment = BODY_FONT, Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=13)
        ws.row_dimensions[r].height = estimate_height([(text, 120)])
        if colour:
            ws.cell(row=r, column=1).fill = PatternFill("solid", fgColor=colour)
        r += 1

    # ---- sources
    r += 1
    ws.cell(row=r, column=1, value="Sources").font = SUBTITLE_FONT
    r += 1
    for j, h in enumerate(["File", "", "", "State", "", "Last commit", "", "", "SHA-256 (first 16)"], start=1):
        if h:
            c = ws.cell(row=r, column=j, value=h)
            c.font = BOLD
    for p in prov:
        r += 1
        ws.cell(row=r, column=1, value=p["path"]).font = BODY_FONT
        ws.cell(row=r, column=4, value=p["state"]).font = BODY_FONT
        ws.cell(row=r, column=6, value=p["last_commit"]).font = BODY_FONT
        ws.cell(row=r, column=9, value=p["sha256"]).font = BODY_FONT
    r += 1
    n_warn = len(log.warnings)
    ws.cell(row=r, column=1, value=(f"Parse warnings: {n_warn} — see the 'Parse log' tab." if n_warn
                                    else "Parse warnings: none.")).font = BOLD if n_warn else NOTE_FONT

    # ---- chart: stacked bars of class by module
    chart = BarChart()
    chart.type = "bar"
    chart.grouping = "stacked"
    chart.overlap = 100
    chart.gapWidth = 60
    chart.title = "Requirements by reachability class"
    chart.y_axis.title = "Requirements"
    chart.x_axis.title = None
    chart.y_axis.majorGridlines = None
    chart.height, chart.width = 7.5, 16
    chart.legend.position = "b"
    cats_rows = [row_of[k] for k in ("CGF", "POL", "ESC", "Supplementary")]
    # categories/values must be contiguous: CGF, POL, ESC are; Supplementary sits after Mandatory.
    # Plot CGF..ESC plus Supplementary by referencing CGF..Supplementary and hiding nothing would include
    # the Mandatory total, so the chart uses its own small, formula-linked block instead.
    cb = grid_top  # chart block to the right of the sources area, formula-linked to the grid
    cb_col = 15  # column O
    ws.cell(row=cb - 1, column=cb_col, value="Chart data").font = NOTE_FONT
    for j, k in enumerate(CLASSES, start=1):
        ws.cell(row=cb - 1, column=cb_col + j, value=f"({k})").font = NOTE_FONT
    for i, (key, rr) in enumerate(zip(("CGF", "POL", "ESC", "Supplementary"), cats_rows)):
        ws.cell(row=cb + i, column=cb_col, value=key).font = NOTE_FONT
        for j in range(1, 5):
            c = ws.cell(row=cb + i, column=cb_col + j, value=f"={get_column_letter(1 + j)}{rr}")
            c.font = NOTE_FONT
    data = Reference(ws, min_col=cb_col + 1, max_col=cb_col + 4, min_row=cb - 1, max_row=cb + 3)
    cats = Reference(ws, min_col=cb_col, min_row=cb, max_row=cb + 3)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    for s, k in zip(chart.series, CLASSES):
        s.graphicalProperties.solidFill = CHART_COLOURS[k]
        s.graphicalProperties.line.solidFill = CHART_COLOURS[k]
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    for flag in ("showSerName", "showCatName", "showLegendKey", "showPercent", "showLeaderLines"):
        setattr(chart.dataLabels, flag, False)
    chart.x_axis.scaling.orientation = "maxMin"  # CGF on top
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    for col in range(cb_col, cb_col + 5):
        ws.column_dimensions[get_column_letter(col)].width = 8
    ws.add_chart(chart, f"O{cb + 6}")
    page_setup(ws)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)

    return {
        "tabs": {name: wb[name].max_row for name in wb.sheetnames},
        "rows": {
            "Requirements map": len(map_rows), "All requirements": len(reqs), **module_counts, "Gaps": len(gap_rows), "Screens": len(scr_rows),
            "Deployment readiness": len(dep_rows), "Epics": len(ep_rows), "Test cases": len(tc_rows),
            "Parse log": len(log.entries),
        },
        "has_story_status": ep["has_story_status"],
        "story_extra_cols": ep["extra_cols"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--strict", action="store_true", help="exit 2 if anything failed to parse")
    args = ap.parse_args()

    log = Log()
    result = build(args.repo.resolve(), args.out.expanduser().resolve(), log)
    print(f"wrote {args.out}")
    for name, n in result["rows"].items():
        print(f"  {name:<22} {n:>4} rows")
    print(f"  story Status column present: {'yes' if result['has_story_status'] else 'no'}"
          + (f" (extra story columns: {', '.join(result['story_extra_cols'])})" if result["story_extra_cols"] else ""))
    warns = log.warnings
    print(f"parse warnings: {len(warns)}")
    for _, where, msg in warns:
        print(f"  WARN {where}: {msg}")
    return 2 if (args.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())
