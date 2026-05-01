#!/usr/bin/env python3
"""
squeezemetrics-update-data — refresh DIX/GEX data from squeezemetrics.com.

Reads the canonical CSV at <plugin_root>/_shared/DIX-3.csv, fetches fresh rows
from https://squeezemetrics.com/monitor/static/DIX.csv, appends new dates to the
CSV, rewrites the Parquet mirror at <TB_ROOT>/alex-data/squeezemetrics/data.parquet,
and updates <TB_ROOT>/alex-data/.sync-meta.json.

Path resolution is layout-agnostic — works for both the maintainer's dev folder
(_shared/ as sibling of skill folder's parent) and a subscriber's plugin cache
(_shared/ at plugin root, two levels up from the skill folder).

Runtime touches only these paths:
  - <plugin_root>/_shared/DIX-3.csv                      (read + atomic rewrite)
  - https://squeezemetrics.com/monitor/static/DIX.csv    (read)
  - <TB_ROOT>/alex-data/squeezemetrics/data.parquet      (atomic rewrite)
  - <TB_ROOT>/alex-data/.sync-meta.json                  (atomic rewrite)
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

# ── Paths (resolved at runtime; layout-agnostic) ──────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent

def _resolve_shared_dir() -> Path:
    """Find the _shared/ folder containing DIX-3.csv. Tries both the dev layout
    (skill_folder/../_shared/) and the published cache layout
    (skill_folder/../../_shared/) — whichever has DIX-3.csv wins."""
    for candidate in (SKILL_DIR.parent / "_shared", SKILL_DIR.parent.parent / "_shared"):
        if (candidate / "DIX-3.csv").exists():
            return candidate
    raise FileNotFoundError(
        f"Could not locate _shared/DIX-3.csv. Tried: "
        f"{SKILL_DIR.parent / '_shared'} and {SKILL_DIR.parent.parent / '_shared'}"
    )

def _resolve_tb_root() -> Path:
    """Walk up from cwd to find the TB Data root (directory containing
    alex_tradeblocks_startup_config.md). Falls back to ancestor of skill folder
    if cwd isn't under TB root."""
    for start in (Path.cwd(), SKILL_DIR):
        for parent in [start, *start.parents]:
            if (parent / "alex_tradeblocks_startup_config.md").exists():
                return parent
    raise FileNotFoundError(
        "TB root not found. Run this script with cwd inside the TradeBlocks Data root."
    )

SHARED_DIR = _resolve_shared_dir()
TB_ROOT = _resolve_tb_root()

CSV_PATH = SHARED_DIR / "DIX-3.csv"
PARQUET_PATH = TB_ROOT / "alex-data" / "squeezemetrics" / "data.parquet"
SYNC_META_PATH = TB_ROOT / "alex-data" / ".sync-meta.json"

SOURCE_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
USER_AGENT = "Mozilla/5.0 (compatible; TradeBlocks-alex-squeezemetrics-update-data)"


# ── Atomic write helpers ──────────────────────────────────────────────────────
def atomic_write_text(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(tmp, index=False, engine="pyarrow")
    os.replace(tmp, path)


def atomic_write_json(path: Path, obj: dict) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2) + "\n")


