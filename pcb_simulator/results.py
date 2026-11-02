"""Package solver fields into a portable, offline 3D result viewer.

The solver's element fields remain in fields.npz. The surface export explicitly
contains volume-weighted vertex projections of current density and Joule heat.
"""
from __future__ import annotations

import base64
import csv
import json
from pathlib import Path
from typing import Callable

import numpy as np


def _json(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (np.ndarray, Path)):
        return value.tolist() if isinstance(value, np.ndarray) else str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _encode(array, dtype):
    return base64.b64encode(np.asarray(array, dtype=dtype).tobytes()).decode("ascii")


def _project_elements(nodes, tetrahedra, values):
    """Return the volume-weighted element average at each connected vertex."""
    weights = np.zeros(len(nodes), dtype=np.float64)
    result = {name: np.zeros(len(nodes), dtype=np.float64) for name in values}
    # Keep determinant inputs and four-vertex repeated weights bounded even for
    # million-element jobs; do not materialize M x 3 x 3 edges for the full mesh.
    for start in range(0, len(tetrahedra), 100_000):
        stop = start + 100_000
        block = tetrahedra[start:stop]
        edges = nodes[block[:, 1:]] - nodes[block[:, 0], None, :]
        volumes = np.abs(np.linalg.det(edges)) / 6.0
        if not np.all(np.isfinite(volumes)) or np.any(volumes <= 0):
            raise ValueError("Mesh contains a degenerate or non-finite tetrahedron")
        index = block.ravel()
        weights += np.bincount(index, weights=np.repeat(volumes, 4), minlength=len(nodes))
        for name, field in values.items():
            result[name] += np.bincount(index, weights=np.repeat(volumes * field[start:stop], 4), minlength=len(nodes))
    for weighted in result.values():
        # Unused nodes have no element field; they are rejected if on the surface.
        np.divide(weighted, weights, out=weighted, where=weights > 0)
    return result, weights


def _surface_groups(nodes, triangles):
    """Identify flat Z surfaces from geometry, leaving connecting walls together."""
    triangle_z = nodes[triangles, 2]
    tolerance = max(float(np.ptp(nodes[:, 2])) * 1e-7, 1e-8)
    horizontal = np.ptp(triangle_z, axis=1) <= tolerance
    levels = triangle_z[horizontal].mean(axis=1)
    if not len(levels):
        return [("Copper surface", triangles)]
    sorted_levels = np.sort(levels)
    boundaries = np.r_[True, np.diff(sorted_levels) > tolerance]
    representatives = sorted_levels[boundaries]
    # Complicated stepped geometry can have many planes. Limit the menu without
    # discarding triangles or pretending that arbitrary planes are copper layers.
    if len(representatives) > 48:
        return [("Horizontal copper surfaces", triangles[horizontal]),
                ("Connecting walls / via surfaces", triangles[~horizontal])]
    assignment = np.searchsorted(representatives, levels + tolerance / 2, side="right") - 1
    flat_indices = np.flatnonzero(horizontal)
    groups = []
    for i in reversed(range(len(representatives))):
        selected = triangles[flat_indices[assignment == i]]
        if len(selected):
            groups.append((f"Copper surface at Z = {representatives[i]:.6g} mm", selected))
    if np.any(~horizontal):
        groups.append(("Connecting walls / via surfaces", triangles[~horizontal]))
    return groups


def _load_ports(output_dir, report):
    given = report.get("ports_file")
    candidates = []
    if given:
        candidate = Path(given)
        candidates.append(candidate if candidate.is_absolute() else output_dir / candidate)
    candidates.extend(sorted(output_dir.rglob("ports.json"), key=lambda p: p.stat().st_mtime, reverse=True))
    for path in candidates:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("ports", []) if isinstance(data, dict) else data
    return []


