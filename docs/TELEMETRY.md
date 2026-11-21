# Star Citizen local game telemetry: what we know

Notes from building [7Hills Link](../README.md). Star Citizen ships a small gRPC server inside the game client, `sc.game.telemetry.v1.GameTelemetryService`. With it, any program on your own PC can:

- **Read** a live stream of your character and ship state at about 17 updates per second.
- **Send** a fixed list of in-game actions (gear, VTOL, power, doors, emotes and so on). Actions work like key presses; you cannot set values such as speed, health or position.

Everything here was found by reading the game's own API definitions and testing against LIVE and PTU in November 2026. CIG may change it with any patch. If something here is wrong or out of date, please open an issue.

## Contents

1. [Switching it on](#1-switching-it-on)
2. [The API](#2-the-api)
3. [Reading: what the stream contains](#3-reading-what-the-stream-contains)
4. [Sending: triggerable actions](#4-sending-triggerable-actions)
5. [Getting the .proto definitions](#5-getting-the-proto-definitions)
6. [Quick test with grpcurl](#6-quick-test-with-grpcurl)
7. [Ideas: button boxes, Joystick Gremlin, Virpil](#7-ideas-button-boxes-joystick-gremlin-virpil)

---

## 1. Switching it on

Add these lines to `user.cfg` in your channel folder (e.g. `StarCitizen\LIVE\user.cfg`; create the file if it does not exist):

```
grpc.client.server.enabled = 1
grpc.client.server.port = 50051
server.game.telemetry.enabled = 1
server.game.telemetry.trigger.actions.enabled = 1   # only needed to send actions
```

Also set the environment variable `GRPC_CLIENT_SERVER_ENABLED=true` for your Windows user, for example with `setx GRPC_CLIENT_SERVER_ENABLED true`.

Then quit the RSI Launcher fully (tray icon → Quit) and start the game again. Both the `user.cfg` lines and the environment variable are read at start.

- The server listens on `127.0.0.1` only, so nothing is exposed to your network.
- The stream starts sending once you are loaded into the game.
- If the server does not answer, a setting is missing or the game was not restarted.

## 2. The API

Service: `sc.game.telemetry.v1.GameTelemetryService`. It has three methods:

| Method | Kind | What it does |
|---|---|---|
| `TelemetryStream` | server streaming | Sends `TelemetryStreamResponse` frames, about 17 per second |
| `ListTriggerableActions` | unary | Lists the actions this build accepts (`action_name`, `category`, `holdable`) |
| `TriggerGameAction` | unary | Runs one action: `action_name`, and `hold_ms` for actions that can be held down |

Each frame carries these top-level parts: `actor`, `vehicle`, `weapons`, `events`, `turret` and `force_feedback`.

## 3. Reading: what the stream contains

Paths below are protobuf field names as JSON (`preserving_proto_field_name`).

### Player (always)

| What | Path |
|---|---|
| Movement state (walking, seated, EVA…) | `actor.state.locomotion` |
| Seat name, crew role (pilot, gunner…) | `actor.state.seat_name`, `actor.state.crew_role` |
| aUEC balance | `actor.state.uec_balance` |
| Health, oxygen, hunger, thirst, body temperature (`current` / `max` each) | `actor.vitals.health` and so on |
| Heart rate, pressure, gravity, intoxication | `actor.vitals.heart_rate`, `.pressure`, `.gravity`, `.intoxication_level` |
| Outside temperature, breathable air, radiation | `actor.environment.external_temperature`, `.breathable_atmosphere`, `.ambient_radiation_rate` |

### Ship (only while seated)

**Identity and overall state**

| What | Path |
|---|---|
| Ship id: unique per ship instance, so two players with the same id are in the same ship. Example: `AEGS_Idris_M_877512102339` | `vehicle.state.name` |
| Class, manufacturer, vehicle type | `vehicle.state.class_name`, `.manufacturer`, `.type` |
| Hull health (overall only) | `vehicle.state.health` |
| Lights | `vehicle.state.lights_enabled` |
| Master mode (NAV/SCM), quantum spooled | `vehicle.state.master_mode.mode`, `.spooled` |
| Shields: overall level and each face | `vehicle.state.shields.level`, `.faces[]` |
| Power on/off per system: power plants, engines, weapons, coolers, life support, sensors, gravity generators, shield generators, shield emitters | `vehicle.state.power.*` |
| Cockpit warning lights | `vehicle.state.annunciators.*` |

**Flight**

| What | Path |
|---|---|
| Landing gear, VTOL, landed | `vehicle.state.flight.state.gear`, `.vtol`, `.is_landed` |
| IFCS / flight settings | `vehicle.state.flight.settings.*` |
| Speed, altitude, radar altitude, heading, vertical speed | `vehicle.state.flight.instruments.speed`, `.altitude`, `.radar_altitude`, `.heading`, `.vertical_speed_indicator` |
| G-load (current / max) | `vehicle.state.flight.instruments.g_meter` |
| Hydrogen and quantum fuel | `vehicle.state.flight.instruments.hydrogen_fuel`, `.quantum_fuel` |
| Boost: reserves, engaged, output, critical | `vehicle.state.flight.instruments.boost.*` |

**Weapons and events**

| What | Path |
|---|---|
| Active weapon group and gimbal lock | `weapons.preset_index`, `.preset_name`, `.settings.gimbals_locked` |
| Per weapon: name, powered, ready to fire, in active group | `weapons.weapons[]` |
| Countermeasure types and how many are left | `weapons.countermeasures[]` |
| Game events, e.g. entering or leaving a seat | `events.events[].type` |

### Quirks we have seen

- In space, altitude is reported as FLT_MAX (about 3.4e38). Treat it as "no altitude".
- Quantum fuel has always read 0 for us so far.
- While the ship sits still, G-load can read 0 and heading 360.
- A drop in pressure while not in EVA is a reliable sign of decompression.
- Gear and VTOL report `DEPLOYED` / `RETRACTED`, and `DEPLOYING` / `RETRACTING` while moving, so a panel can show the in-between state.
- Annunciator keys seen: `pwr`, `wpn`, `thr`, `shld`, `cool`, `qdrv`, `radr`, `prox`, `hit`, `misl`. Their values are `nominal` or `off` normally, and `minor_on` / `major_on` when they light.
- `power` has one flag per system: `powerplants`, `engines`, `weapons`, `coolers`, `life_support`, `sensors`, `shield_generators`, `shield_emitters`, `gravity_generators`.
- The IFCS settings we have seen are `ifcs_spacebreak_enables_boost`, `course_prediction`, `ifcs_g_safe_disabled_by_boost`, `advanced_hud_enabled_scm`, `advanced_hud_enabled_nav`, `advanced_hud_labels` and `flight_light_amplification`. Decoupled mode, G-safe and proximity assist are not reported, so their state cannot be read.
- Seat names look like `ANVL_Asgard_SCItem_Seat_Pilot_877602855924`, and the ship id like `ANVL_Asgard_877602855866`. Everyone seated in the same ship gets the same ship id.
- When you leave the seat, the `vehicle` part of the frame is empty right away.

### What is not in the stream

- Position or location in the 'verse.
- Doors, fuses and damage to individual components.
- Other players and targets.
- Ship data while you are on foot. Only your own vitals are sent then.
- What other crew members do. Each client only reports its own player. You see someone else's actions only through their effect on the ship, for example a system that powers off or shields that drop. Who did it is not reported.
- Interaction with engineering screens and fuse panels.

## 4. Sending: triggerable actions

Actions are sent with `TriggerGameAction { action_name, hold_ms }`. `ListTriggerableActions` returns the list for the build you run; the list below is from PTU, November 2026 (112 actions).

**Lights and player**
- `v_lights`, `v_lights_on`, `v_lights_off`
- `mobiglas`, `toggle_flashlight`, `v_starmap`, `visor_wipe`

**Emotes (34)**

`emote_` followed by one of: agree, angry, atease, attention, blah, bored, bow, burp, cheer, chicken, clap, come, cry, dance, disagree, failure, flex, flirt, gasp, gloat, greet, laugh, launch, point, rude, salute, sit, sleep, smell, taunt, threaten, wait, wave, whistle

**Seat and operator modes**
- Leave the seat: `v_eject`, `v_emergency_exit`
- Remote turrets: `v_enter_remote_turret_1`, `_2`, `_3`
- Night vision: `v_light_amplification_on`, `_off`, `_toggle`
- Cycle operator mode: `v_operator_mode_cycle_forward`, `v_operator_mode_cycle_back`
- Set operator mode:
  - `v_set_flight_mode`, `v_set_guns_mode`, `v_set_scan_mode`
  - `v_set_quantum_mode`, `v_set_mining_mode`, `v_set_salvage_mode`, `v_set_refuel_mode`

**Ship (general)**
- `v_flightready`
- Doors: `v_open_all_doors`, `v_close_all_doors`, `v_toggle_all_doors`
- Door locks: `v_lock_all_doors`, `v_unlock_all_doors`, `v_toggle_all_doorlocks`
- Ports: `v_lock_all_ports`, `v_unlock_all_ports`, `v_toggle_all_portlocks`
- `v_self_destruct`
- `v_toggle_docking_request`

**Flight**
- Landing: `v_atc_request`, `v_deploy_landing_system`, `v_retract_landing_system`, `v_toggle_landing_system`
- VTOL: `v_vtol_on`, `_off`, `_toggle`
- Advanced HUD: `v_flight_advanced_hud_on`, `_off`, `_toggle`
- G-safe: `v_ifcs_gsafe_on`, `_off`, `v_ifcs_toggle_gforce_safety`
- Proximity assist: `v_ifcs_proximity_assist_on`, `_off`, `_toggle`
- Decoupled mode: `v_ifcs_vector_decoupling_on`, `_off`, `_toggle`
- Other IFCS: `v_ifcs_toggle_esp`, `v_ifcs_reset_gmeter_max`
- Master mode: `v_master_mode_set_nav`, `v_master_mode_set_scm`, `v_master_mode_cycle`
- Transform: `v_transform_deploy`, `v_transform_retract`, `v_transform_cycle`

**Power**
- All systems: `v_power_set_on`, `v_power_set_off`, `v_power_toggle`
- Shields: `v_power_set_shields_on`, `_off`, `v_power_toggle_shields`
- Thrusters: `v_power_set_thrusters_on`, `_off`, `v_power_toggle_thrusters`
- Weapons: `v_power_set_weapons_on`, `_off`, `v_power_toggle_weapons`

**Other**
- `v_toggle_qdrive_engagement`
- `v_invoke_ping`: the only action that can be held down, using `hold_ms`.
- `v_target_hail`

### Requirements we found

- Actions only work when `server.game.telemetry.trigger.actions.enabled = 1` is in the `user.cfg` of the channel you play (LIVE, PTU and so on, each has its own file), and the game was restarted after adding it.
- Every call gets an answer. Check `status` in the reply: the gRPC call itself succeeds even when the game refuses the action.
- Ship actions need you seated in a seat that controls the ship. Player actions need you on foot.

### What worked in testing

Tested from the pilot seat of an Anvil Asgard and a C8 Pisces on PTU, November 2026. Self-destruct, eject, emergency exit and the emotes were not tried.

| Game answer | Actions |
|---|---|
| `OK` (61) | All flight, power, IFCS, VTOL, gear, master mode, HUD, transform, quantum, operator modes, remote turrets, lights, night vision, flight ready, ATC, docking request, ping, hail |
| `MAP_INACTIVE` (4) | `mobiglas`, `toggle_flashlight`, `v_starmap`, `visor_wipe`: these belong to the on-foot controls, so they are inactive while seated |
| `FAILED` (9) | All door and port actions (`v_open/close/toggle_all_doors`, `v_lock/unlock/toggle_all_doorlocks`, the port versions) |

The game's statuses seen so far:

| Status | Meaning |
|---|---|
| `OK` | Accepted. For gear and VTOL we saw the ship react; for the others the answer only means the game accepted the action. |
| `FILTERED` | Accepted but blocked right now. We saw it once, for `v_vtol_off`. |
| `MAP_INACTIVE` | The control group the action belongs to is not active (for example player actions while seated, ship actions on foot). |
| `FAILED` | Tried and failed. |

**Be careful** with `v_self_destruct`, `v_eject` and the door locks. A tool that sends actions should accept them only from the local player, never from a network or a server. It is not clear how CIG's rules treat automating these actions, so use them like a button box, not as a bot.

## 5. Getting the .proto definitions

The game embeds its protobuf `FileDescriptorProto`s, the files under `sc/game/telemetry/v1/`, inside `StarCitizen.exe`.

[`src/sevenhills_link/protoset.py`](../src/sevenhills_link/protoset.py) finds them this way:

1. It searches the exe for the string `sc/game/telemetry`.
2. It walks back to where each descriptor starts and checks that the fields parse as a valid `FileDescriptorProto`.
3. It writes the descriptors out as a `FileDescriptorSet`.

Reading them from the installed exe means a tool always matches the build you run. You can use the result with `grpcurl -protoset`, or load it at runtime with `descriptor_pool` as [`stream.py`](../src/sevenhills_link/stream.py) does.

## 6. Quick test with grpcurl

First write the protoset from your exe. Change the path to match your install. In PowerShell, from a clone of this repo:

```powershell
pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -c "from pathlib import Path; from sevenhills_link import protoset; Path('telemetry.protoset').write_bytes(protoset.extract(Path(r'C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Bin64\StarCitizen.exe')).SerializeToString())"
```

Then, with the game running and loaded in:

```powershell
.\grpcurl -plaintext -protoset telemetry.protoset 127.0.0.1:50051 list
.\grpcurl -plaintext -protoset telemetry.protoset 127.0.0.1:50051 sc.game.telemetry.v1.GameTelemetryService/ListTriggerableActions
.\grpcurl -plaintext -protoset telemetry.protoset -d "{}" 127.0.0.1:50051 sc.game.telemetry.v1.GameTelemetryService/TelemetryStream
```

## 7. Ideas: button boxes, Joystick Gremlin, Virpil

The stream and the actions fit together well:

- **Explicit on/off actions.** Most actions exist as `on` and `off` versions, not only as toggles: `v_deploy_landing_system` and `v_retract_landing_system`, `v_power_set_shields_on` and `_off`, `v_ifcs_vector_decoupling_on` and `_off`. A switch on a panel can therefore send the state it is in rather than a toggle.
- **Real state on the panel.** The stream tells you the current state, so a panel or its LEDs can show what the ship actually reports. Examples: gear down, shields on, decoupled, master mode, weapons powered.
- **Panels stay in sync.** After a death, a ship swap or a crew member pressing the key, the panel can read the new state instead of drifting out of step.

Possible ways to connect it:

- A small local bridge that turns joystick button events (Joystick Gremlin, or the Virpil/VKB software's virtual buttons) into `TriggerGameAction` calls.
- The same bridge driving Virpil LEDs from the stream, through Virpil's own LED tools or their USB HID protocol.

7Hills Link does not do this; a separate panel app is planned.
