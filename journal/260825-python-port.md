# 2026-08-25 — Port `yt.sh` (zsh) to a Python package

**Why.** `yt.sh` had grown to 1,294 lines of zsh: three 200–400-line functions (single, playlist, fitness)
repeating the same pipeline, 24 hand-escaped `ssh`/`rsync` invocations, and no linter (shellcheck refuses zsh).
The last two feature branches each shipped a quoting/exit-status bug across the ssh boundary. It already
shelled out to Python (`jellyfin_nfo.py`) for the Jellyfin work. `gm` (get-music) is the same shape as a Python
package with 380+ fast tests, so the template existed.

**What landed.**
- Package `yt/`: `cli`, `config`, `ui`, `ssh`, `remote_scripts`, `cookies`, `session`, `single`, `playlist`,
  `fitness`, `jellyfin_nfo` (moved). `uv tool install -e .` puts `yt` on PATH; the `.zshrc` `source` line is
  now a guarded no-op because `yt.sh` is gone.
- The bash that runs on the media VM / NAS is kept **verbatim** as string constants; the Python side only
  quotes positional arguments (`ssh.run_script`). The zsh `trap`s became `Session.__exit__`
  (KeyboardInterrupt → remove remote tmp + staging, exit 130).
- Every user-visible message, prompt, exit code and cleanup decision was preserved, so the README stayed
  accurate apart from the setup section. One behaviour change: the single-video path used `/usr/bin/ssh`
  directly and was untestable; all modes now go through `$YT_SSH`.
- 38 bats tests → 132 pytest tests (96% coverage), no SSH needed: `FakeSSH` answers by command text and by
  the script content on stdin, exactly how the bats stub discriminated the fitness scripts. The playlist item
  script is still executed for real under bash with fake `yt-dlp`/`rsync`; `jellyfin_nfo.py` is tested both
  imported and piped to `python3 -`.
- ruff + pyright configured and clean; GitHub Actions runs lint, types and tests. `docs/architecture.md`
  replaces the architecture section of CLAUDE.md; the superpowers plan/spec moved to `docs/archive/`.
- README: dropped the stale "Updating yt-dlp" section (it still described `apt install`), which duplicated
  "Keeping yt-dlp current".

**Gotchas.** `argparse` must be built with `add_help=False` because `-h` is the humanity category.
`cli.py` imports the mode *modules* (`from yt import single`) rather than the functions so tests can patch
`yt.single.download_single`; importing the names broke every CLI test by calling real ssh (93 s of timeouts).
`Session.__exit__` must be annotated `-> None`, not `-> bool`, or pyright assumes exceptions may be swallowed
and reports "must return value on all code paths" in every mode function. Not verified against the live media
VM in this session — the first real `yt -g` run should be watched.
