"""Entry point: `7HillsLink.exe`, or `python -m sevenhills_link`.

  --write-cfg <path>   (used by the client itself, elevated) add the telemetry lines to user.cfg
  --headless           run without a window, log status to the console
  --updated <version>  (used by the updater) started by the previous version after an update
  --version
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from . import __version__

    if "--version" in argv:
        print(__version__)
        return 0

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

    from .app import run_window
    return run_window(updated_from)


if __name__ == "__main__":
    sys.exit(main())
