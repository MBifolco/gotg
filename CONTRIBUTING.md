# Contributing to GOTG

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/MBifolco/gotg.git
cd gotg
python -m venv .venv
source .venv/bin/activate
pip install -e ".[tui]"
```

Requires Python 3.11+.

## Running Tests

```bash
python -m pytest tests/ -q
```

All tests must pass before submitting a PR.

## Code Style

- Follow existing patterns in the codebase
- No additional linter or formatter is enforced; just match what's already there
- Keep changes focused — don't refactor unrelated code in the same PR

## Submitting Changes

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Add tests for new functionality
4. Run the full test suite
5. Open a pull request with a clear description of what changed and why

## Reporting Issues

Use [GitHub Issues](https://github.com/MBifolco/gotg/issues). Include steps to reproduce, expected behavior, and your environment (Python version, OS).

## API Keys

Never commit API keys or `.env` files. The `.gitignore` already excludes `.env`, but double-check before pushing.
