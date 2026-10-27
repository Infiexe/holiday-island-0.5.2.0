## Holiday Island - Scene Guide (mod)
##
## Adds a small "play" icon to every tile in the phone's character data
## (Scenes / Events / Appointments), next to the game's own replay camera.
## The icon opens a card that shows what the game's script requires for the
## scene, sets up what can be set up (location, outfit, being alone) and
## starts the scene the same way the game would.
##
## Honest mode (default): only the surroundings are arranged; stats, quests
## and earlier scenes are shown but not changed.
## Guided mode: the conditions on the way to the scene are also forced.
## Replay: plays an unlocked scene again and restores the game afterwards.
##
## The logic lives in hisg_core.py, which reads the game's script at run
## time; nothing is written per character.

default persistent.hisg_guided = False

init 900 python:

    import sys
    import re as hisg_re
    import hisg_core as hisg

    HISG_TYPES = {"Scenes": "scene", "Events": "event", "Appointments": "appointment"}
    HISG_KIND_TEXT = {"scene": "scene", "event": "event", "appointment": "appointment", "quest": "quest step"}
    HISG_WEAR_NAMES = {
        "swimwear": ["bathing suit", "bikini", "skimpy bikini", "special bikini", "swimsuit 4", "swimsuit 5"],
        "nightwear": ["basic clothes", "revealing outfit", "super sexy outfit", "special outfit", "outfit 4"],
    }
    HISG_SPECIAL_TYPES = {"F": ("Flash breasts", "action_flash_breasts"),
                          "G": ("Grope", "action_grope"),
                          "B": ("Pose butt", "action_pose_butt")}
    HISG_COLORS = {"ok": "#7bd88f", "bad": "#ff6b6b", "auto": "#66c1e0", "unknown": "#ffd75e",
                   "choice": "#ffd75e", "info": "#b9c3cc"}
    HISG_ICONS = {"ok": u"✔", "bad": u"✘", "auto": u"⚙", "unknown": "?",
                  "choice": u"➜", "info": u"•"}
    HISG_REPLAY_SLOT = "hisg_replay"

    # -- helpers -----------------------------------------------------------

    def hisg_game():
        return sys.modules["renpy.game"]

    def hisg_esc(s):
        return (u"%s" % (s,)).replace("{", "{{").replace("[", "[[")

    def hisg_title(name):
        return hisg_esc(name.replace("_", " "))

    def hisg_index():
        rt = hisg.RUNTIME
        if rt["index"] is None and not rt["index_error"]:
            try:
                rt["index"] = hisg.Index().build(hisg_game().script.namemap)
            except Exception as e:
                rt["index_error"] = "%s: %s" % (e.__class__.__name__, e)
        return rt["index"]

    def hisg_action_texts():
        rt = hisg.RUNTIME
        if rt.get("action_texts") is None:
            try:
                screens = sys.modules["renpy.display.screen"].screens.values()
                rt["action_texts"] = hisg.collect_action_texts([s.ast for s in screens if getattr(s, "ast", None) is not None])
            except Exception:
                rt["action_texts"] = {}
        return rt["action_texts"]

    def hisg_action_text(name, char):
        tip = hisg.action_text_for(hisg_action_texts(), name)
        if not tip:
            return ""
        tip = hisg_re.sub(r"\[(\w+)\.fname\]", char.fname, tip)
        tip = hisg_re.sub(r"\{[^}]*\}", "", tip)
        return hisg_esc(tip)

    def hisg_clear_cache():
        hisg.RUNTIME["plans"].clear()
        hisg.RUNTIME["details"].clear()

    def hisg_lists(char):
        return {"scene": char.scenes_available,
                "event": char.events_available,
                "appointment": char.appointments_available}

    def hisg_current_list():
        kind = HISG_TYPES.get(getattr(player, "phone_interaction_type", "Scenes"), "scene")
        try:
            return kind, hisg_lists(phone_char)[kind]
        except Exception:
            return kind, []

    def hisg_find_meta(char, kind, name):
        for app in hisg_lists(char).get(kind, []):
            if app.name == name:
                return app
        return None

    def hisg_seen_times(char, kind, name):
        try:
            return getattr(char, "get_%s_seen_times" % kind)(name)
        except Exception:
            return 0

    def hisg_on_island(char):
        try:
            return char in list_of_characters or char.is_special_character or char in (jennifer, sara)
        except Exception:
            return False

    def hisg_location_open(loc):
        ap = actions_left
        if loc in ("massage", "massage_wait"):
            return 22 < ap <= 32
        if loc == "doctor":
            return 30 < ap <= 46
        if loc in ("nightbar", "nightbar_bar"):
            return 10 < ap <= 18
        if loc == "restaurant":
            return ap >= 45 or 35 <= ap <= 38 or 21 <= ap <= 26
        return True

    def hisg_location_text(loc):
        if not loc:
            return ""
        if loc.endswith("_room") and loc != "player_room":
            return loc.replace("_room", "'s room")
        return {"workout": "the gym", "nightbar": "the night bar", "player_room": "your room",
                "massage": "the spa", "pool": "the pool", "beach": "the beach",
                "reception": "the reception", "doctor": "the doctor's office",
                "restaurant": "the restaurant"}.get(loc, loc.replace("_", " "))

    def hisg_wear_attr(loc):
        if loc in gl_locations_swimwear:
            return "swimwear"
        if loc in gl_locations_nightwear:
            return "nightwear"
        if loc == "restaurant":
            return "dinerwear"
        if loc == "doctor":
            return "doctorwear"
        if loc == "reception":
            return "receptionwear"
        return None

    def hisg_wear_name(attr, value):
        names = HISG_WEAR_NAMES.get(attr)
        if names and 0 <= value < len(names):
            return names[value]
        return "%s %s" % (attr, value)

    def hisg_outfit_allowed(char, attr, value):
        """Would the character agree to wear it in the game's outfit dialog?"""
        try:
            if attr not in ("swimwear", "nightwear"):
                return False
            if value == 0:
                return True
            if value == 1:
                return char.check_affection(2, 0, False, True)
            if value == 2:
                return char.check_tease_sexual(3, 0, False, True)
            if value == 3:
                if attr == "swimwear":
                    return (player.get_display_quest_item(char.fname + " swimwear") or 0) >= 20
                special = "Heather_sexy_nurse_outfit" if char.id == heather.id else char.fname + "_nightwear"
                return player.get_display_quest_item(special) == 100
        except Exception:
            return False
        return False

    def hisg_outfit_target(plan, char, meta):
        """(attr, value) the scene needs, or None."""
        ordered = sorted(plan.conds, key=lambda c: 0 if c.data.get("op") == "==" else 1)
        for c in ordered:
            if c.kind != "outfit" or not hisg.is_char_var(c.data["who"], char, store):
                continue
            attr, op, v = c.data["attr"], c.data["op"], c.data["value"]
            cur = getattr(char, attr, 0)
            if op == "==":
                return attr, v
            ok = {"!=": lambda x: x != v, ">=": lambda x: x >= v, "<=": lambda x: x <= v,
                  ">": lambda x: x > v, "<": lambda x: x < v}.get(op)
            if ok is None or ok(cur):
                continue
            for cand in range(0, 4):
                if ok(cand):
                    return attr, cand
        attr = hisg_wear_attr(plan.location)
        clothes = getattr(meta, "clothes", None) if meta is not None else None
        if attr and clothes and getattr(char, attr, 0) not in clothes:
            for cand in clothes:
                if hisg_outfit_allowed(char, attr, cand):
                    return attr, cand
            return attr, clothes[0]
        return None

    def hisg_quest_title(qname, char):
        try:
            for q in player.quests:
                if q.name == qname and q.quest_about.id == char.id:
                    return q.description
            for q in gl_quest_pool:
                if q.name == qname:
                    return q.description.replace("&1", char.fname)
        except Exception:
            pass
        return qname.replace("_", " ")

    def hisg_char_by_var(name, char):
        if name in hisg.CHAR_NAMES:
            return char
        obj = getattr(store, name, None)
        if obj is not None and hasattr(obj, "fname") and hasattr(obj, "locations"):
            return obj
        return char

    # -- plans -------------------------------------------------------------

    def hisg_quest_state(char, qname):
        try:
            return player.get_quest_state(qname, char)
        except Exception:
            return -1

    def hisg_plan(char, kind, name):
        idx = hisg_index()
        if idx is None:
            return None
        extra = hisg_quest_state(char, name) if kind == "quest" else None
        key = (char.fname, kind, name, extra)
        cache = hisg.RUNTIME["plans"]
        if key in cache:
            return cache[key]
        try:
            if kind == "quest":
                plan = None
                for mk in hisg.quest_step_markers(idx, name, extra)[:8]:
                    p = hisg.build_plan(idx, "quest", name, char, store, None, marker=mk)
                    if p.marker is None:
                        continue
                    if plan is None or (p.launchable and not plan.launchable):
                        plan = p
                    if plan.launchable:
                        break
                if plan is None:
                    plan = hisg.Plan("quest", name)
                    plan.reason = "No next step for this quest was found in the game's script."
            else:
                plan = hisg.build_plan(idx, kind, name, char, store, hisg_find_meta(char, kind, name))
        except Exception as e:
            plan = hisg.Plan(kind, name)
            plan.reason = "Scene Guide error: %s" % e
        cache[key] = plan
        return plan

    def hisg_eval(c, char, defaults=None):
        ns = dict(defaults or {})
        idx = hisg.RUNTIME["index"]
        if idx is not None:
            ns.update(hisg.step_values(idx, c, store))
        ns.update((n, char) for n in hisg.CHAR_NAMES)
        return hisg.safe_eval(c.expr, store.__dict__, ns)

    def hisg_erection_row(c, char, guided):
        """The scene checks for an erection: judge it by your lust."""
        want = hisg.effect_wanted(c)
        ns = dict((n, char) for n in hisg.CHAR_NAMES)
        steps, exact = hisg.lust_steps(c, store.__dict__, ns)
        gain = sum(x for x in steps if x > 0)
        lust = player.lust
        has_now = player.get_effect_state("erection") > 0
        overdose = player.get_effect_state("purple tablet overdose") >= 1
        p, level = hisg.erection_odds(lust, has_now, steps, overdose)
        about = u"" if exact else u" about"
        if want:
            t = u"You have an erection when it matters (your lust: %s now,%s %s by then)" % (lust, about, level)
            if p >= 0.999:
                return "ok", t, None
            if guided:
                return "auto", t + u" - set by Guided mode", None
            if p >= 0.3:
                return "unknown", t + u" - %d%% chance" % int(p * 100 + 0.5), None
            need = max(0, 60 - gain)
            return "bad", t + u" - raise your lust to at least %s first (or take a blue pill)" % need, None
        t = u"You stay without an erection (your lust: %s now,%s %s by then)" % (lust, about, level)
        if has_now:
            if guided:
                return "auto", t + u" - set by Guided mode", None
            return "bad", u"You have an erection now - it goes away when your lust drops", None
        if p <= 0.001:
            return "ok", t, None
        if guided:
            return "auto", t + u" - set by Guided mode", None
        need = 60 - gain
        hint = (u"lower your lust below %s to be sure" % need) if need > 0 \
            else u"the scene adds +%s lust, so it is always a gamble" % gain
        if p <= 0.7:
            return "unknown", t + u" - %d%% chance to stay soft; %s" % (int((1 - p) * 100 + 0.5), hint), None
        return "bad", t + u" - only %d%% chance to stay soft; %s" % (int((1 - p) * 100 + 0.5), hint), None

    def hisg_cond_row(c, char, guided, defaults=None):
        """(state, text, link) for one condition, or None to hide it."""
        k, d, nm = c.kind, c.data, hisg_esc(char.fname)
        if k in ("dispatch",) or "renpy.loadable" in c.src or "renpy.has_label" in c.src:
            return None  # technical checks of the game's files
        if k == "identity":
            v, _r = hisg_eval(c, char, defaults)
            if v is not False:
                return None
        if k == "choice":
            cap = hisg_re.sub(r"\[(\w+)\.fname\]", char.fname, c.src)
            cap = hisg_re.sub(r"\{[^}]*\}", "", cap)
            return "choice", u"Choose “%s” (marked in the game)" % hisg_esc(cap), None
        if k == "outfit":
            who = hisg_char_by_var(d["who"], char)
            wn = hisg_wear_name(d["attr"], d["value"])
            if d["op"] == "==":
                t = u"%s wears her %s" % (hisg_esc(who.fname), wn)
            elif d["op"] == "!=":
                t = u"%s does not wear her %s" % (hisg_esc(who.fname), wn)
            else:
                t = u"%s: %s %s %s" % (hisg_esc(who.fname), d["attr"], d["op"], d["value"])
            v, _r = hisg_eval(c, char, defaults)
            if v:
                return "ok", t, None
            if who is char and (guided or hisg_outfit_allowed(char, d["attr"], d["value"]) or d["op"] != "=="):
                return "auto", t + " - the guide changes it", None
            return "bad", t + " - she won't wear it yet", None
        if k == "alone":
            return "auto", u"You are alone with %s - the guide sends the others away" % nm, None
        if k == "company":
            return "unknown", u"Someone else has to be there too", None
        if k in ("char_location", "location"):
            return "auto", u"At %s - the guide takes you there" % hisg_location_text(d.get("location", "")), None
        if k == "effect":
            if d["effect"] == "erection":
                return hisg_erection_row(c, char, guided)
            t = u"Effect %s %s %s" % (d["effect"], d["op"], d["value"])
            v, _r = hisg_eval(c, char, defaults)
            if v:
                return "ok", t, None
            if guided:
                return "auto", t + " - set by Guided mode", None
            return "bad", t, None
        if k in ("chance", "skill"):
            t = u"Random chance" if k == "chance" else u"Your skill check (random)"
            if guided:
                return "auto", t + " - forced by Guided mode", None
            return "unknown", t + u": " + hisg_esc(c.expr), None
        v, _r = hisg_eval(c, char, defaults)
        if k == "other" and v:
            return None  # a technical condition that is already fine
        state = "unknown" if v is None else ("ok" if v else "bad")
        if guided and state != "ok":
            state = "auto"
        link = None
        if k == "quest":
            who = hisg_char_by_var(d["who"], char)
            cur = hisg_quest_state(who, d["quest"])
            t = u"Quest “%s”: step %s %s (now %s)" % (
                hisg_esc(hisg_quest_title(d["quest"], who)), d["op"], d["value"],
                "not started" if cur < 0 else ("done" if cur >= 100 else cur))
            if v is False:
                link = (who, "quest", d["quest"])
        elif k == "seen":
            who = hisg_char_by_var(d["who"], char)
            if who is char and d["name"] == hisg_current_name[0] and not d["want"]:
                return None  # "this one is not seen yet": nothing to do
            t = u"%s %s “%s” %s" % (hisg_esc(who.fname), HISG_KIND_TEXT.get(d["what"], d["what"]),
                                           hisg_title(d["name"]), "seen" if d["want"] else "not seen yet")
            if v is False and d["want"]:
                link = (who, d["what"], d["name"])
        elif k == "seen_times":
            who = hisg_char_by_var(d["who"], char)
            t = u"“%s” seen %s %s times (now %s)" % (hisg_title(d["name"]), d["op"], d["value"],
                                                          hisg_seen_times(who, d["what"], d["name"]))
            if v is False:
                link = (who, d["what"], d["name"])
        elif k == "stat":
            m = hisg_re.search(r"check_(\w+)\((\d+)", c.src)
            what = m.group(1).replace("tease_sexual", "tease") if m else "stat"
            lvl = m.group(2) if m else "?"
            t = u"%s's %s check, level %s" % (nm, what, lvl)
            if not hisg.check_must_pass(c):
                t += u" (must fail)"
        elif k == "cooldown":
            who = hisg_char_by_var(d["who"], char)
            if d["action"] == "anger_block":
                t = u"%s is not angry with you" % hisg_esc(who.fname)
            else:
                what = hisg_action_text(d["action"], who) or hisg_esc(d["action"].replace("_", " "))
                if who is player:
                    t = u"Your waiting time for \u201c%s\u201d is over" % what
                else:
                    t = u"\u201c%s\u201d is available again (no waiting time running)" % what
        elif k == "role":
            expr = d.get("expr", "")
            role = expr.split(".")[-1].replace("_", " ")
            t = u"%s has to be the %s right now (%s)" % (nm, hisg_esc(role), hisg_esc(expr))
            if guided and v is False:
                t = u"%s takes over as the %s" % (nm, hisg_esc(role))
                return "auto", t, None
        elif k == "item":
            t = u"You have “%s”" % hisg_esc(d["item"])
        elif v is None and _r.startswith("call"):
            t = u"Decided during the scene: " + hisg_esc(c.expr)
        else:
            t = u"Game condition: " + hisg_esc(c.expr)
        if guided and state == "auto":
            t += u" - forced by Guided mode"
        return state, t, link

    HISG_BLOCKING = hisg.PROGRESS_KINDS + ("appointment", "presence")

    def hisg_appointment_ids(plan):
        try:
            return [a.id for a in gl_appointment_pool if plan.entry_return and a.action_event == plan.entry_return]
        except Exception:
            return []

    def hisg_appointment_arranged(char, ids):
        try:
            return any(player.has_appointment(i, char) for i in ids)
        except Exception:
            return False

    def hisg_others_involved(char, meta, plan):
        """Other characters the scene needs (named in it or its conditions)."""
        out = []
        pool = list(getattr(store, "list_of_phone_characters", []))
        desc = (getattr(meta, "description", "") or "") if meta is not None else ""
        for other in pool:
            if other is char or not getattr(other, "fname", ""):
                continue
            if hisg_re.search(r"\b%s\b" % hisg_re.escape(other.fname), desc):
                out.append(other)
        for c in plan.conds:
            who = c.data.get("who")
            if who and not hisg.is_char_var(who, char, store):
                other = getattr(store, who, None)
                if other in pool and other is not char and other not in out:
                    out.append(other)
        return out

    hisg_current_name = [""]

    def hisg_card_data(char, kind, name):
        hisg_current_name[0] = name
        guided = bool(persistent.hisg_guided)
        key = (char.fname, kind, name, guided, actions_left)
        cache = hisg.RUNTIME["details"]
        if key in cache:
            return cache[key]
        d = {"title": "", "desc": "", "trigger": "", "requirements": "", "status": "",
             "rows": [], "notes": [], "play": False, "play_hint": "", "replay": False,
             "replay_hint": "", "quest_text": ""}
        idx = hisg_index()
        if idx is None:
            d["title"] = "Scene Guide"
            d["notes"].append("The game's script could not be read: " + hisg_esc(hisg.RUNTIME["index_error"]))
            cache[key] = d
            return d

        meta = None
        if kind == "quest":
            state = hisg_quest_state(char, name)
            d["title"] = u"Quest: " + hisg_esc(hisg_quest_title(name, char))
            d["status"] = "Not started" if state < 0 else ("Fulfilled" if state >= 100 else "Step %s" % state)
            try:
                d["quest_text"] = player.get_quest_state_text(name, char) or ""
            except Exception:
                pass
            if state >= 100:
                d["notes"].append("This quest is already done.")
                cache[key] = d
                return d
        else:
            meta = hisg_find_meta(char, kind, name)
            times = hisg_seen_times(char, kind, name)
            d["title"] = hisg_title(name)
            d["desc"] = getattr(meta, "description", "") if meta else ""
            d["trigger"] = getattr(meta, "trigger", "") if meta else ""
            d["requirements"] = getattr(meta, "requirements", "") if meta else ""
            d["status"] = ("Seen %s time%s" % (times, "" if times == 1 else "s")) if times else "Not seen yet"
            d["seen"] = times > 0
            if meta is not None and (meta.is_sexting or meta.is_web_search):
                d["notes"].append("This one is a picture on the phone (messages or web search), not a scene. "
                                  "The game's own hints above say how to get it.")
                cache[key] = d
                return d

        plan = hisg_plan(char, kind, name)
        rows = []
        unmet = False
        blocked = []
        exact = set((c.data["who"], c.data["attr"]) for c in plan.conds
                    if c.kind == "outfit" and c.data["op"] == "==")
        defaults = hisg.default_values(plan, store)
        for c in plan.conds:
            if c.kind == "outfit" and c.data["op"] != "==" and (c.data["who"], c.data["attr"]) in exact:
                continue
            row = hisg_cond_row(c, char, guided, defaults)
            if row is None:
                continue
            if row[0] == "bad":
                unmet = True
                blocked.append(c.kind)
            if row not in rows:
                rows.append(row)

        # Appointments are arranged by the game (a quest step or a text
        # message); Honest mode only plays them once they are.
        if kind == "appointment" and plan.launchable:
            ids = hisg_appointment_ids(plan)
            if not ids:
                rows.insert(0, ("unknown", u"Could not check whether the appointment is arranged", None))
            elif hisg_appointment_arranged(char, ids):
                rows.insert(0, ("ok", u"The appointment is arranged", None))
            elif d.get("seen"):
                rows.insert(0, ("ok", u"Not arranged right now, but you have had it before", None))
            elif guided:
                rows.insert(0, ("auto", u"Not arranged yet - played anyway in Guided mode", None))
            else:
                rows.insert(0, ("bad", u"Not arranged yet - the game arranges it (see Trigger above)", None))
                blocked.append("appointment")

        absent = [o for o in hisg_others_involved(char, meta, plan) if not hisg_on_island(o)]
        for other in absent:
            rows.insert(0, ("bad", u"%s is not on the island right now" % hisg_esc(other.fname), None))
        d["rows"] = rows
        d["notes"].extend(plan.notes)
        if plan.location:
            d["where"] = u"Where: %s" % hisg_location_text(plan.location)
        if plan.entry_return:
            how = hisg_action_text(plan.entry_return, char)
            if how:
                d["how"] = u"In the game: select %s, then \u201c%s\u201d" % (hisg_esc(char.fname), how)
        if plan.skipped:
            d["notes"].append("The random trigger of this %s is skipped by the guide." % HISG_KIND_TEXT.get(kind, kind))

        on_island = hisg_on_island(char)
        if not plan.launchable:
            d["play_hint"] = plan.reason or "The guide cannot start this one."
        elif not on_island:
            d["play_hint"] = "%s is not on the island right now." % char.fname
        elif absent:
            d["play_hint"] = "%s is not on the island right now." % absent[0].fname
        elif not guided and plan.location and not hisg_location_open(plan.location):
            d["play_hint"] = "%s is closed at this time of day." % hisg_location_text(plan.location).capitalize()
        elif not guided and blocked:
            d["play_hint"] = "Not all requirements are met (marked with a cross) - switch to Guided mode to play it anyway."
        else:
            d["play"] = True
            if any(r[0] == "unknown" for r in rows) and not guided:
                d["play_hint"] = "Rows marked ? are decided by chance or during the scene."
        if plan.launchable and d.get("seen"):
            d["replay"] = True
        elif plan.launchable:
            d["replay_hint"] = "Replay is available after you have seen it once."
        cache[key] = d
        return d

    # -- special actions (flash / grope / pose) -----------------------------

    def hisg_special_info(char, i):
        info = {"launchable": False, "reason": "", "label": None, "location": "", "attr": None,
                "value": 0, "title": "", "seen": False, "times": 0}
        try:
            sa = char.special_actions[i]
        except Exception:
            info["reason"] = "Unknown interaction."
            return info
        tname, label = HISG_SPECIAL_TYPES.get(sa.special_type, (sa.special_type, None))
        info["label"] = label
        info["times"] = sa.times_used
        info["seen"] = sa.times_used > 0
        m = hisg_re.search(r"_(swim|night|reception|doctor|restaurant_table)(\d+)_", sa.image1)
        group = m.group(1) if m else sa.outfit
        value = int(m.group(2)) if m else 0
        if group == "swim":
            m2 = hisg_re.search(r"loc_([a-z]+?)\d*_main", sa.image2)
            info["location"] = m2.group(1) if m2 and m2.group(1) in gl_locations_swimwear else "pool"
            info["attr"], info["value"] = "swimwear", value
        elif group == "night":
            info["location"] = "nightbar"
            info["attr"], info["value"] = "nightwear", value
        else:
            info["reason"] = "Only possible at %s; do it there in the game." % group.replace("_", " ")
        outfit = hisg_wear_name(info["attr"], value) if info["attr"] else group.replace("_", " ")
        info["title"] = u"%s - %s" % (tname, outfit)
        if label and info["location"] and not info["reason"]:
            if not hisg_on_island(char):
                info["reason"] = "%s is not on the island right now." % char.fname
            elif not persistent.hisg_guided and not hisg_location_open(info["location"]):
                info["reason"] = "%s is closed at this time of day." % hisg_location_text(info["location"]).capitalize()
            elif not persistent.hisg_guided and not hisg_outfit_allowed(char, info["attr"], value):
                info["reason"] = "She won't wear her %s for you yet (Honest mode)." % outfit
            else:
                info["launchable"] = True
        return info

    # -- running a scene -----------------------------------------------------

    def hisg_setup_env(char, loc, outfit, alone, guided):
        """Arranges the surroundings. Returns True if the list of people
        at the location has to be rebuilt."""
        slot = actions_left - 1
        rebuild = False
        if loc:
            if not (loc.endswith("_room") and loc != "player_room"):
                store.location = loc
            try:
                char.locations[slot] = loc
            except Exception:
                pass
            rebuild = True
        if outfit:
            attr, value = outfit
            if guided or hisg_outfit_allowed(char, attr, value):
                setattr(char, attr, value)
        if alone and loc:
            others = list(list_of_characters)
            for extra in (jennifer, sara):
                if extra not in others:
                    others.append(extra)
            for other in others:
                try:
                    if other is not char and other.locations[slot] == loc:
                        other.locations[slot] = other.fname + "_room"
                except Exception:
                    pass
        store.selected_char = char
        store.event_char = char
        store.char1 = char
        store.location_detail = ""
        return rebuild

    def hisg_set_role(expr, char):
        """jobs.doctor -> setattr(jobs, "doctor", char) for this scene."""
        try:
            parts = expr.split(".")
            obj = getattr(store, parts[0])
            for part in parts[1:-1]:
                obj = getattr(obj, part)
            setattr(obj, parts[-1], char)
        except Exception:
            pass

    def hisg_setup_effects(plan):
        for c in plan.conds:
            if c.kind != "effect" or c.data["effect"] != "erection":
                continue
            if hisg.effect_wanted(c):
                player.set_effect("erection", 1)
            else:
                player.effects = [e for e in player.effects if e.name != "erection"]

    def hisg_prepare(kind, name, char, replay):
        """Sets the scene up. Returns (label, args, kwargs, rebuild) or None."""
        guided = bool(persistent.hisg_guided) or replay
        rt = hisg.RUNTIME
        if replay and not rt.get("replay_ok"):
            renpy.notify("Could not prepare the replay: %s" % rt.get("replay_error", "save failed"))
            return None
        rt["replay_ok"] = False
        rt["patcher"].restore()
        rt["highlight"].clear()
        if kind == "special":
            info = hisg_special_info(char, int(name))
            if not info["launchable"] and not replay:
                renpy.notify(info["reason"] or "This interaction cannot be started.")
                return None
            rebuild = hisg_setup_env(char, info["location"], (info["attr"], info["value"]), True, guided)
            return (info["label"], [char, info["location"]], {"auto_succeed": guided}, rebuild)

        plan = hisg_plan(char, kind, name)
        if plan is None or not plan.launchable:
            renpy.notify(plan.reason if plan is not None else "The game's script could not be read.")
            return None
        meta = hisg_find_meta(char, kind, name)
        if not replay:
            d = hisg_card_data(char, kind, name)
            if not d["play"]:
                renpy.notify(d["play_hint"] or "This one cannot be started right now.")
                return None
        alone = any(c.kind == "alone" for c in plan.conds)
        rebuild = hisg_setup_env(char, plan.location, hisg_outfit_target(plan, char, meta), alone, guided)
        if guided:
            hisg_setup_effects(plan)
            rt["patcher"].force(plan.steps)
            for c in plan.conds:
                if c.kind == "role":
                    hisg_set_role(c.data["expr"], char)
        if kind == "appointment" and not replay:
            # Played now, so it should not start again later.
            ids = hisg_appointment_ids(plan)
            for lst in (player.appointments_today, player.appointments_tomorrow):
                for app in list(lst):
                    if app.id in ids and app.with_char is char:
                        lst.remove(app)
        for st in plan.steps:
            if st[0] == "menu":
                rt["highlight"].setdefault(st[1].name, set()).add(st[2])
        values, kwvalues = hisg.resolve_args(hisg_index(), plan, char, store)
        if guided:
            kwvalues.update(hisg.auto_succeed_kwargs(hisg_index(), plan))
        return (plan.target_label, values, kwvalues, rebuild)

    def hisg_after_list(char):
        """Makes sure the character is among the people shown."""
        try:
            if char.locations[actions_left - 1] != location:
                return
            for lst in (list_of_chars_display_3, list_of_chars_display_5):
                if char not in lst:
                    if len(lst) >= (3 if lst is list_of_chars_display_3 else 5):
                        lst[-1] = char
                    else:
                        lst.append(char)
        except Exception:
            pass

    def hisg_begin(replay):
        hisg.RUNTIME["run"] = {"replay": replay}
        if replay:
            store.g_replay = True

    def hisg_finish():
        rt = hisg.RUNTIME
        run = rt["run"]
        rt["patcher"].restore()
        rt["highlight"].clear()
        rt["run"] = None
        hisg_clear_cache()
        store.g_scene_mode = False
        if run and run.get("replay"):
            store.g_replay = False
            if renpy.can_load(HISG_REPLAY_SLOT):
                renpy.load(HISG_REPLAY_SLOT)

    def hisg_replay_save():
        hisg.RUNTIME["replay_ok"] = False
        try:
            renpy.save(HISG_REPLAY_SLOT, "Scene Guide replay")
            hisg.RUNTIME["replay_ok"] = True
        except Exception as e:
            hisg.RUNTIME["replay_error"] = "%s" % e

    def hisg_idle():
        """True when the main game loop waits for the player."""
        idx = hisg.RUNTIME["index"]
        if idx is None:
            return False
        try:
            return hisg_game().context().current in idx.main_loop_idle
        except Exception:
            return False

    def hisg_watch():
        # A scene that jumped back into the game instead of returning.
        if hisg.RUNTIME["run"] is not None and hisg_idle():
            hisg_finish()

    def hisg_tiles_visible():
        try:
            return (location_detail == "phone_interactions_char"
                    and renpy.get_screen("phone") is not None
                    and not renpy.get_screen("show_image_on_phone")
                    and not renpy.get_screen("show_image_on_phone_simple")
                    and not renpy.get_screen("single_girl_intro")
                    and not renpy.get_screen("play_minigame_picture")
                    and phone_char.id != no_char.id)
        except Exception:
            return False

    def hisg_open(char, kind, name):
        hisg_clear_cache()
        hisg.RUNTIME.setdefault("history", [])[:] = []
        renpy.show_screen("hisg_card", char, kind, name)
        renpy.restart_interaction()

    def hisg_goto(char, kind, name, back=None):
        hist = hisg.RUNTIME.setdefault("history", [])
        if back is not None:
            hist.append(back)
        renpy.show_screen("hisg_card", char, kind, name)
        renpy.restart_interaction()

    def hisg_back():
        hist = hisg.RUNTIME.setdefault("history", [])
        if hist:
            char, kind, name = hist.pop()
            renpy.show_screen("hisg_card", char, kind, name)
            renpy.restart_interaction()

    def hisg_toggle_mode():
        persistent.hisg_guided = not persistent.hisg_guided
        hisg_clear_cache()
        renpy.restart_interaction()

    # -- menu highlighting --------------------------------------------------

    HISG_MARK = u"{color=#ffd75e}➜ {/color}"

    def hisg_menu_wrapper(items, *args, **kwargs):
        hl = hisg.RUNTIME["highlight"]
        if hl:
            try:
                want = hl.get(hisg_game().context().current)
                if want:
                    items = [((HISG_MARK + label) if value in want else label, cond, value)
                             for (label, cond, value) in items]
            except Exception:
                pass
        return hisg.RUNTIME["orig_menu"](items, *args, **kwargs)

    hisg_exports = sys.modules["renpy.exports"]
    if not getattr(hisg_exports.menu, "hisg_wrapped", False):
        hisg.RUNTIME["orig_menu"] = hisg_exports.menu
        hisg_menu_wrapper.hisg_wrapped = True
        hisg_exports.menu = hisg_menu_wrapper

    config.overlay_screens.append("hisg_tiles")

    def hisg_after_load():
        # Conditions forced in memory never survive a load.
        hisg.RUNTIME["patcher"].restore()
        hisg.RUNTIME["highlight"].clear()
        hisg.RUNTIME["run"] = None
        hisg_clear_cache()

    config.after_load_callbacks.append(hisg_after_load)


