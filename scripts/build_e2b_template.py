"""Build and register the shared E2B sandbox template.

Run once per environment:

    python scripts/build_e2b_template.py

Copy the printed ``E2B_TEMPLATE_ID`` value into your ``.env`` file so the
swarm conductor can pick it up at runtime. Requires ``E2B_API_KEY`` in the
environment.

The build takes several minutes — the Python 3.12 base image is downloaded
and the listed packages get installed before the template is published.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from e2b import Template


TEMPLATE_NAME = "agent-swarm-sandbox"


def main() -> int:
    load_dotenv()
    if not os.getenv("E2B_API_KEY"):
        print("error: E2B_API_KEY is not set in the environment.", file=sys.stderr)
        return 1

    template = (
        Template()
        .from_python_image("3.12")
        .pip_install([
            # Data + analysis
            "pandas",
            "numpy",
            "matplotlib",
            "scipy",
            "tabulate",
            "yfinance",
            # Web
            "requests",
            "beautifulsoup4",
            "lxml",
            # xlsx skill
            "openpyxl",
            "xlsxwriter",
            # pptx skill
            "python-pptx",
            "Pillow",
            "markitdown[pptx]",
        ])
        .apt_install([
            "ripgrep", "curl", "git", "jq",
            # xlsx/pptx skills need LibreOffice for formula recalc + slide rendering,
            # and poppler-utils for the PDF -> JPG step used in pptx visual QA.
            "libreoffice",
            "poppler-utils",
            "fonts-liberation",
        ])
        .make_dir("/home/user/workspace")
        .make_dir("/home/user/workspace/artifacts")
        .make_dir("/home/user/skills")
    )

    print(f"Building E2B template '{TEMPLATE_NAME}' — this may take a few minutes...")
    build_info = Template.build(template, TEMPLATE_NAME)
    print("\nTemplate built successfully.")
    print("\nAdd this to your .env file:\n")
    print(f"E2B_TEMPLATE_ID={build_info.template_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
