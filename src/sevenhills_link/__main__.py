"""Entry point: `7HillsLink.exe`, or `python -m sevenhills_link`.

  --write-cfg <path>   (used by the client itself, elevated) add the telemetry lines to user.cfg
  --headless           run without a window, log status to the console
  --game-dir <path>    a Star Citizen folder to look in (repeatable): the StarCitizen folder,
                       a channel folder, StarCitizen.exe or a whole Wine prefix. Same as
                       SEVENHILLS_SC_DIR (separate several with the OS path separator).
  --updated <version>  (used by the updater) started by the previous version after an update
  --autostart          (used by the Windows Run entry) start hidden in the tray, no music
  --install-to <exe> --wait <pids> --from-version <v>   (used by the updater) put this exe in place of <exe>
  --version
"""

from __future__ import annotations

import sys
from pathlib import Path


def _take_game_dirs(argv: list[str]) -> list[str]:
    """Remove --game-dir <path> / --game-dir=<path> from argv and return the paths."""
    dirs: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--game-dir" and i + 1 < len(argv):
            dirs.append(argv[i + 1])
            del argv[i:i + 2]
        elif a.startswith("--game-dir="):
            dirs.append(a.split("=", 1)[1])
            del argv[i]
        else:
            i += 1
    return dirs


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import __version__

    game_dirs = _take_game_dirs(argv)
    if game_dirs:
        import os
        from .detect import ENV_DIR
        old = [p for p in os.environ.get(ENV_DIR, "").split(os.pathsep) if p]
        os.environ[ENV_DIR] = os.pathsep.join(game_dirs + old)

    if "--version" in argv:
        print(__version__)
        return 0

    if "--install-to" in argv:
        from . import updater

        def arg(flag, default=""):
            i = argv.index(flag) if flag in argv else -1
            return argv[i + 1] if 0 <= i < len(argv) - 1 else default
        pids = [int(p) for p in arg("--wait").split(",") if p.strip().isdigit()]
        return updater.install_to(Path(arg("--install-to")), pids, arg("--from-version", "?"))

    if "--write-cfg" in argv:
        from . import gamecfg
        i = argv.index("--write-cfg")
        path = Path(argv[i + 1]) if i + 1 < len(argv) else None
        if not path or path.name.lower() != "user.cfg":
            return 2
        gamecfg.apply(path)
        return 0

    if "--headless" in argv:
        import json
        import threading
        import time
        from .core import Core
        core = Core()
        threading.Thread(target=core.run, daemon=True).start()
        try:
            while True:
                time.sleep(5)
                print(json.dumps(core.status()), flush=True)
        except KeyboardInterrupt:
            core.stop()
        return 0

    updated_from = None
    if "--updated" in argv:
        i = argv.index("--updated")
        updated_from = argv[i + 1] if i + 1 < len(argv) else "?"
        from . import updater
        updater.mark_ready()   # the swap script waits for this before it removes the backup

    from .app import run_window
    return run_window(updated_from, autostart="--autostart" in argv)


if __name__ == "__main__":
    sys.exit(main())
