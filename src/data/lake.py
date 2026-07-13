"""Parquet research lake: year-partitioned OHLC storage with a JSON
manifest, validation-on-ingest (with quarantine of rejected batches),
and time/usage-based retention pruning.

Layout on disk (under `root`):
    <root>/<broker>/<symbol>/<tf>/<year>.parquet   -- data partitions
    <root>/manifest.json                           -- per-partition metadata
    <root>/.rejected/<ts>_<symbol>_<tf>.csv         -- quarantined batches
    <root>/.rejected/<ts>_<symbol>_<tf>.reason.txt  -- why it was rejected
    <root>/frozen/...                               -- structurally exempt
                                                        from prune(); also
                                                        the only part of the
                                                        lake meant to be
                                                        committed to git
                                                        (see .gitignore).

This module is purely additive research-lake infrastructure. It is not
wired into the live trading path (src/core|execution|arbiter|strategies).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

REQUIRED_COLS = ("time", "open", "high", "low", "close")
_MANIFEST_NAME = "manifest.json"
_REJECTED_DIR = ".rejected"
_FROZEN_DIR = "frozen"


class LakeError(ValueError):
    """Raised for lake validation failures and lookup misses."""


class Lake:
    """A small, single-process Parquet research lake.

    Not thread/process-safe: manifest.json is read-modify-written whole,
    which is fine for the offline/research usage this targets.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.root / _MANIFEST_NAME

    # ------------------------------------------------------------------
    # manifest
    # ------------------------------------------------------------------
    def manifest(self) -> dict:
        if not self._manifest_path.exists():
            return {}
        with open(self._manifest_path, "r") as f:
            return json.load(f)

    def _write_manifest(self, data: dict) -> None:
        tmp = self._manifest_path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(self._manifest_path)

    # ------------------------------------------------------------------
    # paths
    # ------------------------------------------------------------------
    def _partition_dir(self, broker: str, symbol: str, tf: str) -> Path:
        return self.root / broker / symbol / tf

    def _is_frozen(self, path: Path) -> bool:
        try:
            path.relative_to(self.root / _FROZEN_DIR)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # validation + quarantine
    # ------------------------------------------------------------------
    def _quarantine(self, df: pd.DataFrame, symbol: str, tf: str, reason: str) -> None:
        qdir = self.root / _REJECTED_DIR
        qdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        base = f"{ts}_{symbol}_{tf}"
        csv_path = qdir / f"{base}.csv"
        reason_path = qdir / f"{base}.reason.txt"
        try:
            df.to_csv(csv_path, index=False)
        except Exception:
            csv_path.write_text("")
        reason_path.write_text(reason)

    def _validate(self, df: pd.DataFrame, symbol: str, tf: str) -> pd.DataFrame:
        missing = [c for c in REQUIRED_COLS if c not in df.columns]
        if missing:
            reason = f"missing required columns: {missing}"
            self._quarantine(df, symbol, tf, reason)
            raise LakeError(reason)

        try:
            parsed_time = pd.to_datetime(df["time"], errors="raise")
        except Exception as exc:
            reason = f"time column not parseable: {exc}"
            self._quarantine(df, symbol, tf, reason)
            raise LakeError(reason)

        work = df.copy()
        work["time"] = parsed_time

        # Coerce OHLC to numeric BEFORE the NaN + geometry checks: string
        # data would otherwise compare lexicographically (e.g. "9" > "10")
        # and defeat the geometry checks, then land in parquet as str.
        # Coercion failures become NaN and are rejected by the check below.
        for col in ("open", "high", "low", "close"):
            work[col] = pd.to_numeric(work[col], errors="coerce")

        for col in ("open", "high", "low", "close"):
            if work[col].isna().any():
                reason = f"non-numeric or NaN present in OHLC column '{col}'"
                self._quarantine(df, symbol, tf, reason)
                raise LakeError(reason)

        if (work["high"] < work["low"]).any():
            reason = "high < low on at least one row"
            self._quarantine(df, symbol, tf, reason)
            raise LakeError(reason)
        if (work["high"] < work["open"]).any() or (work["high"] < work["close"]).any():
            reason = "high < open/close on at least one row"
            self._quarantine(df, symbol, tf, reason)
            raise LakeError(reason)
        if (work["low"] > work["open"]).any() or (work["low"] > work["close"]).any():
            reason = "low > open/close on at least one row"
            self._quarantine(df, symbol, tf, reason)
            raise LakeError(reason)

        sorted_dedup = (
            work.sort_values("time", kind="mergesort")
            .drop_duplicates(subset="time", keep="last")
            .reset_index(drop=True)
        )
        if not sorted_dedup["time"].is_monotonic_increasing or sorted_dedup["time"].duplicated().any():
            reason = "time not strictly increasing after sort+dedupe"
            self._quarantine(df, symbol, tf, reason)
            raise LakeError(reason)

        return sorted_dedup

    # ------------------------------------------------------------------
    # ingest
    # ------------------------------------------------------------------
    def ingest(self, df: pd.DataFrame, broker: str, symbol: str, tf: str, source: str = "") -> list:
        """Validate `df` and write it into year partitions; returns paths written.

        Merge-dedupe tie-break policy: on overlapping re-ingest, NEW rows win
        timestamp ties — existing partition rows are concatenated before the
        incoming batch, sorted with a STABLE mergesort, then
        `drop_duplicates(subset="time", keep="last")` keeps the new row.
        (The stable sort is load-bearing: quicksort would shuffle ties.)
        """
        validated = self._validate(df, symbol, tf)

        pdir = self._partition_dir(broker, symbol, tf)
        pdir.mkdir(parents=True, exist_ok=True)

        validated = validated.copy()
        validated["_year"] = validated["time"].dt.year

        manifest = self.manifest()
        manifest.setdefault(broker, {}).setdefault(symbol, {}).setdefault(tf, {})
        now_iso = datetime.now(timezone.utc).isoformat()

        written = []
        for year, group in validated.groupby("_year"):
            group = group.drop(columns=["_year"]).reset_index(drop=True)
            path = pdir / f"{int(year)}.parquet"

            if path.exists():
                existing = pd.read_parquet(path, engine="pyarrow")
                existing["time"] = pd.to_datetime(existing["time"])
                merged = pd.concat([existing, group], ignore_index=True)
                merged = (
                    merged.sort_values("time", kind="mergesort")
                    .drop_duplicates(subset="time", keep="last")
                    .reset_index(drop=True)
                )
            else:
                merged = group.sort_values("time", kind="mergesort").reset_index(drop=True)

            merged.to_parquet(path, engine="pyarrow", index=False)
            written.append(str(path))

            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            year_key = str(int(year))
            prev_entry = manifest[broker][symbol][tf].get(year_key, {})
            manifest[broker][symbol][tf][year_key] = {
                "rows": int(len(merged)),
                "first_time": merged["time"].iloc[0].isoformat(),
                "last_time": merged["time"].iloc[-1].isoformat(),
                "sha256": sha,
                "source": source,
                "created": prev_entry.get("created", now_iso),
                "last_used": prev_entry.get("last_used", now_iso),
            }

        self._write_manifest(manifest)
        return written

    # ------------------------------------------------------------------
    # load
    # ------------------------------------------------------------------
    def load(
        self,
        symbol: str,
        tf: str,
        broker: str = "fbs",
        start=None,
        end=None,
    ) -> pd.DataFrame:
        manifest = self.manifest()
        sym_years = manifest.get(broker, {}).get(symbol, {}).get(tf, {})
        if not sym_years:
            existing = sorted(manifest.get(broker, {}).keys())
            raise LakeError(
                f"no lake partitions for {broker}/{symbol}/{tf}; "
                f"symbols available for broker '{broker}': {existing}"
            )

        pdir = self._partition_dir(broker, symbol, tf)
        frames = []
        for year in sorted(sym_years.keys()):
            path = pdir / f"{year}.parquet"
            if not path.exists():
                continue
            frame = pd.read_parquet(path, engine="pyarrow")
            frame["time"] = pd.to_datetime(frame["time"])
            frames.append(frame)

        if not frames:
            raise LakeError(f"manifest has entries for {broker}/{symbol}/{tf} but no partition files exist on disk")

        combined = (
            pd.concat(frames, ignore_index=True)
            .sort_values("time", kind="mergesort")
            .reset_index(drop=True)
        )

        if start is not None:
            combined = combined[combined["time"] >= pd.Timestamp(start)]
        if end is not None:
            combined = combined[combined["time"] <= pd.Timestamp(end)]
        combined = combined.reset_index(drop=True)

        now_iso = datetime.now(timezone.utc).isoformat()
        for year in sym_years:
            sym_years[year]["last_used"] = now_iso
        manifest[broker][symbol][tf] = sym_years
        self._write_manifest(manifest)

        return combined

    # ------------------------------------------------------------------
    # prune
    # ------------------------------------------------------------------
    def prune(
        self,
        active_years: int = 4,
        unused_days: int = 180,
        now: Optional[datetime] = None,
        dry_run: bool = True,
    ) -> list:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        cutoff_year = now.year - active_years
        unused_cutoff = now - timedelta(days=unused_days)

        manifest = self.manifest()
        candidates = []  # list of (broker, symbol, tf, year, path)

        for broker, symbols in manifest.items():
            for symbol, tfs in symbols.items():
                for tf, years in tfs.items():
                    for year, entry in years.items():
                        path = self._partition_dir(broker, symbol, tf) / f"{year}.parquet"
                        if self._is_frozen(path):
                            continue  # structural exclusion, no exceptions

                        if int(year) > cutoff_year:
                            continue  # not entirely older than active_years

                        last_used = datetime.fromisoformat(entry["last_used"])
                        if last_used.tzinfo is None:
                            last_used = last_used.replace(tzinfo=timezone.utc)
                        if last_used > unused_cutoff:
                            continue  # used too recently

                        candidates.append((broker, symbol, tf, year, path))

        if dry_run:
            return [str(path) for *_which, path in candidates]

        deleted = []
        for broker, symbol, tf, year, path in candidates:
            if path.exists():
                path.unlink()
            del manifest[broker][symbol][tf][year]
            # prune now-empty dict levels to keep the manifest tidy.
            if not manifest[broker][symbol][tf]:
                del manifest[broker][symbol][tf]
            if not manifest[broker][symbol]:
                del manifest[broker][symbol]
            if not manifest[broker]:
                del manifest[broker]
            deleted.append(str(path))

        self._write_manifest(manifest)
        return deleted
