# 7Hills Link

Desktop client for [7Hills Industries](https://www.7hills.space). It reads Star Citizen's own local game telemetry and sends it to 7Net, so you can see your ship and vitals on your phone or a second screen at **7hills.space/live**, and choose what Org Command sees: nothing, only that you are online (default), or your full status.

**Download:** [7HillsLink.exe](https://github.com/TheBanjolorian/7hills-link/releases/latest/download/7HillsLink.exe) (Windows 10/11). The exe is not code-signed yet, so Windows SmartScreen asks once: *More info → Run anyway*.

## What it does

1. **Finds Star Citizen** (running game, RSI Launcher files, common install folders) — LIVE, PTU and the other channels. If it misses one, pick `StarCitizen.exe` for that channel under Settings → Game.
2. **Switches on the game's telemetry** when you press *Switch on*: adds three lines to `StarCitizen\<channel>\user.cfg` and sets `GRPC_CLIENT_SERVER_ENABLED=true` for your Windows user. Nothing else in the file changes. Restart the game afterwards.
   ```
   grpc.client.server.enabled = 1
   grpc.client.server.port = 50051
   server.game.telemetry.enabled = 1
   ```
3. **Reads the API definitions from your installed `StarCitizen.exe`**, so it keeps working after patches.
4. **Links this PC to your 7Net account**: shows a code, opens 7hills.space/link, you press *Connect this PC*. The key is stored in Windows Credential Manager.
5. **Streams** from the game's local server (`127.0.0.1:50051`, never exposed to the network) and sends the state to 7Net as soon as it changes (at most four times a second).
6. **Runs in the tray**: minimizing or closing hides the window behind a gold 7 in the notification area; quit from its menu. It starts with Windows (hidden, no music) unless you switch that off under Settings.

## Linux (Wine / Proton)

The client runs natively on Linux from source (see *Run from source*; use `export PYTHONPATH=src`). The game's telemetry server listens on the host's `127.0.0.1:50051` through Wine, so the native client can reach it.

- **Finding the game:** it looks inside the usual prefixes (`$WINEPREFIX`, `~/Games/star-citizen` from the LUG helper, other `~/Games/*` Lutris prefixes, Steam/Proton `compatdata/*/pfx`, `~/.wine`), reads the RSI Launcher's files inside them, and maps the running `StarCitizen.exe` back to its folder. If it misses yours, point it there:
  ```
  python -m sevenhills_link --game-dir ~/Games/star-citizen
  # or
  export SEVENHILLS_SC_DIR=~/Games/star-citizen
  ```
  Either takes the Wine prefix, the `StarCitizen` folder, a channel folder (`.../StarCitizen/PTU`) or `StarCitizen.exe` itself. `--game-dir` can be repeated; separate several folders in the variable with `:`.
- **`user.cfg`:** *Switch on* writes the three lines as on Windows. No admin prompt is needed, the prefix is yours.
- **`GRPC_CLIENT_SERVER_ENABLED`:** must be in the game's launch environment; the client cannot set it for you. Add `export GRPC_CLIENT_SERVER_ENABLED=true` to your launch script, or set it under Lutris → Configure → System options → Environment variables, or use Steam launch options `GRPC_CLIENT_SERVER_ENABLED=true %command%`. The client checks the running game's environment and shows a hint until it sees the variable there.
- Not verified yet: whether the telemetry server starts under Wine/Proton at all. Check with `ss -ltnp | grep 50051` while in game, and report in [issue #1](https://github.com/TheBanjolorian/7hills-link/issues/1).

## What the game's telemetry offers

See **[docs/TELEMETRY.md](docs/TELEMETRY.md)** for everything we have found: how to switch it on, every field you can read, the actions you can send to the game, and how the API definitions are read from the exe. Useful if you want to build your own tool (button boxes, Joystick Gremlin, dashboards).

## Updates

From v0.4.0 the client checks this repository's latest release at start and every 6 hours, downloads a newer `7HillsLink.exe` and checks its SHA-256 against the release. It installs by itself when the game is not running (you can switch that off under Settings and press *Restart now* instead). The client starts the downloaded exe as the installer and closes; the new exe copies itself over the old one (kept as `7HillsLink.old.exe`), starts, and puts the old one back if it does not start within 20 seconds. The steps are logged in `%LOCALAPPDATA%\7HillsLink\update\update.log`. v0.4.0 to v0.4.3 may not update themselves; install v0.4.4 or later by hand once. Keep the exe in a folder you can write to, such as Downloads or Desktop.

## What it does not do

- It does not read game memory, inject anything, or touch Easy Anti-Cheat. It only uses the telemetry server the game itself provides.
- It does not send commands to the game (yet).
- Live data on 7Net is deleted after 24 hours. Org Command sees what you choose: *Off*, *Online only* (default: your name and "in game") or *Full* (ship, seat, status; health and aUEC only if you tick them).

## Run from source

```
pip install -r requirements.txt
set PYTHONPATH=src
python -m sevenhills_link            # window
python -m sevenhills_link --headless
```

Tests: `PYTHONPATH=src python -m pytest -q tests`. Builds: GitHub Actions builds `7HillsLink.exe` on every push; every push to `main` publishes the release for the version in `src/sevenhills_link/__init__.py`.
