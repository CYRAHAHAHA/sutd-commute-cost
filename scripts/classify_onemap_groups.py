from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from commute.addresses.discovery import normalize_address, normalize_postal
from commute.config import ConfigError, expected_samples, load_config, resolve_path
from commute.db import init_addresses_db
from commute.routing_groups import representative_for_group


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Classify named URA condo/EC developments into one deterministic OneMap route point."
    )
    result.add_argument(
        "--geojson",
        default="data/input/URA_NoOfDwellingUnits.geojson",
        help="Downloaded URA No of Dwelling Units GeoJSON",
    )
    result.add_argument("--dry-run", action="store_true", help="Report groups without changing SQLite")
    return result


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _project_members(path: str | Path, allowed_types: set[str]) -> dict[str, set[str]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    groups: dict[str, set[str]] = defaultdict(set)
    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        raw_property_type = normalize_address(properties.get("PROP_TYPE"))
        property_type = {
            "NON-LANDED": "PRIVATE_NON_LANDED",
            "EC": "EXECUTIVE_CONDOMINIUM",
            "LANDED": "PRIVATE_LANDED",
        }.get(raw_property_type, "PRIVATE_RESIDENTIAL")
        project = normalize_address(properties.get("PROJ_NAME"))
        postal = normalize_postal(properties.get("POSTALCODE"))
        if property_type in allowed_types and project and postal:
            groups[project].add(postal)
    return groups


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config()
        grouping = config["providers"]["ONEMAP"].get("origin_grouping", {})
        if not grouping.get("enabled"):
            raise ConfigError("OneMap origin grouping is disabled in config/project.json")
        groups = _project_members(args.geojson, set(grouping.get("residential_types", [])))
        connection = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        all_rows = {
            row["postal_code"]: row
            for row in connection.execute(
                "SELECT * FROM residential_address WHERE source=?", (grouping["source"],)
            )
        }
        classified: list[tuple[str, list]] = []
        for project, postcodes in groups.items():
            members = [all_rows[postal] for postal in sorted(postcodes) if postal in all_rows]
            if members:
                classified.append((project, members))
        grouped_postcodes = sum(len(members) for _, members in classified)
        representatives = len(classified)
        total_rows = connection.execute(
            "SELECT COUNT(*) FROM residential_address WHERE confidence IN ('VERIFIED','LIKELY')"
        ).fetchone()[0]
        excluded_types = set(grouping.get("excluded_residential_types", []))
        excluded_rows = connection.execute(
            "SELECT COUNT(*) FROM residential_address WHERE confidence IN ('VERIFIED','LIKELY') "
            "AND residential_type IN ({})".format(",".join("?" for _ in excluded_types)),
            tuple(excluded_types),
        ).fetchone()[0] if excluded_types else 0
        route_origins = total_rows - excluded_rows - grouped_postcodes + representatives
        print(
            f"URA named condo/EC members: {grouped_postcodes:,}; developments: {representatives:,}; "
            f"scheduled-mapping exclusions: {excluded_rows:,}; "
            f"route origins after grouping: {route_origins:,}; "
            f"OneMap observations at current config: {route_origins * expected_samples(config, 'ONEMAP'):,}"
        )
        if args.dry_run:
            return 0

        connection.execute(
            """
            UPDATE residential_address
            SET onemap_group_key=NULL, onemap_group_representative=NULL,
                onemap_group_size=NULL, onemap_group_method=NULL,
                onemap_exclusion_reason=NULL
            WHERE source=?
            """,
            (grouping["source"],),
        )
        if excluded_types:
            placeholders = ",".join("?" for _ in excluded_types)
            connection.execute(
                f"UPDATE residential_address SET onemap_exclusion_reason=? "
                f"WHERE source=? AND residential_type IN ({placeholders})",
                (grouping["excluded_reason"], grouping["source"], *excluded_types),
            )
        for project, members in classified:
            representative = representative_for_group(members)
            group_key = f"URA_PROJECT:{project}"
            for member in members:
                connection.execute(
                    """
                    UPDATE residential_address
                    SET onemap_group_key=?, onemap_group_representative=?,
                        onemap_group_size=?, onemap_group_method=?
                    WHERE postal_code=?
                    """,
                    (group_key, representative["postal_code"], len(members), grouping["method"], member["postal_code"]),
                )
        connection.commit()
        print(f"Classified {grouped_postcodes:,} URA postcodes into {representatives:,} route groups.")
        return 0
    except (ConfigError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
