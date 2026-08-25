# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`yt` is a Python CLI (package `yt/`, entry point `yt.cli:main`, installed with `uv tool install -e .`) that
downloads videos via yt-dlp on a remote "media" VM over SSH, then stores them on an NFS-mounted dataset
organized by category, as a playlist library, or as an episode of a Jellyfin *Health & Fitness* show.
It replaced a 1,300-line zsh script in August 2026; behaviour, messages and remote scripts were ported 1:1.

`docs/architecture.md` is the map: data flow, the two-stage SSD-staged transfer, and what each module does.
Read it before changing anything.

## Key rules

- **stdout is for final file paths only**; every status line goes through `ui.info()` (stderr). `yt -g URL | epm`
  depends on this.
- **All remote calls go through `yt/ssh.py`.** Never call `subprocess` elsewhere. Remote scripts in
  `yt/remote_scripts.py` receive inputs as `bash -s -- args…` positionals via `ssh.run_script()`, which quotes
  every argument — do not interpolate values into script text.
- **Remote scripts stay bash** and are copied verbatim from the zsh original; edit them only for remote-side
  behaviour. Their stdout contracts are listed in `docs/architecture.md` §4.
- `yt/jellyfin_nfo.py` runs on the media VM via `python3 -` over stdin: stdlib only, no `from yt import …`.
  Its `clean_overview()` mirrors proxmox-setup's `scripts/jellyfin-fitness-migration/migrate.py` — keep in step.
- `-h` is the **humanity** category shortcut, not help (`argparse` is built with `add_help=False`).
- Failure paths decide explicitly whether to clean the remote staging dir: after a NAS or nfo failure it is
  kept for manual recovery and the message says so; after a download failure it is removed.

## Adding a category

Add one line to `CATEGORIES` in `yt/config.py`. The flag, validation, help text and README table derive from it
(update the README table by hand).

## Testing, lint, types

```
uv run python -m pytest --cov=yt     # NOT bare `uv run pytest`: a pyenv-global pytest can shadow the venv's
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

Tests never open a real SSH connection: `tests/conftest.py` patches `yt.ssh._execute` with `FakeSSH`, which
records calls and answers by rules keyed on the command text and (for the fitness scripts) the script content on
stdin. `answers("y\n")` feeds prompt input; it also sets `YT_FITNESS_ANSWERS_FROM_STDIN=1` so `ui.interactive()`
is true without a tty. When patching mode functions from CLI tests, patch `yt.single.download_single` etc. —
`cli.py` imports the modules, not the names, precisely so those patches take effect.

## Journal

`journal/yymmdd-name.md` — decisions and gotchas per change. `journal/260825-python-port.md` records the port.
