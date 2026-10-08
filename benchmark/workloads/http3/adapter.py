from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from framework.ids import utc_rfc3339
from framework.io_utils import (
    FrameworkError,
    append_log,
    atomic_write_json,
    atomic_write_text,
    read_json,
)
from framework.lifecycle import (
    load_state,
    transition,
    update_run_counts,
)
from framework.provenance import (
    resolve_recorded_location,
    sha256_file,
)


DEFAULTS = {
    "requests_per_client": 5000,
    "warmup_requests_per_client": 50,
    "cipher_suite": "TLS_AES_128_GCM_SHA256",
    "server_host": "127.0.0.1",
    "server_port": 8443,
    "worker_connections": 4096,
    "keepalive_requests": 20000,
    "startup_timeout_seconds": 10,
    "client_timeout_seconds": 60,
}


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise FrameworkError(f"{name} must be a positive integer")
    return value


def _validate_int_axis(value: Any, name: str) -> None:
    if isinstance(value, list):
        if not value:
            raise FrameworkError(f"{name} must not be an empty list")
        for item in value:
            _positive_int(item, name)
    else:
        _positive_int(value, name)


def resolve_http3_config(
    request: dict[str, Any],
    resolved: dict[str, Any],
) -> dict[str, Any]:
    parameters = dict(resolved["parameters"])

    required_axes = {
        "payload_bytes": [16384],
        "workers": [1],
        "clients": [1],
    }

    for name, default in required_axes.items():
        parameters.setdefault(name, default)
        _validate_int_axis(parameters[name], name)

    for name, value in DEFAULTS.items():
        parameters.setdefault(name, value)

    for name in (
        "requests_per_client",
        "warmup_requests_per_client",
        "server_port",
        "worker_connections",
        "keepalive_requests",
        "startup_timeout_seconds",
        "client_timeout_seconds",
    ):
        _positive_int(parameters[name], name)

    cipher = parameters["cipher_suite"]
    if not isinstance(cipher, str) or not cipher:
        raise FrameworkError("cipher_suite must be a non-empty string")

    host = parameters["server_host"]
    if not isinstance(host, str) or not host:
        raise FrameworkError("server_host must be a non-empty string")

    resolved = dict(resolved)
    resolved["parameters"] = parameters
    resolved["workload_contract"] = {
        "adapter": "http3",
        "version": 1,
        "primary_metric": "requests_per_second",
        "transport": "QUIC",
        "application_protocol": "HTTP/3",
    }
    return resolved


def _tool_path(
    dependencies: dict[str, Any],
    name: str,
) -> str:
    record = dependencies.get("tools", {}).get(name, {})
    command = record.get("command")

    if not record.get("available") or not command:
        raise FrameworkError(f"required tool is unavailable: {name}")

    return command[0]


def _write_payload(path: Path, size: int) -> str:
    expected = hashlib.sha256(b"\x00" * size).hexdigest()

    if path.exists():
        if path.stat().st_size != size:
            raise FrameworkError(
                f"existing HTTP/3 payload has wrong size: {path}"
            )
        current = sha256_file(path)
        if current != expected:
            raise FrameworkError(
                f"existing HTTP/3 payload has wrong content: {path}"
            )
        return expected

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return expected


def _axis_values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _runtime_env_for_binding(
    binding: dict[str, Any],
    repo_root: Path,
) -> dict[str, str]:
    env = dict(os.environ)
    library_dirs = []

    for library in binding.get("libraries", []):
        path = resolve_recorded_location(
            library.get("location"),
            repo_root,
        )
        library_dirs.append(str(path.parent))

    if library_dirs:
        joined = os.pathsep.join(dict.fromkeys(library_dirs))
        for key in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
            previous = env.get(key)
            env[key] = joined if not previous else joined + os.pathsep + previous

    return env