def build_results(output_dir: Path, report: dict, emit: Callable, *, viewer_only: bool = False) -> dict:
    """Create viewer.html, summary.json, surface_fields.npz and pad_currents.csv.

    Input fields.npz contains nodes_mm, tetrahedra, external_triangles, voltage_V,
    ir_drop_mV, and the element arrays current_density_A_mm2 and joule_W_mm3.
    Temperature is included only when thermal_solved is explicitly true.
    viewer_only refreshes the HTML from existing fields without rewriting exports.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    emit("results", "Preparing surface fields and offline 3D viewer")
    with np.load(output_dir / "fields.npz", allow_pickle=False) as archive:
        nodes = np.asarray(archive["nodes_mm"], dtype=np.float64)
        tet = np.asarray(archive["tetrahedra"], dtype=np.int64)
        triangles = np.asarray(archive["external_triangles"], dtype=np.int64)
        if nodes.ndim != 2 or nodes.shape[1] != 3 or not len(nodes) or not np.all(np.isfinite(nodes)):
            raise ValueError("nodes_mm must contain finite N x 3 coordinates")
        for name, array, width in (("tetrahedra", tet, 4), ("external_triangles", triangles, 3)):
            if array.ndim != 2 or array.shape[1] != width or not len(array) or array.min() < 0 or array.max() >= len(nodes):
                raise ValueError(f"{name} has invalid node indices or shape")
        values = {}
        for name in ("voltage_V", "ir_drop_mV"):
            values[name] = np.asarray(archive[name], dtype=np.float64)
        thermal = report.get("thermal_solved") is True
        if thermal:
            values["temperature_C"] = np.asarray(archive["temperature_C"], dtype=np.float64)
        for name, field in values.items():
            if field.shape != (len(nodes),) or not np.all(np.isfinite(field)):
                raise ValueError(f"{name} must contain one finite value per node")
        elements = {}
        for name in ("current_density_A_mm2", "joule_W_mm3"):
            elements[name] = np.asarray(archive[name], dtype=np.float64)
            if elements[name].shape != (len(tet),) or not np.all(np.isfinite(elements[name])):
                raise ValueError(f"{name} must contain one finite value per tetrahedron")
        projected, weights = _project_elements(nodes, tet, elements)
        if np.any(weights[np.unique(triangles)] <= 0):
            raise ValueError("Surface contains nodes unconnected to volume elements")
        values.update(projected)
        node_tags = np.asarray(archive["node_tags"]) if "node_tags" in archive else np.arange(len(nodes))

    surface_path = output_dir / "surface_fields.npz"
    if not viewer_only:
        np.savez_compressed(surface_path, nodes_mm=nodes, node_tags=node_tags, triangles=triangles, **values)
    center = (nodes.min(axis=0) + nodes.max(axis=0)) / 2
    bodies = []
    for name, faces in _surface_groups(nodes, triangles):
        if not len(faces):
            continue
        used = np.unique(faces)
        points = nodes[used]
        bodies.append(dict(id=len(bodies) + 1, name=name,
                           bounds_mm=np.r_[points.min(axis=0), points.max(axis=0)].tolist(),
                           xyz=_encode(points - center, "<f4"),
                           faces=_encode(np.searchsorted(used, faces), "<u4"),
                           fields={key: _encode(value[used], "<f4") for key, value in values.items()}))

    low_voltage, high_voltage = sorted((float(report["input_voltage_V"]), float(report["output_voltage_V"])))
    drop = float(report["terminal_drop_V"]) * 1000
    ranges = {"voltage_V": [low_voltage, high_voltage], "ir_drop_mV": sorted((0, drop))}
    for name in projected:
        ranges[name] = [0, float(projected[name][np.unique(triangles)].max())]
    if thermal:
        ranges["temperature_C"] = [float(report["room_temperature_C"]), float(report["limit_temperature_C"])]
    for key, bounds in ranges.items():
        if not np.all(np.isfinite(bounds)):
            raise ValueError(f"Non-finite recommended scale for {key}")
        if bounds[1] <= bounds[0]:
            bounds[1] = bounds[0] + max(abs(bounds[0]) * 1e-6, 1e-9)

    ports = []
    for port in _load_ports(output_dir, report):
        position = port.get("centroid_mm")
        if position is not None and len(position) == 3:
            ports.append(dict(name=str(port.get("name", "Port")), role=port.get("role", "output"),
                              position=[float(v) for v in position]))
    notes = ["Geometry and slice positions use millimetres from the mesh.",
             "Voltage and temperature are original nodal FEM values. Current density and Joule generation are volume-weighted vertex projections of element values; corner peaks depend on the mesh.",
             "Horizontal Z surfaces are detected from geometry. Connecting walls include via surfaces and copper edges; surface groups do not establish electrical connectivity."]
    notes.append("Temperature is an approximate model prediction; review the cooling and material assumptions below."
                 if thermal else "Electrical-only solve: temperature was not calculated.")
    assumptions = report.get("assumptions", [])
    if isinstance(assumptions, dict):
        notes.extend(f"{key}: {value}" for key, value in assumptions.items())
    elif isinstance(assumptions, list):
        notes.extend(str(value) for value in assumptions)
    elif assumptions:
        notes.append(str(assumptions))
    payload = dict(center=center.tolist(), bounds_mm=np.r_[nodes.min(axis=0), nodes.max(axis=0)].tolist(),
                   bodies=bodies, report=report, ports=ports, field_names=list(values), ranges=ranges, notes=notes)
    template = (Path(__file__).parent / "viewer" / "viewer.template.html").read_text(encoding="utf-8")
    serialized = json.dumps(payload, separators=(",", ":"), default=_json, allow_nan=False).replace("<", "\\u003c")
    pending_viewer = output_dir / "viewer.pending.html"
    pending_viewer.write_text(template.replace("__BOARD_GEOMETRY__", serialized), encoding="utf-8")
    pending_viewer.replace(output_dir / "viewer.html")
    summary = dict(report=report, surface_groups=[dict(id=b["id"], name=b["name"]) for b in bodies],
                   recommended_ranges=ranges, field_interpretation=notes,
                   files=["viewer.html", "summary.json", "surface_fields.npz", "pad_currents.csv", "fields.npz", "report.json"])
    if not viewer_only:
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=_json, allow_nan=False), encoding="utf-8")
        pads = report.get("per_pad", [])
        columns = list(dict.fromkeys(["name", "role", "current_A", "mean_voltage_V"] + [key for pad in pads for key in pad]))
        with (output_dir / "pad_currents.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(pads)
    emit("results", "Offline 3D viewer and result downloads ready", files=summary["files"])
    return summary