# ── Fetch + parse ─────────────────────────────────────────────────────────────
def fetch_upstream_csv(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse_csv_str(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    expected = ["date", "price", "dix", "gex"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing expected columns: {missing}. Got: {list(df.columns)}")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for c in ("price", "dix", "gex"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[expected]


# ── Sync-meta update ──────────────────────────────────────────────────────────
def update_sync_meta(now_iso: str, latest_date, row_count: int) -> None:
    existing: dict = {}
    if SYNC_META_PATH.exists():
        try:
            existing = json.loads(SYNC_META_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing["squeezemetrics"] = {
        "source_url": SOURCE_URL,
        "csv_path": str(CSV_PATH.relative_to(TB_ROOT)),
        "parquet_path": str(PARQUET_PATH.relative_to(TB_ROOT)),
        "last_refresh": now_iso,
        "latest_date": str(latest_date),
        "row_count": row_count,
    }
    atomic_write_json(SYNC_META_PATH, existing)


# ── Parquet build (preserves existing source_updated) ─────────────────────────
def build_parquet(merged: pd.DataFrame, now_ts: pd.Timestamp) -> pd.DataFrame:
    """Return the full Parquet frame with source_updated preserved for existing
    rows and set to `now_ts` for new rows."""
    out = merged.copy()
    if PARQUET_PATH.exists():
        existing = pd.read_parquet(PARQUET_PATH)
        existing["date"] = pd.to_datetime(existing["date"]).dt.date
        if "source_updated" not in existing.columns:
            existing["source_updated"] = pd.Series([pd.NaT] * len(existing), dtype="datetime64[ns, UTC]")
        out = out.merge(existing[["date", "source_updated"]], on="date", how="left")
    else:
        out["source_updated"] = pd.Series([pd.NaT] * len(out), dtype="datetime64[ns, UTC]")
    # Ensure datetime dtype before filling, then fill missing with now
    out["source_updated"] = pd.to_datetime(out["source_updated"], utc=True)
    out["source_updated"] = out["source_updated"].fillna(now_ts.tz_convert("UTC") if now_ts.tz is not None else now_ts.tz_localize("UTC"))
    return out


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and diff but do not write any files.")
    args = parser.parse_args()

    now_iso = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    now_ts = pd.Timestamp(now_iso)

    # 1. Read canonical CSV
    if not CSV_PATH.exists():
        print(f"ERROR: canonical CSV missing at {CSV_PATH}", file=sys.stderr)
        return 1
    local = parse_csv_str(CSV_PATH.read_text(encoding="utf-8"))
    local_latest = local["date"].max()
    print(f"Local CSV: {len(local):,} rows, latest date {local_latest}")

    # 2. Fetch upstream
    print(f"Fetching {SOURCE_URL} ...")
    try:
        upstream_text = fetch_upstream_csv(SOURCE_URL)
    except Exception as e:
        print(f"ERROR: upstream fetch failed: {e}", file=sys.stderr)
        return 1
    upstream = parse_csv_str(upstream_text)
    print(f"Upstream: {len(upstream):,} rows, latest date {upstream['date'].max()}")

    # 3. Diff
    new_rows = upstream[upstream["date"] > local_latest].copy()

    if new_rows.empty:
        print("No new rows — already up to date.")
        if args.dry_run:
            return 0
        if not PARQUET_PATH.exists():
            print(f"Parquet missing — writing initial mirror to {PARQUET_PATH.relative_to(TB_ROOT)}")
            pq = build_parquet(local, now_ts)
            atomic_write_parquet(pq, PARQUET_PATH)
        # Always refresh the watermark on a successful run — keeps last_refresh current
        # even when no new rows arrived, and self-heals if the sync-meta file went missing.
        update_sync_meta(now_iso, local_latest, len(local))
        print(f"Sync meta refreshed: {SYNC_META_PATH.relative_to(TB_ROOT)}")
        return 0

    print(f"New rows: {len(new_rows):,} (dates {new_rows['date'].min()} → {new_rows['date'].max()})")

    if args.dry_run:
        print("(dry-run — no writes)")
        return 0

    # 4. Merge + rewrite CSV
    merged = pd.concat([local, new_rows], ignore_index=True).sort_values("date").reset_index(drop=True)
    csv_buf = io.StringIO()
    merged.to_csv(csv_buf, index=False, date_format="%Y-%m-%d")
    atomic_write_text(CSV_PATH, csv_buf.getvalue())
    print(f"CSV updated: {len(merged):,} rows → {CSV_PATH.relative_to(TB_ROOT)}")

    # 5. Rewrite Parquet (preserving existing source_updated where possible)
    pq = build_parquet(merged, now_ts)
    atomic_write_parquet(pq, PARQUET_PATH)
    print(f"Parquet rewritten: {len(pq):,} rows → {PARQUET_PATH.relative_to(TB_ROOT)}")

    # 6. Update sync-meta
    update_sync_meta(now_iso, merged["date"].max(), len(merged))
    print(f"Sync meta updated: {SYNC_META_PATH.relative_to(TB_ROOT)}")

    # Summary
    print()
    print("=== Summary ===")
    print(f"Rows fetched: {len(upstream):,}")
    print(f"New rows added: {len(new_rows):,}")
    print(f"Date range added: {new_rows['date'].min()} → {new_rows['date'].max()}")
    print(f"Final row count: {len(merged):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
