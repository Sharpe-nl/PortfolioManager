#!/usr/bin/env python3
"""Download pinned vendor assets (Chart.js and Pico.css) into app/static/vendor/.

Run once after cloning:
  python scripts/download_vendors.py
"""
import urllib.request
from pathlib import Path

VENDOR_DIR = Path(__file__).parent.parent / "app" / "static" / "vendor"

VENDORS: dict[str, str] = {
    "chart.umd.js": (
        "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"
    ),
    "pico.min.css": (
        "https://cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css"
    ),
}


def main() -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in VENDORS.items():
        dest = VENDOR_DIR / filename
        if dest.exists():
            print(f"  {filename}: already present — skipping")
            continue
        print(f"  {filename}: downloading from {url} …")
        try:
            urllib.request.urlretrieve(url, dest)
            size = dest.stat().st_size
            print(f"  {filename}: saved ({size:,} bytes)")
        except Exception as exc:
            print(f"  {filename}: FAILED — {exc}")
    print("Done.")


if __name__ == "__main__":
    main()
