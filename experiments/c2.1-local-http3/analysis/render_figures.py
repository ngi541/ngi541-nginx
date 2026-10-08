\
#!/usr/bin/env python3

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "processed" / "summary.csv"
FIGURES = ROOT / "figures"


def load_rows():
    with SUMMARY.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def label(row):
    kib = int(row["payload_bytes"]) // 1024
    return f"{kib} KiB\n{row['workers']}w/{row['clients']}c"


def render_throughput(rows):
    labels = [label(row) for row in rows]
    baseline = [float(row["baseline_median_rps"]) for row in rows]
    ngi541 = [float(row["ngi541_median_rps"]) for row in rows]

    x = list(range(len(rows)))
    width = 0.38

    plt.figure(figsize=(10, 5.5))
    plt.bar([v - width / 2 for v in x], baseline, width=width, label="Stock OpenSSL")
    plt.bar([v + width / 2 for v in x], ngi541, width=width, label="NGI541")
    plt.xticks(x, labels)
    plt.ylabel("Completed HTTP/3 requests/s")
    plt.xlabel("Workload configuration")
    plt.title("NGINX HTTP/3 throughput — C2.1 local experiment")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURES / "throughput-comparison.svg", format="svg")
    plt.close()


def render_delta(rows):
    labels = [label(row) for row in rows]
    delta = [float(row["median_delta_percent"]) for row in rows]
    x = list(range(len(rows)))

    plt.figure(figsize=(10, 5.5))
    bars = plt.bar(x, delta)
    plt.axhline(0, linewidth=1)
    plt.xticks(x, labels)
    plt.ylabel("NGI541 median throughput delta (%)")
    plt.xlabel("Workload configuration")
    plt.title("NGI541 relative throughput delta — C2.1 local experiment")

    for bar, value in zip(bars, delta):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            value,
            f"{value:+.2f}%",
            ha="center",
            va="bottom" if value >= 0 else "top",
        )

    plt.tight_layout()
    plt.savefig(FIGURES / "relative-throughput-delta.svg", format="svg")
    plt.close()


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    render_throughput(rows)
    render_delta(rows)


if __name__ == "__main__":
    main()