label hisg_run(hisg_kind, hisg_name, hisg_char, hisg_replay=False):
    $ hisg_call = hisg_prepare(hisg_kind, hisg_name, hisg_char, hisg_replay)
    if hisg_call is None:
        return
    if hisg_call[3]:
        call create_list_of_chars_display from _call_hisg_list
        $ hisg_after_list(hisg_char)
    $ hisg_begin(hisg_replay)
    # Like the game's own replay: hide the people standing around while
    # the scene plays, and redraw the location afterwards.
    $ start_scene()
    $ renpy.call(hisg_call[0], *hisg_call[1], **hisg_call[2])
    $ hisg_finish()
    $ stop_scene()
    return


## Styles -------------------------------------------------------------------

style hisg_frame is default:
    background Frame(Solid("#0b1118ee"), 0, 0)
    padding (12, 10)

style hisg_text is default:
    font "DejaVuSans.ttf"
    size 14
    color "#e6edf3"

style hisg_small is hisg_text:
    size 13
    color "#b9c3cc"

style hisg_head is hisg_text:
    size 19
    bold True
    color "#66c1e0"

style hisg_section is hisg_text:
    size 13
    bold True
    color "#66c1e0"

style hisg_button is default:
    background Solid("#1d2733")
    hover_background Solid("#2d4a63")
    insensitive_background Solid("#151b22")
    padding (10, 4)

