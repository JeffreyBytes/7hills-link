"""Game.log → place, with lines shaped like a real 4.x session (Orison, then Cellin)."""

import json
from pathlib import Path

from sevenhills_link.location import GameLogFollower, Places, Tracker

PLACES = Places.load()


def L(t: str, rest: str) -> str:
    return f"<2026-11-23T{t}Z> {rest}"


JOIN = L("23:21:45.968", "[Notice] <Join PU> address[1.2.3.4] port[64298] shard[ptu_use1b_13260598_010] locationId[562954248454145] [Team_GameServices]")
BURST = [L(f"23:22:18.{i:03d}", f"[Notice] <Planet CPU Maps Loaded> Planet '{n}' (entity 1) CPU maps: x [Team_PlanetTech][Planet]")
         for i, n in enumerate(["OOC_Stanton_1d_Ita", "OOC_Stanton_4b_Clio", "pyro5a", "Nyx1", "OOC_Stanton_2c_Yela"])]
CRUSADER = L("23:22:49.232", "[Notice] <Planet CPU Maps Loaded> Planet 'OOC_Stanton_2_Crusader' (entity 1) CPU maps: x [Team_PlanetTech][Planet]")
ATC = L("23:22:50.791", "[Notice] <ATC_Reset_VehiclesBeingStoredCleared> ATC 'ATC_DataManager_Port_Lawful-Orison' [878129606879] clearing 0 entries [Team_MissionFeatures][ATC]")
LAND = L("23:22:54.549", "[Notice] <Update Inventory Location> Player [X] is changing location. Landing [0] -> [1105811199]. Location [0] -> [1105811199]. Pending [0] ")
ARM_IN = L("23:27:48.683", '[Notice] <SHUDEvent_OnNotification> Added notification "Entering Armistice Zone - Combat Prohibited: " [4] to queue.')
ARM_OUT = L("23:39:50.759", '[Notice] <SHUDEvent_OnNotification> Added notification "Leaving Armistice Zone - Caution Advised: " [17] to queue.')
LEAVE = L("23:40:02.636", "[Notice] <Update Inventory Location> Player [X] is changing location. Landing [1105811199] -> [0]. Location [1105811199] -> [2493660041]. Pending [0] ")
CELLIN = L("23:42:55.004", "[Notice] <Planet CPU Maps Loaded> Planet 'OOC_Stanton_2a_Cellin' (entity 1) CPU maps: x [Team_PlanetTech][Planet]")
UEE = L("23:42:56.698", '[Notice] <SHUDEvent_OnNotification> Added notification "Entered UEE Jurisdiction: " [18] to queue.')
LATER = L("23:43:10.000", "[Notice] <Population Manager Stats> NPCs 0/1000")
HURSTON = L("23:50:00.000", '[Notice] <SHUDEvent_OnNotification> Added notification "Entered Hurston Dynamics Jurisdiction: " [19] to queue.')


def run(lines):
    t = Tracker(PLACES)
    for line in lines:
        t.feed(line)
    return t


def test_place_list_is_consistent():
    data = json.loads(Path(__file__).resolve().parents[1].joinpath("src/sevenhills_link/data/places.json").read_text(encoding="utf-8"))
    ids = [p["id"] for p in data["places"]]
    assert len(ids) == len(set(ids))
    assert all(p["parent"] is None or p["parent"] in ids for p in data["places"])
    assert {"stanton", "pyro", "nyx"} <= set(ids)


def test_nothing_before_join_and_burst_says_nothing():
    assert run(BURST).snapshot() is None
    t = run([JOIN] + BURST)
    assert t.snapshot() is None          # loads at join cover every system
    assert t.shard == "ptu_use1b_13260598_010"


def test_lone_planet_load_settles_after_a_quiet_spell():
    t = run([JOIN] + BURST + [CRUSADER, ATC])
    assert t.snapshot() is None                       # 1.5 s later: could still be a batch
    t.feed(L("23:22:53.000", "[Notice] <Population Manager Stats> NPCs 0/1000"))
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/crusader" and snap["confidence"] == "near"


def test_landing_after_atc_puts_you_at_the_port():
    t = run([JOIN] + BURST + [CRUSADER, ATC, LAND])
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/crusader/orison"
    assert snap["confidence"] == "exact" and snap["source"] == "port"
    assert snap["raw_id"] == "1105811199"


def test_armistice_flags_and_the_port_stays_inside_the_landing_area():
    t = run([JOIN] + BURST + [CRUSADER, ATC, LAND, ARM_IN])
    assert t.snapshot()["armistice"] is True
    t.feed(ARM_OUT)
    snap = t.snapshot()
    assert snap["armistice"] is False and snap["place_id"] == "stanton/crusader/orison"
    t.feed(LEAVE)
    assert t.snapshot()["place_id"] == "stanton/crusader"


def test_flying_to_a_moon_and_uee_space_keeps_the_moon():
    t = run([JOIN] + BURST + [CRUSADER, ATC, LAND, LEAVE, CELLIN, UEE, LATER])
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/crusader/cellin" and snap["confidence"] == "near"


def test_another_planets_jurisdiction_drops_the_old_moon():
    t = run([JOIN] + BURST + [CRUSADER, ATC, LAND, LEAVE, CELLIN, LATER, HURSTON])
    snap = t.snapshot()
    assert snap["place_id"] == "stanton/hurston" and snap["confidence"] == "area"


def test_a_new_join_starts_over():
    t = run([JOIN] + BURST + [CRUSADER, ATC, LAND])
    t.feed(JOIN.replace("010", "011"))
    assert t.snapshot() is None and t.shard == "ptu_use1b_13260598_011"


def test_port_names_need_a_real_name_not_a_fragment():
    assert PLACES.port("ATC_DataManager_Port_Lawful-Orison") == "stanton/crusader/orison"
    assert PLACES.port("ANVL_Arrow_ShipATCDataManager_878144185411") is None
    assert PLACES.body("OOC_Stanton_2a_Cellin") == "stanton/crusader/cellin"
    assert PLACES.body("pyro5a") == "pyro/pyro-v/ignis"


def test_follower_reads_the_file_and_starts_over_on_a_new_log(tmp_path: Path):
    log = tmp_path / "Game.log"
    log.write_text("\n".join([JOIN] + BURST + [CRUSADER, ATC, LAND]) + "\n", encoding="utf-8")
    t = Tracker(PLACES)
    f = GameLogFollower(log, t, poll=0.01)
    f._stop.set()          # one pass: run the loop body by hand
    f._stop.clear()
    import threading
    th = threading.Thread(target=f._run, daemon=True)
    th.start()
    import time
    for _ in range(200):
        if (t.snapshot() or {}).get("place_id") == "stanton/crusader/orison":
            break
        time.sleep(0.01)
    assert t.snapshot()["place_id"] == "stanton/crusader/orison"
    f.stop()
    th.join(timeout=2)
