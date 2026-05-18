"""Render every slide of a .pptx as a JPG image for visual QA.

Pipeline: pptx --(soffice)--> pdf --(pdftoppm)--> slide-01.jpg, slide-02.jpg, ...

Usage:
    python thumbnails.py <input.pptx> <output_dir> [--dpi 150]

Drop into the sandbox at /home/user/skills/pptx/scripts/thumbnails.py. Requires
`libreoffice` (`soffice`) and `poppler-utils` (`pdftoppm`) to be installed
(both are baked into the agent-swarm-sandbox template).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _soffice_env() -> dict:
    env = os.environ.copy()
    env.setdefault("SAL_USE_VCLPLUGIN", "svp")
    return env


def render(pptx_path: Path, out_dir: Path, dpi: int = 150) -> list[Path]:
    if not pptx_path.exists() or pptx_path.suffix.lower() != ".pptx":
        raise SystemExit(f"Invalid pptx file: {pptx_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # 1. pptx -> pdf
        r = subprocess.run(
            ["soffice", "--headless", "--norestore",
             "--convert-to", "pdf", "--outdir", str(tmp_path),
             str(pptx_path.absolute())],
            capture_output=True, text=True, env=_soffice_env(), timeout=120,
        )
        if r.returncode != 0:
            raise SystemExit(f"soffice failed: {r.stderr.strip() or r.stdout.strip()}")

        pdfs = list(tmp_path.glob("*.pdf"))
        if not pdfs:
            raise SystemExit("soffice produced no PDF")
        pdf = pdfs[0]

        # 2. pdf -> slide-NN.jpg
        prefix = out_dir / "slide"
        r = subprocess.run(
            ["pdftoppm", "-jpeg", "-r", str(dpi), str(pdf), str(prefix)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            raise SystemExit(f"pdftoppm failed: {r.stderr.strip()}")

    images = sorted(out_dir.glob("slide-*.jpg"))
    return images


def main() -> int:
    p = argparse.ArgumentParser(description="Render pptx slides to JPGs for visual QA.")
    p.add_argument("input", type=Path, help="Input .pptx path")
    p.add_argument("output_dir", type=Path, help="Directory to write slide-NN.jpg into")
    p.add_argument("--dpi", type=int, default=150, help="Render DPI (default: 150)")
    args = p.parse_args()

    if shutil.which("soffice") is None:
        print("error: 'soffice' not found on PATH (install libreoffice)", file=sys.stderr)
        return 2
    if shutil.which("pdftoppm") is None:
        print("error: 'pdftoppm' not found on PATH (install poppler-utils)", file=sys.stderr)
        return 2

    imgs = render(args.input, args.output_dir, args.dpi)
    print(f"Wrote {len(imgs)} slide image(s) to {args.output_dir}/")
    for img in imgs:
        print(f"  {img}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