def _check_nginx_variant(
    variant: str,
    binding: dict[str, Any],
    repo_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    binary = resolve_recorded_location(
        binding["binary"].get("location"),
        repo_root,
    )

    if sha256_file(binary) != binding["binary"]["sha256"]:
        raise FrameworkError(
            f"sealed binary hash mismatch during HTTP/3 preparation: {variant}"
        )

    env = _runtime_env_for_binding(binding, repo_root)
    result = subprocess.run(
        [str(binary), "-V"],
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    stdout_path = output_dir / f"{variant}-nginx-V.stdout.log"
    stderr_path = output_dir / f"{variant}-nginx-V.stderr.log"
    atomic_write_text(stdout_path, result.stdout)
    atomic_write_text(stderr_path, result.stderr)

    combined = result.stdout + "\n" + result.stderr
    http3 = "--with-http_v3_module" in combined

    return {
        "name": f"{variant}-nginx-http3",
        "passed": result.returncode == 0 and http3,
        "exit_code": result.returncode,
        "http3_module": http3,
        "stdout": (
            f"execution/workload/preflight/{stdout_path.name}"
        ),
        "stderr": (
            f"execution/workload/preflight/{stderr_path.name}"
        ),
    }


def prepare_http3_workload(
    experiment_dir: Path,
    resolved: dict[str, Any],
    dependencies: dict[str, Any],
    runtime_bindings: dict[str, Any],
) -> dict[str, Any]:
    workload_dir = experiment_dir / "execution" / "workload"
    assets_dir = workload_dir / "assets"
    preflight_dir = workload_dir / "preflight"
    assets_dir.mkdir(parents=True, exist_ok=True)
    preflight_dir.mkdir(parents=True, exist_ok=True)

    parameters = resolved["parameters"]
    payload_sizes = sorted(
        {
            int(value)
            for value in _axis_values(parameters["payload_bytes"])
        }
    )

    payload_records = []
    for size in payload_sizes:
        payload_path = assets_dir / f"{size}.bin"
        digest = _write_payload(payload_path, size)
        payload_records.append(
            {
                "bytes": size,
                "path": f"execution/workload/assets/{size}.bin",
                "sha256": digest,
            }
        )

    curl = _tool_path(dependencies, "curl")
    openssl = _tool_path(dependencies, "openssl")

    curl_help = subprocess.run(
        [curl, "--help", "all"],
        check=False,
        text=True,
        capture_output=True,
    )
    curl_help_text = curl_help.stdout + "\n" + curl_help.stderr

    checks = [
        {
            "name": "curl-http3-only",
            "passed": (
                curl_help.returncode == 0
                and "--http3-only" in curl_help_text
            ),
        },
        {
            "name": "curl-tls13-ciphers",
            "passed": (
                curl_help.returncode == 0
                and "--tls13-ciphers" in curl_help_text
            ),
        },
        {
            "name": "curl-out-null",
            "passed": (
                curl_help.returncode == 0
                and "--out-null" in curl_help_text
            ),
        },
        {
            "name": "openssl-available",
            "passed": bool(openssl),
        },
    ]

    repo_root = experiment_dir.parents[1]
    bindings = runtime_bindings["variants"]

    for variant in resolved["variants"]:
        binding = bindings.get(variant)
        if binding is None:
            raise FrameworkError(
                f"HTTP/3 runtime binding is missing variant: {variant}"
            )

        checks.append(
            _check_nginx_variant(
                variant,
                binding,
                repo_root,
                preflight_dir,
            )
        )

    preflight = {
        "schema_version": 1,
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks),
    }
    atomic_write_json(
        workload_dir / "preflight.json",
        preflight,
    )

    manifest = {
        "schema_version": 1,
        "adapter": "http3",
        "transport": "QUIC",
        "application_protocol": "HTTP/3",
        "cipher_suite": parameters["cipher_suite"],
        "server": {
            "host": parameters["server_host"],
            "port": parameters["server_port"],
        },
        "payloads": payload_records,
        "client": {
            "curl": curl,
            "requests_per_client": parameters["requests_per_client"],
            "warmup_requests_per_client": (
                parameters["warmup_requests_per_client"]
            ),
        },
        "preflight": "execution/workload/preflight.json",
    }
    atomic_write_json(
        workload_dir / "manifest.json",
        manifest,
    )

    if not preflight["passed"]:
        failed = [
            check["name"]
            for check in checks
            if not check["passed"]
        ]
        raise FrameworkError(
            "HTTP/3 workload preflight failed: "
            + ", ".join(failed)
        )

    return manifest


def _nginx_config(
    *,
    workers: int,
    host: str,
    port: int,
    worker_connections: int,
    keepalive_requests: int,
) -> str:
    reuseport = " reuseport" if workers > 1 else ""

    return f"""worker_processes {workers};
pid logs/nginx.pid;

events {{
    worker_connections {worker_connections};
}}

http {{
    access_log off;
    keepalive_requests {keepalive_requests};

    server {{
        listen {host}:{port} quic{reuseport};

        ssl_protocols TLSv1.3;
        ssl_certificate conf/server.crt;
        ssl_certificate_key conf/server.key;

        http3 on;

        root html;
    }}
}}
"""


def _verify_and_copy(
    record: dict[str, Any],
    repo_root: Path,
    destination: Path,
) -> None:
    source = resolve_recorded_location(
        record.get("location"),
        repo_root,
    )

    expected = record["sha256"]
    actual = sha256_file(source)
    if actual != expected:
        raise FrameworkError(
            f"sealed artifact hash mismatch: {record['name']}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)

    copied = sha256_file(destination)
    if copied != expected:
        raise FrameworkError(
            f"runtime copy hash mismatch: {record['name']}"
        )


def _materialize_runtime(
    experiment_dir: Path,
    run_id: str,
    attempt_number: int,
    variant: str,
    binding: dict[str, Any],
    parameters: dict[str, Any],
    workload_manifest: dict[str, Any],
    dependencies: dict[str, Any],
) -> tuple[Path, Path, dict[str, str]]:
    repo_root = experiment_dir.parents[1]

    runtime = (
        experiment_dir
        / "execution"
        / "runtime"
        / run_id
        / f"attempt-{attempt_number:02d}"
    )
    if runtime.exists():
        shutil.rmtree(runtime)

    for rel in ("bin", "lib", "conf", "html", "logs"):
        (runtime / rel).mkdir(parents=True, exist_ok=True)

    nginx_path = runtime / "bin" / "nginx"
    _verify_and_copy(
        binding["binary"],
        repo_root,
        nginx_path,
    )
    nginx_path.chmod(
        nginx_path.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    for library in binding.get("libraries", []):
        _verify_and_copy(
            library,
            repo_root,
            runtime / "lib" / library["basename"],
        )

    for payload in workload_manifest["payloads"]:
        source = experiment_dir / payload["path"]
        if sha256_file(source) != payload["sha256"]:
            raise FrameworkError(
                f"sealed payload hash mismatch: {payload['path']}"
            )
        shutil.copy2(
            source,
            runtime / "html" / Path(payload["path"]).name,
        )

    config = _nginx_config(
        workers=int(parameters["workers"]),
        host=str(parameters["server_host"]),
        port=int(parameters["server_port"]),
        worker_connections=int(parameters["worker_connections"]),
        keepalive_requests=int(parameters["keepalive_requests"]),
    )
    atomic_write_text(runtime / "conf" / "nginx.conf", config)

    openssl = _tool_path(dependencies, "openssl")
    cert = runtime / "conf" / "server.crt"
    key = runtime / "conf" / "server.key"

    cert_result = subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-days",
            "1",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if cert_result.returncode != 0:
        raise FrameworkError(
            "unable to generate ephemeral HTTP/3 TLS certificate: "
            + cert_result.stderr.strip()
        )

    env = dict(os.environ)
    runtime_lib = str(runtime / "lib")

    for key_name in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        previous = env.get(key_name)
        env[key_name] = (
            runtime_lib
            if not previous
            else runtime_lib + os.pathsep + previous
        )

    return runtime, nginx_path, env


def _curl_command(
    *,
    curl: str,
    host: str,
    port: int,
    payload_bytes: int,
    count: int,
    client_index: int,
    cipher_suite: str,
    timeout_seconds: int,
) -> list[str]:
    url = (
        f"https://{host}:{port}/{payload_bytes}.bin"
        f"?client={client_index}&i=[1-{count}]"
    )

    return [
        curl,
        "--http3-only",
        "--tls13-ciphers",
        cipher_suite,
        "--insecure",
        "--silent",
        "--show-error",
        "--fail",
        "--fail-early",
        "--out-null",
        "--connect-timeout",
        str(timeout_seconds),
        "--max-time",
        str(timeout_seconds),
        url,
    ]


def _run_clients(
    *,
    curl: str,
    host: str,
    port: int,
    payload_bytes: int,
    count_per_client: int,
    clients: int,
    cipher_suite: str,
    timeout_seconds: int,
    output_dir: Path,
    phase: str,
) -> tuple[bool, int, str | None]:
    phase_dir = output_dir / phase
    phase_dir.mkdir(parents=True, exist_ok=True)

    processes = []

    for client_index in range(1, clients + 1):
        stdout_path = phase_dir / f"client-{client_index:03d}.stdout.log"
        stderr_path = phase_dir / f"client-{client_index:03d}.stderr.log"

        stdout_handle = stdout_path.open("wb")
        stderr_handle = stderr_path.open("wb")

        command = _curl_command(
            curl=curl,
            host=host,
            port=port,
            payload_bytes=payload_bytes,
            count=count_per_client,
            client_index=client_index,
            cipher_suite=cipher_suite,
            timeout_seconds=timeout_seconds,
        )

        process = subprocess.Popen(
            command,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
        processes.append(
            (
                client_index,
                process,
                stdout_handle,
                stderr_handle,
                stdout_path,
                stderr_path,
            )
        )

    failure = None
    exit_code = 0

    for (
        client_index,
        process,
        stdout_handle,
        stderr_handle,
        stdout_path,
        stderr_path,
    ) in processes:
        rc = process.wait()
        stdout_handle.close()
        stderr_handle.close()

        stderr_nonempty = stderr_path.stat().st_size > 0

        if rc != 0 and failure is None:
            exit_code = rc
            failure = (
                f"{phase} curl client {client_index} failed "
                f"with exit code {rc}"
            )
        elif stderr_nonempty and failure is None:
            exit_code = 1
            failure = (
                f"{phase} curl client {client_index} produced stderr"
            )

    return failure is None, exit_code, failure


def _probe_server(
    *,
    curl: str,
    host: str,
    port: int,
    payload_bytes: int,
    cipher_suite: str,
    timeout_seconds: int,
    server_process: subprocess.Popen[Any],
    output_dir: Path,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    probe_dir = output_dir / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    last_error = "server probe did not run"

    while time.monotonic() < deadline:
        if server_process.poll() is not None:
            raise FrameworkError(
                f"NGINX exited during startup with code "
                f"{server_process.returncode}"
            )

        command = _curl_command(
            curl=curl,
            host=host,
            port=port,
            payload_bytes=payload_bytes,
            count=1,
            client_index=0,
            cipher_suite=cipher_suite,
            timeout_seconds=2,
        )
        result = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
        )

        atomic_write_text(
            probe_dir / "stdout.log",
            result.stdout,
        )
        atomic_write_text(
            probe_dir / "stderr.log",
            result.stderr,
        )

        if result.returncode == 0:
            return

        last_error = result.stderr.strip() or f"curl exit {result.returncode}"
        time.sleep(0.2)

    raise FrameworkError(
        f"HTTP/3 server did not become ready: {last_error}"
    )


def _stop_server(
    process: subprocess.Popen[Any],
) -> None:
    if process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait(timeout=5)


def _allocate_attempt(
    experiment_dir: Path,
    run_id: str,
) -> tuple[Path, int]:
    run_dir = experiment_dir / "raw" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    numbers = []
    for child in run_dir.iterdir():
        if child.is_dir() and child.name.startswith("attempt-"):
            try:
                numbers.append(int(child.name.split("-", 1)[1]))
            except (ValueError, IndexError):
                pass

    number = max(numbers, default=0) + 1
    attempt_dir = run_dir / f"attempt-{number:02d}"
    attempt_dir.mkdir()
    return attempt_dir, number


def _latest_valid_attempt(
    experiment_dir: Path,
    run_id: str,
) -> bool:
    run_dir = experiment_dir / "raw" / "runs" / run_id
    if not run_dir.is_dir():
        return False

    for measurement_path in sorted(
        run_dir.glob("attempt-*/measurement.json"),
        reverse=True,
    ):
        try:
            measurement = read_json(measurement_path)
        except FrameworkError:
            continue

        if measurement.get("execution", {}).get("valid") is True:
            return True

    return False


def _aggregate_client_logs(
    attempt_dir: Path,
    phase: str,
) -> None:
    source_dir = attempt_dir / phase

    stdout_parts = []
    stderr_parts = []

    for path in sorted(source_dir.glob("client-*.stdout.log")):
        data = path.read_text(encoding="utf-8", errors="replace")
        if data:
            stdout_parts.append(f"===== {path.name} =====\n{data}")

    for path in sorted(source_dir.glob("client-*.stderr.log")):
        data = path.read_text(encoding="utf-8", errors="replace")
        if data:
            stderr_parts.append(f"===== {path.name} =====\n{data}")

    atomic_write_text(
        attempt_dir / "stdout.log",
        "\n".join(stdout_parts),
    )
    atomic_write_text(
        attempt_dir / "stderr.log",
        "\n".join(stderr_parts),
    )


def _execute_run(
    experiment_dir: Path,
    run: dict[str, Any],
) -> dict[str, Any]:
    repo_root = experiment_dir.parents[1]
    dependencies = read_json(
        experiment_dir / "provenance" / "dependencies.json"
    )
    bindings = read_json(
        experiment_dir / "provenance" / "runtime-bindings.json"
    )
    workload_manifest = read_json(
        experiment_dir / "execution" / "workload" / "manifest.json"
    )
    resolved = read_json(
        experiment_dir / "config" / "resolved.json"
    )

    parameters = dict(resolved["parameters"])
    parameters.update(run["parameters"])

    variant = run["variant"]
    binding = bindings["variants"][variant]
    attempt_dir, attempt_number = _allocate_attempt(
        experiment_dir,
        run["run_id"],
    )

    attempt_started_at = utc_rfc3339()
    server = None
    server_stdout_handle = None
    server_stderr_handle = None

    measurement: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": experiment_dir.name,
        "run_id": run["run_id"],
        "pair_id": run.get("pair_id"),
        "attempt": attempt_number,
        "variant": variant,
        "parameters": parameters,
        "timing": {
            "started_at": attempt_started_at,
            "finished_at": attempt_started_at,
            "elapsed_ns": 0,
        },
        "requests": {
            "planned": (
                int(parameters["clients"])
                * int(parameters["requests_per_client"])
            ),
            "completed": 0,
        },
        "metrics": {
            "requests_per_second": None,
        },
        "execution": {
            "exit_code": 1,
            "valid": False,
            "failure": "attempt did not complete",
        },
        "observations": {
            "attempt_started_at": attempt_started_at,
            "completed_count_known": False,
        },
    }

    try:
        runtime, nginx, env = _materialize_runtime(
            experiment_dir,
            run["run_id"],
            attempt_number,
            variant,
            binding,
            parameters,
            workload_manifest,
            dependencies,
        )

        shutil.copy2(
            runtime / "conf" / "nginx.conf",
            attempt_dir / "nginx.conf",
        )

        test_result = subprocess.run(
            [
                str(nginx),
                "-p",
                str(runtime) + os.sep,
                "-c",
                "conf/nginx.conf",
                "-t",
            ],
            env=env,
            check=False,
            text=True,
            capture_output=True,
        )
        atomic_write_text(
            attempt_dir / "nginx-test.stdout.log",
            test_result.stdout,
        )
        atomic_write_text(
            attempt_dir / "nginx-test.stderr.log",
            test_result.stderr,
        )

        if test_result.returncode != 0:
            raise FrameworkError(
                f"NGINX configuration test failed for {variant}"
            )

        server_stdout_handle = (
            attempt_dir / "server.stdout.log"
        ).open("wb")
        server_stderr_handle = (
            attempt_dir / "server.stderr.log"
        ).open("wb")

        server = subprocess.Popen(
            [
                str(nginx),
                "-p",
                str(runtime) + os.sep,
                "-c",
                "conf/nginx.conf",
                "-g",
                "daemon off;",
            ],
            env=env,
            stdout=server_stdout_handle,
            stderr=server_stderr_handle,
            start_new_session=True,
        )

        curl = _tool_path(dependencies, "curl")

        _probe_server(
            curl=curl,
            host=str(parameters["server_host"]),
            port=int(parameters["server_port"]),
            payload_bytes=int(parameters["payload_bytes"]),
            cipher_suite=str(parameters["cipher_suite"]),
            timeout_seconds=int(parameters["startup_timeout_seconds"]),
            server_process=server,
            output_dir=attempt_dir,
        )

        warm_ok, warm_rc, warm_failure = _run_clients(
            curl=curl,
            host=str(parameters["server_host"]),
            port=int(parameters["server_port"]),
            payload_bytes=int(parameters["payload_bytes"]),
            count_per_client=int(
                parameters["warmup_requests_per_client"]
            ),
            clients=int(parameters["clients"]),
            cipher_suite=str(parameters["cipher_suite"]),
            timeout_seconds=int(parameters["client_timeout_seconds"]),
            output_dir=attempt_dir,
            phase="warmup",
        )
        if not warm_ok:
            raise FrameworkError(
                warm_failure or f"warmup failed with exit code {warm_rc}"
            )

        measured_started_at = utc_rfc3339()
        start_ns = time.perf_counter_ns()

        ok, exit_code, failure = _run_clients(
            curl=curl,
            host=str(parameters["server_host"]),
            port=int(parameters["server_port"]),
            payload_bytes=int(parameters["payload_bytes"]),
            count_per_client=int(parameters["requests_per_client"]),
            clients=int(parameters["clients"]),
            cipher_suite=str(parameters["cipher_suite"]),
            timeout_seconds=int(parameters["client_timeout_seconds"]),
            output_dir=attempt_dir,
            phase="measured",
        )

        end_ns = time.perf_counter_ns()
        elapsed_ns = end_ns - start_ns

        _aggregate_client_logs(attempt_dir, "measured")

        if not ok:
            raise FrameworkError(
                failure or f"measured clients failed with exit code {exit_code}"
            )

        planned = measurement["requests"]["planned"]
        requests_per_second = (
            planned / (elapsed_ns / 1_000_000_000)
            if elapsed_ns > 0 else None
        )

        measurement["timing"] = {
            "started_at": measured_started_at,
            "finished_at": utc_rfc3339(),
            "elapsed_ns": elapsed_ns,
        }
        measurement["requests"]["completed"] = planned
        measurement["metrics"]["requests_per_second"] = requests_per_second
        measurement["execution"] = {
            "exit_code": 0,
            "valid": True,
            "failure": None,
        }
        measurement["observations"]["completed_count_known"] = True

    except Exception as exc:
        measurement["timing"]["finished_at"] = utc_rfc3339()
        measurement["execution"] = {
            "exit_code": 1,
            "valid": False,
            "failure": str(exc),
        }

    finally:
        if server is not None:
            _stop_server(server)

        if server_stdout_handle is not None:
            server_stdout_handle.close()
        if server_stderr_handle is not None:
            server_stderr_handle.close()

        atomic_write_json(
            attempt_dir / "measurement.json",
            measurement,
        )

    return measurement


def _recount(
    experiment_dir: Path,
    schedule: dict[str, Any],
) -> tuple[int, int]:
    completed = 0
    failed = 0

    for run in schedule["runs"]:
        if _latest_valid_attempt(experiment_dir, run["run_id"]):
            completed += 1
            continue

        run_dir = experiment_dir / "raw" / "runs" / run["run_id"]
        if run_dir.is_dir() and any(
            run_dir.glob("attempt-*/measurement.json")
        ):
            failed += 1

    return completed, failed


def execute_http3_schedule(
    experiment_dir: Path,
) -> None:
    state = load_state(experiment_dir)

    if state["state"] == "READY":
        transition(experiment_dir, "RUNNING")
    elif state["state"] in {"FAILED", "ABORTED"}:
        transition(experiment_dir, "RUNNING")
    elif state["state"] != "RUNNING":
        raise FrameworkError(
            "execute requires READY, RUNNING, FAILED, or ABORTED state; "
            f"current state is {state['state']}"
        )

    schedule = read_json(
        experiment_dir / "execution" / "schedule.json"
    )

    try:
        for run in schedule["runs"]:
            if _latest_valid_attempt(
                experiment_dir,
                run["run_id"],
            ):
                continue

            append_log(
                experiment_dir / "logs" / "framework.log",
                f"{utc_rfc3339()} executing "
                f"{run['run_id']} variant={run['variant']}",
            )

            measurement = _execute_run(
                experiment_dir,
                run,
            )

            completed, failed = _recount(
                experiment_dir,
                schedule,
            )
            update_run_counts(
                experiment_dir,
                completed=completed,
                failed=failed,
            )

            if not measurement["execution"]["valid"]:
                transition(
                    experiment_dir,
                    "FAILED",
                    failure={
                        "stage": "running",
                        "message": (
                            measurement["execution"]["failure"]
                            or "HTTP/3 run failed"
                        ),
                        "run_id": run["run_id"],
                    },
                )
                raise FrameworkError(
                    f"HTTP/3 run failed: {run['run_id']}: "
                    f"{measurement['execution']['failure']}"
                )

        completed, failed = _recount(
            experiment_dir,
            schedule,
        )
        update_run_counts(
            experiment_dir,
            completed=completed,
            failed=failed,
        )

        if completed != len(schedule["runs"]):
            raise FrameworkError(
                "HTTP/3 schedule ended without all runs completing"
            )

        transition(experiment_dir, "ANALYZING")

    except KeyboardInterrupt:
        current = load_state(experiment_dir)
        if current["state"] == "RUNNING":
            transition(experiment_dir, "ABORTED")
        raise
