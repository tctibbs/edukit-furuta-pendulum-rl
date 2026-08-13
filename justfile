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