style hisg_button_text is hisg_text:
    size 14
    color "#e6edf3"
    hover_color "#ffffff"
    insensitive_color "#5d6670"

style hisg_link is default:
    padding (0, 0)

style hisg_link_text is hisg_text:
    size 13
    color "#ffd75e"
    hover_color "#ffffff"
    underline True

style hisg_tile is default:
    background Solid("#0b1118cc")
    hover_background Solid("#2d4a63")
    xysize (26, 24)

style hisg_tile_text is hisg_text:
    size 14
    xalign 0.5
    yalign 0.5


## Icons on the phone tiles ----------------------------------------------------

screen hisg_tiles():
    zorder 215

    if hisg.RUNTIME["run"] is not None:
        timer 0.2 repeat True action Function(hisg_watch)

    if hisg_tiles_visible():
        $ hisg_vp = renpy.get_widget("phone", "interaction_screen")
        if hisg_vp is not None:
            $ hisg_kind, hisg_list = hisg_current_list()
            $ hisg_height = int(len(hisg_list) / 3.0 + 0.999999) * 73
            viewport:
                xpos 480
                ypos 210
                xmaximum 391
                ymaximum 445
                child_size (391, hisg_height)
                yadjustment hisg_vp.yadjustment
                fixed:
                    xsize 391
                    ysize hisg_height
                    for hisg_i, hisg_app in enumerate(hisg_list):
                        if not (hisg_app.is_sexting or hisg_app.is_web_search):
                            if hisg_app.is_special_type:
                                textbutton u"▶":
                                    style "hisg_tile"
                                    text_color "#ffd75e"
                                    xpos (hisg_i % 3) * 128 + 60
                                    ypos (hisg_i // 3) * 73 + 41
                                    action Function(hisg_open, phone_char, "special", "list")
                                    tooltip "03_Scene Guide: play the interactions (flash, grope, pose) one by one"
                            else:
                                $ hisg_seen = hisg_seen_times(phone_char, hisg_kind, hisg_app.name) > 0
                                textbutton u"▶":
                                    style "hisg_tile"
                                    text_color ("#66c1e0" if hisg_seen else "#ffd75e")
                                    xpos (hisg_i % 3) * 128 + 60
                                    ypos (hisg_i // 3) * 73 + 41
                                    action Function(hisg_open, phone_char, hisg_kind, hisg_app.name)
                                    tooltip ("03_Scene Guide: " + ("replay or play again" if hisg_seen else "how to unlock it, and play it"))


## The card next to the phone -------------------------------------------------

screen hisg_card(hisg_char, hisg_kind, hisg_name):
    modal True
    zorder 240

    key "game_menu" action Hide("hisg_card")

    if hisg_kind == "special":
        use hisg_special_card(hisg_char)
    else:
        use hisg_entry_card(hisg_char, hisg_kind, hisg_name)


screen hisg_card_frame(hisg_title_text):
    frame:
        style "hisg_frame"
        xpos 8
        ypos 66
        xsize 436
        ysize 646

        vbox:
            spacing 6

            hbox:
                xfill True
                text hisg_title_text style "hisg_head" xmaximum 330
                hbox:
                    xalign 1.0
                    spacing 4
                    if hisg.RUNTIME.get("history"):
                        textbutton "Back" style "hisg_button" action Function(hisg_back)
                    textbutton "Close" style "hisg_button" action Hide("hisg_card")

            hbox:
                spacing 6
                text "Mode:" style "hisg_small" yalign 0.5
                textbutton ("Guided" if persistent.hisg_guided else "Honest"):
                    style "hisg_button"
                    action Function(hisg_toggle_mode)
                    tooltip ("03_Honest: only the location, outfit and company are arranged.\nGuided: the conditions are forced too.")
                text ("conditions are forced" if persistent.hisg_guided else "surroundings only") style "hisg_small" yalign 0.5

            transclude


screen hisg_entry_card(hisg_char, hisg_kind, hisg_name):
    $ hisg_d = hisg_card_data(hisg_char, hisg_kind, hisg_name)

    use hisg_card_frame(hisg_d["title"]):

        text hisg_d["status"] style "hisg_section"

        viewport:
            ysize 446
            scrollbars "vertical"
            vscrollbar_xsize 6
            mousewheel True
            draggable True

            vbox:
                spacing 5
                xsize 400

                if hisg_d["desc"]:
                    text hisg_d["desc"] style "hisg_text"
                if hisg_d["quest_text"]:
                    text hisg_d["quest_text"] style "hisg_text"
                if hisg_d["trigger"]:
                    text "{b}Trigger:{/b} " + hisg_d["trigger"] style "hisg_small"
                if hisg_d["requirements"]:
                    text "{b}Requirements:{/b} " + hisg_d["requirements"] style "hisg_small"
                if hisg_d.get("where"):
                    text hisg_d["where"] style "hisg_text"
                if hisg_d.get("how"):
                    text hisg_d["how"] style "hisg_text"

                if hisg_d["rows"]:
                    null height 4
                    text "On the way to it" style "hisg_section"
                    for hisg_state, hisg_text, hisg_link in hisg_d["rows"]:
                        hbox:
                            spacing 6
                            text HISG_ICONS[hisg_state] style "hisg_text" color HISG_COLORS[hisg_state] min_width 16
                            vbox:
                                xsize 376
                                text hisg_text style "hisg_text"
                                if hisg_link is not None:
                                    textbutton "Show how to get it":
                                        style "hisg_link"
                                        action Function(hisg_goto, hisg_link[0], hisg_link[1], hisg_link[2], (hisg_char, hisg_kind, hisg_name))

                for hisg_note in hisg_d["notes"]:
                    text hisg_note style "hisg_small"

        hbox:
            spacing 8
            textbutton ("Play next step" if hisg_kind == "quest" else "Play"):
                style "hisg_button"
                sensitive hisg_d["play"]
                action [Hide("hisg_card"), Call("hisg_run", hisg_kind, hisg_name, hisg_char, False)]
            if hisg_kind != "quest":
                textbutton "Replay":
                    style "hisg_button"
                    sensitive hisg_d["replay"]
                    action [Function(hisg_replay_save), Hide("hisg_card"), Call("hisg_run", hisg_kind, hisg_name, hisg_char, True)]
        if hisg_d["play_hint"]:
            text hisg_d["play_hint"] style "hisg_small" color "#ffb26b"
        elif hisg_d["replay_hint"] and not hisg_d["replay"] and hisg_kind != "quest":
            text hisg_d["replay_hint"] style "hisg_small"


screen hisg_special_card(hisg_char):
    use hisg_card_frame("Interactions - " + hisg_char.fname):

        text "Flash, grope and pose for every outfit" style "hisg_section"

        viewport:
            ysize 500
            scrollbars "vertical"
            vscrollbar_xsize 6
            mousewheel True
            draggable True

            vbox:
                spacing 4
                xsize 400
                for hisg_i in range(len(hisg_char.special_actions)):
                    $ hisg_info = hisg_special_info(hisg_char, hisg_i)
                    frame:
                        background Solid("#151d27")
                        padding (6, 4)
                        xfill True
                        vbox:
                            spacing 2
                            hbox:
                                spacing 6
                                text (HISG_ICONS["ok"] if hisg_info["seen"] else u"○") style "hisg_text" color (HISG_COLORS["ok"] if hisg_info["seen"] else HISG_COLORS["unknown"])
                                text hisg_info["title"] style "hisg_text"
                            hbox:
                                spacing 6
                                textbutton "Play":
                                    style "hisg_button"
                                    sensitive hisg_info["launchable"]
                                    action [Hide("hisg_card"), Call("hisg_run", "special", str(hisg_i), hisg_char, False)]
                                textbutton "Replay":
                                    style "hisg_button"
                                    sensitive hisg_info["seen"] and hisg_info["label"] is not None and hisg_info["location"] != ""
                                    action [Function(hisg_replay_save), Hide("hisg_card"), Call("hisg_run", "special", str(hisg_i), hisg_char, True)]
                                if hisg_info["reason"]:
                                    text hisg_info["reason"] style "hisg_small" yalign 0.5 xmaximum 250
