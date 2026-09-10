from __future__ import annotations

import argparse
import sys

from commute.audit import audit_provider
from commute.config import ConfigError, load_config, resolve_path
from commute.db import init_addresses_db, init_observations_db, iter_observations, iter_onemap_origins


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Audit persisted commute observations against configured production jobs."
    )
    result.add_argument("--provider", choices=("GOOGLE", "ONEMAP", "ALL"), default="ALL")
    result.add_argument(
        "--require-complete",
        action="store_true",
        help="Return failure unless the selected provider population has every expected terminal observation",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config()
        addresses = init_addresses_db(resolve_path(config, config["addresses"]["database"]))
        observations = init_observations_db(resolve_path(config, config["observations_database"]))
        routed = list(iter_onemap_origins(addresses, config["addresses"]["include_confidence"], None, None))
        selected_google = [row for row in routed if row["google_sample_selected"]]
        populations = {"GOOGLE": selected_google, "ONEMAP": routed}
        minimum_google = int(
            config.get("google_sampling", {}).get(
                "minimum_production_sample_size", config.get("google_sampling", {}).get("sample_size", 0)
            )
        )
        providers = ("GOOGLE", "ONEMAP") if args.provider == "ALL" else (args.provider,)
        failed = False
        for provider in providers:
            result = audit_provider(
                config,
                provider,
                populations[provider],
                iter_observations(observations, provider=provider),
                minimum_population=minimum_google if provider == "GOOGLE" else 0,
            )
            print(
                f"{provider}: population {result['population']:,}; "
                f"jobs {result['persisted_jobs']:,}/{result['expected_jobs']:,}; "
                f"missing {result['missing_jobs']:,}; extra {result['unexpected_jobs']:,}; "
                f"duplicates {result['duplicate_keys']:,}; invariants {len(result['invariant_errors']):,}"
            )
            if not result["selection_ready"]:
                print(
                    f"  selection incomplete: {result['population']:,}/{result['minimum_population']:,} origins",
                    file=sys.stderr,
                )
            if result["missing_examples"]:
                print(f"  missing examples: {result['missing_examples']}")
            if result["unexpected_examples"]:
                print(
                    "  extra examples (retained smoke/history rows may be intentional): "
                    f"{result['unexpected_examples']}"
                )
            for error in result["invariant_errors"][:10]:
                print(f"  invariant error: {error}", file=sys.stderr)
            if result["duplicate_keys"] or result["invariant_errors"]:
                failed = True
            if args.require_complete and (result["missing_jobs"] or not result["selection_ready"]):
                failed = True
        if failed:
            print("OBSERVATION AUDIT FAILED", file=sys.stderr)
            return 1
        print("OBSERVATION AUDIT PASSED")
        return 0
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
