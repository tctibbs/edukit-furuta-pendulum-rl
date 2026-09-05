# Run `just` to list recipes.

# Show available recipes
default:
    @just --list

# Sync the environment and install git hooks
[group('dev')]
install:
    uv sync
    uv run pre-commit install

# Run all hooks
[group('dev')]
check:
    uv run pre-commit run --all-files

# Download the Vale style packages the prose check reads
[group('dev')]
vale-sync:
    vale sync

# Check prose against the house style
[group('dev')]
prose:
    vale docs/ README.md


# Format and autofix with Ruff
[group('dev')]
format:
    uv run ruff format .
    uv run ruff check --fix .

# Rebuild the reference pack. Not committed, third-party copyright
[group('docs')]
docs-fetch:
    ./scripts/fetch_reference_docs.sh

# Delete the reference pack. Recover with `just docs-fetch`
[group('docs')]
docs-clean:
    rm -f docs/reference/*.{pdf,bin,zip,m}

# List the firmware targets that can be flashed
[group('hardware')]
hw-targets:
    uv run --with pyyaml python scripts/flash_firmware.py --list

# Flash a firmware target, skipping the write if the board already has it
[group('hardware')]
hw-flash TARGET="edukit" *FLAGS:
    uv run --with pyyaml python scripts/flash_firmware.py --target {{ TARGET }} {{ FLAGS }}

# Watch the serial output, answering the boot prompt with a mode if one is given
[group('hardware')]
hw-monitor MODE="":
    uv run --with pyserial python scripts/monitor_serial.py {{ if MODE != "" { "--mode " + MODE } else { "" } }}

# Measure the serial round trip. Press reset when prompted
[group('hardware')]
hw-latency MODE="1":
    uv run --with pyserial python scripts/measure_latency.py --mode {{ MODE }}

# Capture a free-swing ring-down for the suspended mode and Q
[group('hardware')]
hw-probe-freeswing SECONDS="180":
    uv run --with pyserial python -u scripts/capture_trace.py --mode w --seconds {{ SECONDS }}

# Map baseplate tilt from the resting angle around a full turn
[group('hardware')]
hw-probe-sweep SECONDS="250":
    uv run --with pyserial python -u scripts/capture_trace.py --mode y --seconds {{ SECONDS }}

# Measure dissipation across swing amplitude
[group('hardware')]
hw-probe-pump SECONDS="420":
    uv run --with pyserial python -u scripts/capture_trace.py --mode d --seconds {{ SECONDS }}

# Resolve the actuator's command units and authority. Drives the arm
[group('hardware')]
hw-probe-lean SECONDS="200":
    uv run --with pyserial python -u scripts/capture_trace.py --mode a --seconds {{ SECONDS }}

# Capture the reference swing-up and balance trace. Drives the arm
[group('hardware')]
hw-probe-trace SECONDS="220":
    uv run --with pyserial python -u scripts/capture_trace.py --mode u --seconds {{ SECONDS }}

# Fit a free-swing capture and redraw experiment 03's figures
[group('hardware')]
freeswing-fit TRACE="" FLAGS="":
    uv run docs/experiments/03-hardware-bringup/figures/analyze_freeswing.py {{ TRACE }} {{ FLAGS }}

# Redraw one experiment's figures, or every experiment's
[group('docs')]
figures EXPERIMENT="":
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    found=0
    for script in docs/experiments/{{ EXPERIMENT }}*/figures/*.py; do
        found=1
        echo "==> $script"
        uv run "$script"
    done
    if [ "$found" -eq 0 ]; then
        echo "No figure generators under docs/experiments/{{ EXPERIMENT }}*/figures/" >&2
        exit 1
    fi
