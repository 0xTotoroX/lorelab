"""Rebuild the reviewed endpoint registry from a downloaded public TikHub OpenAPI file."""

import argparse
from pathlib import Path

from soota.providers.tikhub.registry import REGISTRY_PATH, write_registry

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--spec", type=Path, required=True)
parser.add_argument("--as-of", required=True, help="Verification date, YYYY-MM-DD")
parser.add_argument("--output", type=Path, default=REGISTRY_PATH)
args = parser.parse_args()
registry = write_registry(args.spec, args.output, args.as_of)
print(f"{len(registry.endpoints)} documented endpoints; {len(registry.preferred())} preferred operations")
