"""Lint the charts in an .xlsx for defects that make a dashboard render blank or
garbled but that the formula recalc step (recalc.py) cannot catch. openpyxl writes
only the chart's formula references, never the plotted values, so a chart pointing at
the wrong range or wrong orientation raises no formula error — it just renders empty.

Single-file helper. Drop into the sandbox at
/home/user/skills/xlsx/scripts/chart_lint.py and run:

    python chart_lint.py <path-to-xlsx>

Checks, per chart:
  - the chart has at least one data series                       (empty_chart)
  - every series has a title                                     (untitled_series -> "Series1..N")
  - line/area series reference a multi-cell range (>=2 points)   (single_point_series -> blank line)
  - charts on the same sheet do not overlap                      (overlapping_charts)

Returns a JSON report to stdout:
    {
      "status": "success" | "issues_found",
      "total_charts": <int>,
      "total_issues": <int>,
      "issues": [ {"chart": "chart1.xml", "title": "...", "type": "...", "detail": "..."} ]
    }

Works on both openpyxl-native files (no namespace prefix, no cached values) and files
already recalculated by LibreOffice (c: prefix, cached values) — series length is always
measured from the range reference, which is present in both.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile

# Default Excel cell dimensions in pixels — good enough to detect gross anchor overlap.
COL_PX = 64.0
ROW_PX = 20.0
EMU_PER_PX = 9525.0


def _strip_c(xml: str) -> str:
    """Drop the optional `c:` chart namespace prefix so one set of patterns matches
    both openpyxl-native (`<ser>`) and LibreOffice-recalced (`<c:ser>`) XML."""
    return xml.replace("<c:", "<").replace("</c:", "</")


def _ref_cell_count(ref: str) -> int:
    """Number of cells a reference like `'Sheet'!$B$9:$F$9` covers (single cell -> 1)."""
    body = ref.split("!")[-1].replace("$", "")
    if ":" not in body:
        return 1
    a, b = body.split(":")
    ma = re.match(r"([A-Z]+)(\d+)", a)
    mb = re.match(r"([A-Z]+)(\d+)", b)
    if not (ma and mb):
        return 0
    from openpyxl.utils import column_index_from_string as ci

    cols = abs(ci(mb.group(1)) - ci(ma.group(1))) + 1
    rows = abs(int(mb.group(2)) - int(ma.group(2))) + 1
    return cols * rows


def _chart_title(xml: str) -> str:
    m = re.search(r"<title>.*?<a:t>(.*?)</a:t>", xml, re.S)
    return m.group(1) if m else ""


def _check_series(charts: dict[str, str]) -> list[dict]:
    issues: list[dict] = []
    for name, raw in charts.items():
        x = _strip_c(raw)
        title = _chart_title(x) or "(untitled chart)"
        is_line = ("<lineChart>" in x) or ("<areaChart>" in x)
        sers = re.findall(r"<ser>.*?</ser>", x, re.S)
        if not sers:
            issues.append({"chart": name, "title": title, "type": "empty_chart",
                           "detail": "chart has no data series"})
            continue
        for i, s in enumerate(sers):
            if "<tx>" not in s:
                issues.append({"chart": name, "title": title, "type": "untitled_series",
                               "detail": f"series {i} has no title (legend will show Series{i + 1})"})
            if is_line:
                vm = re.search(r"<val>.*?<f>(.*?)</f>", s, re.S)
                n = _ref_cell_count(vm.group(1)) if vm else 0
                if n < 2:
                    issues.append({"chart": name, "title": title, "type": "single_point_series",
                                   "detail": f"line series {i} spans {n} cell(s); needs >=2 to draw "
                                             f"(likely missing from_rows=True)"})
    return issues


def _strip_xdr(xml: str) -> str:
    """Drop the optional `xdr:` drawing prefix so one set of patterns matches both
    openpyxl-native (`<oneCellAnchor>`) and LibreOffice (`<xdr:oneCellAnchor>`) XML.
    Leaves `a:`/`c:` prefixes intact (e.g. `<a:ext>` inside `<a:xfrm>`)."""
    return xml.replace("<xdr:", "<").replace("</xdr:", "</")


def _anchor_rects(drawing_xml: str) -> list[tuple[float, float, float, float]]:
    d = _strip_xdr(drawing_xml)
    rects = []
    for m in re.finditer(r"<(oneCellAnchor|twoCellAnchor)\b[^>]*>(.*?)</\1>", d, re.S):
        a = m.group(2)
        if "graphicFrame" not in a:  # only chart frames; ignore images/shapes
            continue
        fc = re.search(r"<from>.*?<col>(\d+)</col>", a, re.S)
        fr = re.search(r"<from>.*?<row>(\d+)</row>", a, re.S)
        if not (fc and fr):
            continue
        x0, y0 = int(fc.group(1)) * COL_PX, int(fr.group(1)) * ROW_PX
        tc = re.search(r"<to>.*?<col>(\d+)</col>", a, re.S)
        tr = re.search(r"<to>.*?<row>(\d+)</row>", a, re.S)
        if tc and tr:  # twoCellAnchor: extent given by the `to` cell
            w = (int(tc.group(1)) - int(fc.group(1))) * COL_PX
            h = (int(tr.group(1)) - int(fr.group(1))) * ROW_PX
        else:  # oneCellAnchor: extent given by <ext> in EMU (not <a:ext>)
            ext = re.search(r'(?<![a-z]:)<ext[^>]*cx="(\d+)"[^>]*cy="(\d+)"', a)
            if not ext:
                continue
            w, h = int(ext.group(1)) / EMU_PER_PX, int(ext.group(2)) / EMU_PER_PX
        rects.append((x0, y0, x0 + w, y0 + h))
    return rects


def _check_overlaps(z: zipfile.ZipFile) -> list[dict]:
    issues: list[dict] = []
    for dn in sorted(n for n in z.namelist() if re.match(r"xl/drawings/drawing\d+\.xml$", n)):
        rects = _anchor_rects(z.read(dn).decode())
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ax0, ay0, ax1, ay1 = rects[i]
                bx0, by0, bx1, by1 = rects[j]
                if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                    issues.append({"chart": dn.split("/")[-1], "title": "",
                                   "type": "overlapping_charts",
                                   "detail": f"charts {i} and {j} overlap on the same sheet"})
    return issues


def lint(filename: str) -> dict:
    try:
        z = zipfile.ZipFile(filename)
    except (OSError, zipfile.BadZipFile) as e:
        return {"error": f"cannot open {filename}: {e}"}
    with z:
        chart_names = sorted(n for n in z.namelist() if re.match(r"xl/charts/chart\d+\.xml$", n))
        charts = {n.split("/")[-1]: z.read(n).decode() for n in chart_names}
        issues = _check_series(charts) + _check_overlaps(z)
    return {
        "status": "success" if not issues else "issues_found",
        "total_charts": len(charts),
        "total_issues": len(issues),
        "issues": issues,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: chart_lint.py <xlsx_file>"}))
        return 1
    print(json.dumps(lint(sys.argv[1]), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
