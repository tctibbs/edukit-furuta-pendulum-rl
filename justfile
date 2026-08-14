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
