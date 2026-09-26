"""Generate or refresh the product routing profiles (kb_products.py).

The worker reconciles these every few minutes on its own; this is for doing it
now, or forcing a regeneration after changing the prompt:

    python scripts/kb_product_profiles.py            # only what changed
    python scripts/kb_product_profiles.py --force    # every product
    python scripts/kb_product_profiles.py --product travel --force
    python scripts/kb_product_profiles.py --show     # print what is stored
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from env_loader import load_env  # noqa: E402

load_env()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="Regenerate even if unchanged")
    parser.add_argument("--product", action="append", default=[], help="Limit to a product key")
    parser.add_argument("--show", action="store_true", help="Print stored profiles and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    import actor_context
    import kb_products

    actor_context.bind_service_actor("system")
    if args.show:
        for p in kb_products.list_products():
            print(f"\n== {p['productKey']} · {p['title']} · {p['status']} · {len(p['phrasings'])} phrasings")
            print(f"   {p['summary']}")
            for ph in p["phrasings"]:
                print(f"   - [{ph['origin']}] {ph['text']}")
        return 0
    results = kb_products.reconcile(force=args.force, product_keys=args.product or None)
    print(json.dumps(results, indent=2, default=str))
    return 1 if any(r["status"] != "ready" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
