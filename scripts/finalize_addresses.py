from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from commute.addresses.hdb import HDB_SOURCE, read_hdb_residential_csv
from commute.addresses.ura import URA_SOURCE, read_ura_postal_codes
from commute.config import ConfigError, load_config, resolve_path
from commute.db import init_addresses_db


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Finalize the verified residential address database for production.")
    result.add_argument(
        "--confirm-production",
        action="store_true",
        help="Required before removing the known sample_fixture rows",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.confirm_production:
        print("Refusing to remove fixtures without --confirm-production.", file=sys.stderr)
        return 2
    try:
        config = load_config()
        database = resolve_path(config, config["addresses"]["database"])
        connection = init_addresses_db(database)
        hdb_expected = len(read_hdb_residential_csv("data/input/HDBPropertyInformation.csv"))
        hdb_success = int(
            connection.execute(
                "SELECT COUNT(*) FROM address_resolution WHERE source=? AND status='SUCCESS'", (HDB_SOURCE,)
            ).fetchone()[0]
        )
        hdb_failed = int(
            connection.execute(
                "SELECT COUNT(*) FROM address_resolution WHERE source=? AND status='FAILED'", (HDB_SOURCE,)
            ).fetchone()[0]
        )
        ura_postals = read_ura_postal_codes("data/input/URA_NoOfDwellingUnits.geojson")
        hdb_postals = {
            row[0]
            for row in connection.execute(
                "SELECT postal_code FROM residential_address WHERE source=?", (HDB_SOURCE,)
            )
        }
        ura_hdb_overlaps = len(ura_postals & hdb_postals)
        ura_expected = len(ura_postals) - ura_hdb_overlaps
        ura_imported = int(
            connection.execute("SELECT COUNT(*) FROM residential_address WHERE source=?", (URA_SOURCE,)).fetchone()[0]
        )
        if hdb_success != hdb_expected or hdb_failed or ura_imported != ura_expected:
            raise ConfigError(
                "Production finalization requires complete HDB and URA imports: "
                f"HDB {hdb_success}/{hdb_expected} with {hdb_failed} failures; "
                f"URA {ura_imported}/{ura_expected} ({ura_hdb_overlaps} HDB overlaps retained)"
            )
        fixture_count = int(
            connection.execute("SELECT COUNT(*) FROM residential_address WHERE source='sample_fixture'").fetchone()[0]
        )
        if fixture_count == 0:
            print("No sample_fixture rows remain; production database is already finalized.")
            return 0
        backup = Path(database).with_name(Path(database).stem + ".pre_production.sqlite")
        if backup.exists():
            raise ConfigError(f"Refusing to overwrite existing backup: {backup}")
        shutil.copy2(database, backup)
        connection.execute("DELETE FROM residential_address WHERE source='sample_fixture'")
        connection.commit()
        print(f"Removed {fixture_count:,} sample_fixture rows after backup: {backup}")
        return 0
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
