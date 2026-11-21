"""Joystick Gremlin user plugin: send a Star Citizen action through 7Hills Link.

Setup
  1. In 7Hills Link, switch on "Local bridge" and press Copy next to the key.
  2. In Joystick Gremlin: Plugins tab -> add this file. Add one instance per button.
  3. Per instance: pick the physical button, paste the key, and type the action
     to send on press (and optionally on release), e.g.
        on press:   v_deploy_landing_system
        on release: v_retract_landing_system
     A toggle switch with an on and an off action keeps the game in step with
     the switch. Leave "on release" empty for a push button.

Action names: GET http://127.0.0.1:50052/actions (with the key), or the list in
docs/TELEMETRY.md of https://github.com/TheBanjolorian/7hills-link.
Risky actions (self-destruct, eject, door locks) only work after you allow them
in 7Hills Link.
"""

import json
import threading
import urllib.request

import gremlin
from gremlin.user_plugin import *

mode = ModeVariable("Mode", "Mode in which this button is active")
button = PhysicalInputVariable(
    "Button",
    "Physical button or switch",
    [gremlin.common.InputType.JoystickButton],
)
on_press = StringVariable("Action on press", "Game action sent when pressed, e.g. v_deploy_landing_system", "")
on_release = StringVariable("Action on release", "Game action sent when released (optional)", "")
hold_ms = IntegerVariable("Hold (ms)", "Only for holdable actions such as v_invoke_ping; 0 otherwise", 0, 0, 10000)
key = StringVariable("Bridge key", "Copy it from 7Hills Link (Local bridge)", "")
port = IntegerVariable("Bridge port", "Port shown in 7Hills Link", 50052, 1024, 65535)

decorator = button.create_decorator(mode.value)


def _send(action):
    """POST to the bridge in a thread, so Gremlin's input handling never waits on it."""
    action = (action or "").strip()
    if not action:
        return

    def go():
        body = json.dumps({"name": action, "hold_ms": hold_ms.value}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:%d/action" % port.value,
            data=body,
            headers={"Content-Type": "application/json", "X-7Hills-Key": key.value.strip()},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3).read()
        except Exception as e:  # shown in Gremlin's log
            gremlin.util.log("7Hills Link: %s failed: %s" % (action, e))

    threading.Thread(target=go, daemon=True).start()


@decorator.button(button.input_id)
def on_button(event):
    _send(on_press.value if event.is_pressed else on_release.value)
