from __future__ import annotations

from pathlib import Path
from typing import Any

from framework.io_utils import FrameworkError, read_json


def _source_component(
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": source.get("describe"),
        "commit": source.get("commit"),
        "source": source.get("remote"),
        "role": "source",
    }


def build_software_record(
    sources: dict[str, Any],
    dependencies: dict[str, Any],
) -> dict[str, Any]:
    software: dict[str, Any] = {}

    for name, source in sources.get("sources", {}).items():
        software[name] = _source_component(source)

    pinned = dependencies.get("pinned_versions", {})

    mapping = {
        "NGINX_VERSION": "nginx",
        "OPENSSL_VERSION": "openssl",
    }

    for key, component_name in mapping.items():
        if key in pinned and component_name not in software:
            software[component_name] = {
                "version": pinned[key],
                "commit": None,
                "source": None,
                "role": "dependency",
            }

    if not software:
        raise FrameworkError("unable to build non-empty software provenance")

    return software


def build_manifest(
    experiment_dir: Path,
) -> dict[str, Any]:
    experiment_id = experiment_dir.name

    state = read_json(experiment_dir / "state.json")
    request = read_json(experiment_dir / "config" / "request.json")
    adapter = read_json(experiment_dir / "environment" / "adapter.json")
    sources = read_json(experiment_dir / "provenance" / "sources.json")
    dependencies = read_json(
        experiment_dir / "provenance" / "dependencies.json"
    )

    framework_source = sources.get("sources", {}).get("ngi541-nginx")
    if not framework_source:
        raise FrameworkError(
            "framework source provenance is missing ngi541-nginx"
        )

    nodes = {}
    for node_name, node in adapter["nodes"].items():
        nodes[node_name] = {
            "roles": list(node["roles"]),
            "inventory_path": f"environment/nodes/{node_name}",
            "address": None,
        }

    return {
        "schema_version": 1,
        "experiment": {
            "id": experiment_id,
            "alias": request.get("alias"),
            "workload": request["workload"],
            "environment": request["environment"],
            "created_at": state["created_at"],
        },
        "framework": {
            "repository": "ngi541-nginx",
            "commit": framework_source["commit"],
        },
        "software": build_software_record(
            sources,
            dependencies,
        ),
        "topology": {
            "class": adapter["topology_class"],
            "nodes": nodes,
        },
        "config": {
            "request": "config/request.json",
            "resolved": "config/resolved.json",
        },
        "environment": {
            "adapter": "environment/adapter.json",
            "nodes_root": "environment/nodes",
        },
        "provenance": {
            "sources": "provenance/sources.json",
            "dependencies": "provenance/dependencies.json",
            "build": "provenance/build.json",
            "binaries": "provenance/binaries.sha256",
            "preflight": "provenance/preflight.json",
        },
        "execution": {
            "schedule": "execution/schedule.json",
        },
        "extensions": {
            "source_dirty": {
                name: bool(record.get("dirty"))
                for name, record in sources.get("sources", {}).items()
            }
        },
    }
