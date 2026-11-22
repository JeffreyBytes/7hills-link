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
7. **Installs itself** on first start to `%LOCALAPPDATA%\Programs\7HillsLink` (no admin rights) with Start menu and desktop shortcuts, and runs **one copy at a time**: starting it again shows the window of the one that runs. Quit with the power button in the window or from the tray. Its log is `%LOCALAPPDATA%\7HillsLink\link.log` (native crashes in `crash.log`).
6. **Runs in the tray**: minimizing or closing hides the window behind a gold 7 in the notification area; quit from its menu. It starts with Windows (hidden, no music) unless you switch that off under Settings.

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
