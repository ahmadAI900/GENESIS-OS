"""Merge per-run recorder output into the single evidence file.

Each recorder run writes its own file under ``docs/fast_gate_runs/``
tagged by what it was: a control run, the live tier, the fast tier.
They are merged here into ``docs/fast_gate_evidence.json`` so the tiering
script has one input, with the merge arithmetic reported rather than
assumed.

Merging is by union of distinct events with counts summed, and by MAX
duration. MAX rather than SUM because a test that appears in two runs was
observed twice; the question the duration answers is "how long is this
test when it runs", and the slowest observation is the conservative one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
IDENTITY_FIELDS = ("api", "exe", "path", "host", "symbol", "dll")


def key(event):
    return (event.get("kind", ""),) + tuple(
        event.get(f, "") for f in IDENTITY_FIELDS)


def merge_events(a, b):
    out = [dict(e) for e in a]
    index = {key(e): e for e in out}
    for event in b:
        k = key(event)
        if k in index:
            index[k]["count"] = index[k].get("count", 1) + event.get("count", 1)
        else:
            copied = dict(event)
            out.append(copied)
            index[k] = copied
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="*", default=None,
                        help="run files under docs/fast_gate_runs/")
    parser.add_argument("--out", default=str(BACKEND / "docs" /
                                             "fast_gate_evidence.json"))
    args = parser.parse_args(argv)

    run_dir = BACKEND / "docs" / "fast_gate_runs"
    paths = ([Path(p) for p in args.runs] if args.runs
             else sorted(run_dir.glob("*.json")))

    merged = {}
    provenance = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for nodeid, record in data.items():
            if nodeid.startswith("__"):
                continue
            if nodeid in merged:
                merged[nodeid]["events"] = merge_events(
                    merged[nodeid]["events"], record["events"])
                merged[nodeid]["seconds"] = max(
                    merged[nodeid]["seconds"], record["seconds"])
                merged[nodeid]["dropped"] = (merged[nodeid].get("dropped", 0)
                                             + record.get("dropped", 0))
                provenance[nodeid].append(path.stem)
            else:
                merged[nodeid] = {
                    "events": [dict(e) for e in record["events"]],
                    "seconds": record["seconds"],
                    "dropped": record.get("dropped", 0),
                }
                provenance[nodeid] = [path.stem]

    payload = {
        "__meta__": {
            "sources": [p.stem for p in paths],
            "tests": len(merged),
            "truncated_tests": sorted(n for n, r in merged.items()
                                      if r.get("dropped")),
        },
        **merged,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True),
                   encoding="utf-8")

    both = sum(1 for v in provenance.values() if len(v) > 1)
    print(f"merged {len(paths)} run files -> {out}")
    print(f"tests: {len(merged)} (seen in more than one run: {both})")
    print(f"truncated: {len(payload['__meta__']['truncated_tests'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())