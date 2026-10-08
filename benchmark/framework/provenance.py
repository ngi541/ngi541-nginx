from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from framework.ids import validate_slug, utc_rfc3339
from framework.io_utils import (
    FrameworkError,
    atomic_write_json,
    atomic_write_text,
)


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        raise FrameworkError(
            f"unable to execute {argv[0]!r}: {exc}"
        ) from exc


def _run_ok(
    argv: list[str],
    *,
    cwd: Path | None = None,
) -> str | None:
    result = _run(argv, cwd=cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _relative_location(path: Path, repo_root: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        pass

    parent = repo_root.resolve().parent
    try:
        relative = path.resolve().relative_to(parent)
        return f"../{relative}"
    except ValueError:
        return None


def resolve_recorded_location(
    location: str | None,
    repo_root: Path,
) -> Path:
    if location is None:
        raise FrameworkError(
            "artifact has no portable recorded location; "
            "local execution requires an artifact below the repository "
            "or its parent directory"
        )

    path = (repo_root / location).resolve()
    parent = repo_root.resolve().parent

    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise FrameworkError(
            f"recorded artifact escapes repository parent: {location}"
        ) from exc

    return path


def _git_diff_sha256(path: Path) -> str:
    chunks: list[bytes] = []

    for argv in (
        ["git", "diff", "--binary", "HEAD"],
        ["git", "diff", "--cached", "--binary", "HEAD"],
    ):
        result = subprocess.run(
            argv,
            cwd=path,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            chunks.append(result.stdout)

    return hashlib.sha256(b"\n".join(chunks)).hexdigest()


def git_source_info(
    name: str,
    path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    inside = _run_ok(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path,
    )
    if inside != "true":
        raise FrameworkError(f"source is not a Git work tree: {path}")

    commit = _run_ok(["git", "rev-parse", "HEAD"], cwd=path)
    if not commit:
        raise FrameworkError(f"unable to resolve Git commit for source: {path}")

    branch = _run_ok(
        ["git", "symbolic-ref", "--short", "-q", "HEAD"],
        cwd=path,
    )
    describe = _run_ok(
        ["git", "describe", "--always", "--dirty", "--tags"],
        cwd=path,
    )
    remote = _run_ok(
        ["git", "remote", "get-url", "origin"],
        cwd=path,
    )

    tracked_status = _run_ok(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=path,
    )
    untracked = _run_ok(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=path,
    )

    untracked_files = []
    if untracked:
        untracked_files = [
            line
            for line in untracked.splitlines()
            if not line.startswith("experiments/")
            and not line.startswith("evidence/candidates/")
            and "__pycache__/" not in line
            and not line.endswith(".pyc")
        ]

    tracked_dirty = bool(tracked_status)

    return {
        "name": name,
        "commit": commit,
        "branch": branch,
        "describe": describe,
        "remote": remote,
        "location": _relative_location(path, repo_root),
        # "dirty" means tracked source state differs from HEAD.
        # Untracked files are preserved separately because build/install
        # artifacts should not silently turn a clean source revision dirty.
        "dirty": tracked_dirty,
        "tracked_dirty": tracked_dirty,
        "untracked_present": bool(untracked_files),
        "untracked_relevant": untracked_files,
        "tracked_diff_sha256": _git_diff_sha256(path),
    }


def parse_named_path(spec: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise FrameworkError(
            f"expected NAME=PATH syntax, got: {spec!r}"
        )

    name, raw_path = spec.split("=", 1)
    validate_slug(name, "artifact name")

    path = Path(raw_path).expanduser()
    return name, path


def parse_named_command(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise FrameworkError(
            f"expected NAME=COMMAND syntax, got: {spec!r}"
        )

    name, command = spec.split("=", 1)
    validate_slug(name, "preflight name")

    if not command.strip():
        raise FrameworkError("preflight command must not be empty")

    return name, command


def discover_sources(
    repo_root: Path,
    explicit_sources: list[str],
) -> dict[str, Any]:
    sources: dict[str, Any] = {}

    sources["ngi541-nginx"] = git_source_info(
        "ngi541-nginx",
        repo_root,
        repo_root,
    )

    sibling = repo_root.parent / "ngi541"
    if sibling.is_dir():
        try:
            sources["ngi541"] = git_source_info(
                "ngi541",
                sibling,
                repo_root,
            )
        except FrameworkError:
            pass

    for spec in explicit_sources:
        name, path = parse_named_path(spec)
        sources[name] = git_source_info(
            name,
            path.resolve(),
            repo_root,
        )

    return {
        "schema_version": 1,
        "collected_at": utc_rfc3339(),
        "sources": sources,
    }


def _probe_version(
    candidates: list[list[str]],
) -> dict[str, Any]:
    for argv in candidates:
        executable = shutil.which(argv[0])

        if executable is None and Path(argv[0]).is_absolute():
            if Path(argv[0]).is_file():
                executable = argv[0]

        if executable is None:
            continue

        resolved = [executable, *argv[1:]]
        result = _run(resolved)

        output = (result.stdout or result.stderr).strip()
        first_line = output.splitlines()[0] if output else None

        return {
            "available": result.returncode == 0,
            "command": resolved,
            "version": first_line,
        }

    return {
        "available": False,
        "command": None,
        "version": None,
    }


def _parse_versions_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}

    result: dict[str, str] = {}

    for raw_line in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")

    return result


def discover_dependencies(repo_root: Path) -> dict[str, Any]:
    curl_candidates = []
    homebrew_curl = Path("/usr/local/opt/curl/bin/curl")
    if homebrew_curl.is_file():
        curl_candidates.append([str(homebrew_curl), "--version"])
    curl_candidates.append(["curl", "--version"])

    tools = {
        "python3": _probe_version([["python3", "--version"]]),
        "git": _probe_version([["git", "--version"]]),
        "curl": _probe_version(curl_candidates),
        "cmake": _probe_version([["cmake", "--version"]]),
        "clang": _probe_version([["clang", "--version"]]),
        "openssl": _probe_version([["openssl", "version"]]),
    }

    pinned = _parse_versions_env(
        repo_root / "integration" / "versions" / "versions.env"
    )

    return {
        "schema_version": 1,
        "collected_at": utc_rfc3339(),
        "tools": tools,
        "pinned_versions": pinned,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _artifact_record(
    name: str,
    path: Path,
    repo_root: Path,
) -> dict[str, Any]:
    requested = path.expanduser().absolute()
    resolved = requested.resolve()

    if not resolved.is_file():
        raise FrameworkError(f"artifact does not exist: {path}")

    # Preserve the user-visible leaf name even when PATH is a symlink.
    # Runtime loaders often depend on that exact SONAME/install-name alias
    # (for example libngi541_engine.0.1.dylib -> .0.1.1.dylib).
    #
    # Hashing still follows the symlink and fingerprints the target bytes.
    location = _relative_location(requested.parent, repo_root)
    if location is not None:
        location = str(Path(location) / requested.name)

    return {
        "name": name,
        "sha256": sha256_file(resolved),
        "location": location,
        "basename": requested.name,
        "resolved_basename": resolved.name,
        "size_bytes": resolved.stat().st_size,
    }


def record_binaries(
    repo_root: Path,
    binary_specs: list[str],
    output: Path,
) -> dict[str, Any]:
    rows = []
    lines = []

    for spec in binary_specs:
        name, path = parse_named_path(spec)
        record = _artifact_record(name, path, repo_root)
        rows.append(record)
        lines.append(
            f"{record['sha256']}  {name}:{record['basename']}"
        )

    atomic_write_text(
        output,
        "\n".join(lines) + ("\n" if lines else ""),
    )

    return {
        "schema_version": 1,
        "artifacts": rows,
    }


def record_runtime_bindings(
    repo_root: Path,
    variants: list[str],
    binary_records: dict[str, Any],
    library_specs: list[str],
) -> dict[str, Any]:
    binaries = {
        item["name"]: item
        for item in binary_records.get("artifacts", [])
    }

    result: dict[str, Any] = {
        "schema_version": 1,
        "variants": {},
    }

    for variant in variants:
        if variant not in binaries:
            raise FrameworkError(
                f"missing --binary binding for variant: {variant}"
            )

        if binaries[variant].get("location") is None:
            raise FrameworkError(
                f"variant binary {variant!r} is outside the portable "
                "repository-parent boundary"
            )

        result["variants"][variant] = {
            "binary": binaries[variant],
            "libraries": [],
        }

    for spec in library_specs:
        variant, path = parse_named_path(spec)

        if variant not in result["variants"]:
            raise FrameworkError(
                f"runtime library references unknown variant: {variant}"
            )

        record = _artifact_record(
            f"{variant}-library",
            path,
            repo_root,
        )
        if record.get("location") is None:
            raise FrameworkError(
                f"runtime library for {variant!r} is outside the portable "
                "repository-parent boundary"
            )

        result["variants"][variant]["libraries"].append(record)

    return result


def record_build(
    binary_records: dict[str, Any],
    runtime_bindings: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "collected_at": utc_rfc3339(),
        "build_performed_by_framework": False,
        "binary_artifacts": binary_records["artifacts"],
        "runtime_bindings": {
            variant: {
                "binary_sha256": binding["binary"]["sha256"],
                "library_sha256": [
                    library["sha256"]
                    for library in binding["libraries"]
                ],
            }
            for variant, binding in runtime_bindings["variants"].items()
        },
        "note": (
            "R5.4 executes only sealed runtime artifacts whose hashes "
            "match the preparation provenance."
        ),
    }


def run_preflight(
    experiment_dir: Path,
    repo_root: Path,
    custom_specs: list[str],
) -> dict[str, Any]:
    preflight_dir = experiment_dir / "provenance" / "preflight"
    preflight_dir.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = [
        {
            "name": "request-present",
            "kind": "builtin",
            "passed": (experiment_dir / "config" / "request.json").is_file(),
        },
        {
            "name": "resolved-present",
            "kind": "builtin",
            "passed": (experiment_dir / "config" / "resolved.json").is_file(),
        },
        {
            "name": "schedule-present",
            "kind": "builtin",
            "passed": (experiment_dir / "execution" / "schedule.json").is_file(),
        },
        {
            "name": "runtime-bindings-present",
            "kind": "builtin",
            "passed": (
                experiment_dir
                / "provenance"
                / "runtime-bindings.json"
            ).is_file(),
        },
        {
            "name": "workload-prepared",
            "kind": "builtin",
            "passed": (
                experiment_dir
                / "execution"
                / "workload"
                / "manifest.json"
            ).is_file(),
        },
    ]

    for spec in custom_specs:
        name, command = parse_named_command(spec)

        result = subprocess.run(
            command,
            cwd=repo_root,
            shell=True,
            text=True,
            capture_output=True,
        )

        stdout_path = preflight_dir / f"{name}.stdout.log"
        stderr_path = preflight_dir / f"{name}.stderr.log"
        atomic_write_text(stdout_path, result.stdout)
        atomic_write_text(stderr_path, result.stderr)

        checks.append(
            {
                "name": name,
                "kind": "command",
                "command": command,
                "exit_code": result.returncode,
                "passed": result.returncode == 0,
                "stdout": f"provenance/preflight/{stdout_path.name}",
                "stderr": f"provenance/preflight/{stderr_path.name}",
            }
        )

    passed = all(bool(check.get("passed")) for check in checks)

    return {
        "schema_version": 1,
        "collected_at": utc_rfc3339(),
        "passed": passed,
        "checks": checks,
    }
