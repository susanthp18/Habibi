"""Record what Voice Studio is serving, before a deploy or a routing change.

Writes one JSON file: every agent's live (published) version with its full
definition, and every channel binding (inbound numbers, outbound objectives,
WhatsApp). Read-only; prints the file path, never a secret.

    docker exec collections_api python -m scripts.voice_studio_snapshot --out /app/.cache/vs-snapshots

Restoring from it (docs: deploy/cloudunity/README.md, "Voice Studio rollback"):
  * an agent: Voice Studio > agent > version history > "Roll back to vN" with the
    snapshot's version number (the engine keeps every version);
  * routing: Voice Studio > Agent routing, re-assign each channel to the
    snapshot's agent (validated and audited like any change).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from env_loader import load_env


def snapshot() -> dict[str, Any]:
    import db
    import voice_studio
    import voice_studio_routing

    routing = voice_studio_routing.list_routing()
    agents = []
    for agent in routing["agents"]:
        versions = voice_studio.engine_call("GET", f"/workflow/{agent['id']}/versions") or []
        live = next((v for v in versions if v.get("status") == "published"), None)
        agents.append({
            "id": agent["id"],
            "name": agent["name"],
            "liveVersion": live.get("version_number") if live else None,
            "liveVersionId": live.get("id") if live else None,
            "publishedAt": live.get("published_at") if live else None,
            # Keys are masked by the engine; the definition is for review and diffing.
            "definition": live.get("workflow_json") if live else None,
        })
    return {
        "takenAt": datetime.now(timezone.utc).isoformat(),
        "tenant": db.current_tenant(),
        "agents": agents,
        "routing": {"inbound": routing["numbers"], "bindings": routing["bindings"]},
    }


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="/app/.cache/vs-snapshots", help="directory for the JSON file")
    args = parser.parse_args()
    data = snapshot()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"voice-studio-{data['takenAt'][:19].replace(':', '')}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    live = ", ".join(f"{a['name']} v{a['liveVersion']}" for a in data["agents"])
    print(f"snapshot: {path} ({live}; {len(data['routing']['inbound'])} numbers, "
          f"{len(data['routing']['bindings'])} bindings)")


if __name__ == "__main__":
    main()
