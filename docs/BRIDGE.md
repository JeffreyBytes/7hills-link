# Local bridge: button boxes, Joystick Gremlin and other tools

7Hills Link can open a small local API so that other programs on your PC can do two things:

- **Read** your ship and player state.
- **Send** game actions such as gear, VTOL, power, master mode and doors.

The bridge is **off by default**. When it is on:

- It listens on `127.0.0.1` only, never on your network, and nothing from 7Net can reach it.
- Every request needs your local key. Requests from web pages, meaning anything with an `Origin` header, are refused, so a website cannot drive your ship through localhost.
- Risky actions are blocked until you tick *Allow risky actions*: `v_self_destruct`, `v_eject`, `v_emergency_exit` and the door/port lock actions.
- At most 10 actions per second are accepted.

## Switching it on

1. In 7Hills Link, set **Local bridge** to **On**.
2. Press **Switch on** in the yellow card if it appears. This adds `server.game.telemetry.trigger.actions.enabled = 1` to `user.cfg`.
3. Restart Star Citizen, so the game accepts actions.
4. Press **Copy** next to the key.

## API

Base URL is `http://127.0.0.1:50052`. Send the key in one of these headers:

- `X-7Hills-Key: <key>`
- `Authorization: Bearer <key>`

| Request | Answer |
|---|---|
| `GET /state` | Compact state: `in_game`, `locomotion`, `seated`, `seat`, `crew_role`, `ship`, `ship_id`, `gear`, `vtol`, `landed`, `lights`, `master_mode`, `quantum_spooled`, `power{…}`, `shields`, `hull`, `boost_engaged`, `ifcs{…}`, `annunciators{…}`, `weapon_group`, `gimbals_locked` |
| `GET /state?raw=1` | The full telemetry frame as the game sends it |
| `GET /actions` | `{actions: [{action_name, category, holdable, blocked}]}` for the running build |
| `POST /action` with `{"name": "v_vtol_on", "hold_ms": 0}` | Sends the action. Answers `200` on success. The errors are: `401` wrong key, `403` blocked or from a web page, `429` too fast, `503` game not connected, `502` the game refused it |
| `GET /devices` | Virpil devices found on this PC (USB vendor 0x3344), one entry per device, with `selected` for the ones picked in 7Hills Link |
| `GET /events` | Server-Sent Events: `event: state` with the compact state every time it changes, and a ping every 15 s |

Examples in PowerShell:

```powershell
$h = @{ "X-7Hills-Key" = "<key>" }
Invoke-RestMethod http://127.0.0.1:50052/state -Headers $h
Invoke-RestMethod http://127.0.0.1:50052/action -Method Post -Headers $h -ContentType application/json -Body '{"name":"v_deploy_landing_system"}'
```

## Joystick Gremlin

7Hills Link ships a Gremlin user plugin, `7hills_action.py`.

1. In 7Hills Link, press **Joystick Gremlin plugin** to open the folder that has the plugin in it.
2. In Joystick Gremlin, open the **Plugins** tab and add `7hills_action.py`.
3. Add one instance of the plugin for each button or switch, and set it up like this:
   - **Button:** the physical input.
   - **Bridge key:** paste the key you copied.
   - **Action on press:** for example `v_deploy_landing_system`.
   - **Action on release:** for example `v_retract_landing_system`. Leave it empty for a push button.

A two-way switch with an on action and an off action keeps the game in step with the switch, because both actions set a fixed state instead of toggling. Good pairs for that:

| Switch | On | Off |
|---|---|---|
| Gear | `v_deploy_landing_system` | `v_retract_landing_system` |
| VTOL | `v_vtol_on` | `v_vtol_off` |
| Decoupled | `v_ifcs_vector_decoupling_on` | `v_ifcs_vector_decoupling_off` |
| Shields | `v_power_set_shields_on` | `v_power_set_shields_off` |
| Weapons power | `v_power_set_weapons_on` | `v_power_set_weapons_off` |
| Lights | `v_lights_on` | `v_lights_off` |
| Master mode | `v_master_mode_set_scm` | `v_master_mode_set_nav` |

The plugin was written for Joystick Gremlin R13's user-plugin API. If your Gremlin version shows an error when loading it, please open an issue.

## Virpil LEDs

7Hills Link lists every connected Virpil device under *Local bridge → Virpil devices*, so you can pick the ones that should show ship status. Listing only reads what Windows reports; nothing is sent to the devices.

**Panel test** (in the window) shows which button you pressed on any stick or panel, and lights an LED by number in one of the 64 colours, so you can find which number is which LED. It uses `VPC_LED_Control.exe <VID> <PID> <number> <R> <G> <B>` from Virpil's VPC Software Suite; number 0 resets the device to its own profile.

**Panel setup** ties a button and its LED to the ship:

1. Press *Add button*, then the button on your panel.
2. Pick what it does from the list (landing gear, VTOL, power, shields, doors, modes, ping…). If Star Citizen already binds that button, you get a warning, because one press would do both.
3. Choose *Push button* (each press flips it, based on what the game reports, so it never gets out of step) or *Switch* (down = on, up = off).
4. Find the LED: the number starts at the button number; press *Light* / *Next* until the right LED is lit.
5. Pick an on and an off colour (sensible defaults are filled in).

LEDs show the game's state, blink amber while gear or VTOL is moving, and go dark when you are not seated. *Add LED only* shows a warning (missile lock, taking hits, shields or hull low) on an LED without a button. Eject and self-destruct need a 1-second hold. When the game is not running, panels get their own Virpil profile back. Mappings are stored in `%LOCALAPPDATA%\7HillsLink\panel.json`; panel buttons do not need the local bridge. The plan is a rules file that maps a state to a LED, for example gear down → green. The bridge will then set the LED through Virpil's own `VPC_LED_Control.exe` on the devices you picked.

Until then, any tool that reads `GET /events` can drive LEDs itself.
