"""Command-line entry point for one-shot or interval radar execution."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from catalog import load_product_aliases, load_products

from .importers import load_sources, load_watches
from .pipeline import RadarPipeline
from .persistence import RadarStore


def initialize_runtime(root: Path) -> Path:
    user = root / "data" / "user"
    user.mkdir(parents=True, exist_ok=True)
    for runtime, template in (
        ("radar_sources.json", "radar_sources.example.json"),
        ("radar_wishlist.csv", "radar_wishlist.example.csv"),
        ("manual_listings.csv", "manual_listings.example.csv"),
    ):
        target = user / runtime
        source = root / "data" / "templates" / template
        if not target.exists():
            shutil.copyfile(str(source), str(target))
    return user


def execute_once(root: Path, dry_run: bool = False, source_ids=None,
                 allow_private_network: bool = False, import_directory=None):
    user = initialize_runtime(root)
    products = load_products(root / "data" / "products.csv")
    aliases = load_product_aliases(root / "data" / "product_aliases.csv", products)
    sources = load_sources(user / "radar_sources.json")
    watches = load_watches(user / "radar_wishlist.csv", products, sources)
    if source_ids:
        requested = set(source_ids)
        unknown = requested - {source.source_id for source in sources}
        if unknown:
            raise ValueError(f"unknown source ID: {sorted(unknown)[0]}")
        sources = [source for source in sources if source.source_id in requested]
    return RadarPipeline(RadarStore(user), products, aliases,
                         user_directory=user,
                         import_directory=import_directory or user / "imports",
                         allow_private_network=allow_private_network).run(
                             sources, watches, dry_run=dry_run)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the local universal radar")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--interval-minutes", type=int, default=0)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--allow-private-network", action="store_true")
    parser.add_argument("--import-dir", type=Path)
    args = parser.parse_args(argv)
    if args.interval_minutes and args.interval_minutes < 60:
        parser.error("--interval-minutes must be at least 60")
    root = Path(__file__).resolve().parents[2]
    user = initialize_runtime(root)
    lock = user / ".radar.lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("Radar is already running.", file=sys.stderr)
        return 1
    try:
        os.close(descriptor)
        while True:
            # Source selection and development overrides are applied without
            # changing persisted configuration.
            result = execute_once(root, args.dry_run, args.source,
                                  args.allow_private_network, args.import_dir)
            print(f"Radar run: {result.run.status.value}")
            print(f"Relevant listings: {len(result.listings)}")
            print(f"Ignored records: {result.run.listing_count_ignored}")
            if not args.interval_minutes:
                return 0 if result.run.status.value in {"COMPLETED", "DRY_RUN"} else 1
            time.sleep(args.interval_minutes * 60)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
