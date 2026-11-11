"""Refresh successful saved runs from existing FEM fields, without solving.

python -m pcb_simulator.viewer.refresh_viewers [--runs-dir PATH]
Only viewer.html is replaced. Numeric exports, reports, meshes and run metadata
are retained byte-for-byte. No engine or CAD package is imported.
"""
import argparse
import json
from pathlib import Path

from pcb_simulator.results import build_results


def refresh(runs_dir: Path) -> list[str]:
    refreshed = []
    for metadata_path in sorted(Path(runs_dir).glob("*/meta.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        output_dir = metadata_path.parent
        if metadata.get("status") != "succeeded":
            continue
        if not (output_dir / "fields.npz").is_file() or not (output_dir / "report.json").is_file():
            continue
        report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
        build_results(output_dir, report, lambda stage, message, **_: print(f"{output_dir.name}: {message}"),
                      viewer_only=True)
        refreshed.append(str(output_dir / "viewer.html"))
    return refreshed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "runs")
    args = parser.parse_args()
    print(json.dumps(dict(refreshed=refresh(args.runs_dir)), indent=2))


if __name__ == "__main__":
    main()
