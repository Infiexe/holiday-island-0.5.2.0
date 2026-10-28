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

    def hisg_role_local(name):
        """l_bartender (set from jobs.bartender in the scene) -> who has the job now."""
        if name.startswith("l_"):
            try:
                obj = getattr(store.jobs, name[2:], None)
            except Exception:
                obj = None
            if obj is not None and hasattr(obj, "fname"):
                return obj
        return None

    def hisg_char_by_var(name, char):
        if name in hisg.CHAR_NAMES:
            return char
        role = hisg_role_local(name)
        if role is not None:
            return role
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
        for name in set(hisg_re.findall(r"\b(char[2-9])\b", c.src)):
            if name not in ns:
                ns[name] = char  # nobody else picked when the guide starts it
        for name in set(hisg_re.findall(r"\bl_\w+", c.src)):
            role = hisg_role_local(name)
            if role is not None:
                ns[name] = role
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

    HISG_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

    def hisg_ap_time(ap):
        """Game time of an action point (48 = 07:00, one point = 30 minutes)."""
        minutes = 7 * 60 + (48 - int(ap)) * 30
        return u"%02d:%02d" % ((minutes // 60) % 24, minutes % 60)

    def hisg_hours(ap):
        if ap is None or ap < 0:
            return u"a while"
        if ap >= 999:
            return u"a later part of the story"
        h = ap / 2.0
        if h >= 24:
            return u"%.1f days" % (h / 24.0) if h % 24 else u"%d days" % (h // 24)
        return (u"%d h" % h) if h == int(h) else (u"%.1f h" % h)

    def hisg_cooldown_left(who, name):
        try:
            for a in who.action_cooldwon_list:
                if a.name == name:
                    return a.ap_cooldown
        except Exception:
            pass
        return None

    # Row text and the game's own condition, shown on hover.
    HISG_ENGINE_SEP = u"\x1f"

    HISG_ENGINE_END = u"\x1e"

    def hisg_engine(c):
        return HISG_ENGINE_SEP + hisg_esc(c.expr) + HISG_ENGINE_END

    def hisg_engine_last(text):
        """Moves the game's condition to the end of the row text."""
        if HISG_ENGINE_SEP not in text:
            return text
        head, _s, rest = text.partition(HISG_ENGINE_SEP)
        eng, _e, tail = rest.partition(HISG_ENGINE_END)
        return head + tail + HISG_ENGINE_SEP + eng

    def hisg_time_window(c):
        """
        For a condition that only reads the clock (actions_left): the times
        it holds, in words. Tries every half hour of the day.
        """
        if set(hisg_re.findall(r"[A-Za-z_]\w*", c.src)) - {"actions_left", "and", "or", "not"}:
            return None
        ok = {}
        for ap in range(0, 50):  # 48 = 07:00 ... 1 = 06:30 next morning, 0 / 49 = the day is over
            v, _r = hisg.safe_eval(c.expr, {}, {"actions_left": ap})
            if v is None:
                return None
            ok[ap] = v
        day = [ap for ap in range(48, 0, -1) if ok[ap]]
        now = hisg_ap_time(actions_left) if 0 < actions_left <= 48 else u"the day is over"
        if not day:
            if ok[0] or ok[49]:
                return u"the day is over - time runs out and you go to sleep (now %s)" % now
            return None
        if len(day) == 48:
            return u"any time of the day"
        # Day order: 48 (07:00) down to 1 (06:30 next morning).
        runs, run = [], [day[0]]
        for ap in day[1:]:
            if ap == run[-1] - 1:
                run.append(ap)
            else:
                runs.append(run)
                run = [ap]
        runs.append(run)

        def span(r):
            if len(r) == 1:
                return u"at %s" % hisg_ap_time(r[0])
            return u"from %s to %s" % (hisg_ap_time(r[0]), hisg_ap_time(r[-1]))
        return u"%s (now %s)" % (u" or ".join(span(r) for r in runs), now)

    def hisg_describe(c, char):
        """Plain words for common game conditions, the engine's text after it."""
        window = hisg_time_window(c)
        if window:
            return window + hisg_engine(c)
        try:
            tree = hisg.pyast.parse(c.src.replace("<>", "!="), mode="eval").body
            words = hisg_words(tree, c.negated, char)
        except Exception:
            words = None
        if words:
            return words + hisg_engine(c)
        return u"Another check in the game's script (point here to see it)" + hisg_engine(c)

    def hisg_effect_text(c, d):
        """player.get_effect_state("blue pill") > 0 -> "The blue pill is working"."""
        m = hisg_re.search(r"""get_effect_state\(["']([^"']+)["']\)""", c.src)
        name = m.group(1) if m else d["effect"]
        op, v = d["op"], d["value"]
        yes = {">": v == 0, ">=": v <= 1, "!=": v == 0, "==": v > 0}.get(op)
        no = {"==": v == 0, "<=": v == 0, "<": v <= 1}.get(op)
        if yes:
            return u"You have the \u201c%s\u201d effect" % name
        if no:
            return u"You don't have the \u201c%s\u201d effect" % name
        word = {"==": u"exactly", "!=": u"not", ">": u"above", ">=": u"at least", "<": u"below", "<=": u"at most"}.get(op, op)
        return u"Your \u201c%s\u201d effect is %s level %s" % (name, word, v)

    HISG_SKILL_NAMES = {"get_strength": "strength", "get_charm": "charm", "get_looks": "looks",
                        "get_hacking": "hacking", "get_endurance": "endurance", "get_sneaking": "sneaking"}
    HISG_GETTERS = {"get_mood": "mood"}

    def hisg_flag_words(name, value):
        base = name
        for pre in ("lo_", "l_", "i_"):
            if base.startswith(pre):
                base = base[len(pre):]
                break
        base = base.replace("_", " ")
        if hisg_re.match(r"^option\d+$", name):
            return u"In the scene: your earlier dialogue choice (%s) %s" % (name, u"is open" if value else u"was already taken")
        if name.startswith("i_"):
            return u"The scene is started %s %s" % (u"with" if value else u"without", base)
        return u"In the scene: %s%s" % (u"" if value else u"not ", base)

    def hisg_op_text(op):
        return {"Eq": u"is", "NotEq": u"is not", "Gt": u"is more than", "GtE": u"is at least",
                "Lt": u"is less than", "LtE": u"is at most"}.get(op, op)

    def hisg_leaf(n, neg, char):
        """Single comparisons and calls the game uses everywhere, in words."""
        cn = n.__class__.__name__
        flip = lambda o: HISG_FLIP.get(o, o) if neg else o
        # a local flag on its own: l_titfuck, option1, i_flag
        if cn == "Name" and (n.id.startswith(("l_", "lo_", "i_")) or hisg_re.match(r"^option\d+$", n.id)):
            return hisg_flag_words(n.id, not neg)
        if cn == "Call":
            return hisg_call_words(n, True, neg, char)
        if cn != "Compare" or len(n.ops) != 1:
            return None
        op = n.ops[0].__class__.__name__
        left, right = n.left, n.comparators[0]
        try:
            rv = eval(hisg.unparse(right), {}, {})
        except Exception:
            rv = None
        lsrc = hisg.unparse(left)
        # local flag == True/False, or a started-with value
        if left.__class__.__name__ == "Name" and (left.id.startswith(("l_", "lo_", "i_")) or hisg_re.match(r"^option\d+$", left.id)):
            if isinstance(rv, bool):
                val = rv if op in ("Eq", "Is") else (not rv if op in ("NotEq", "IsNot") else None)
                if val is not None:
                    return hisg_flag_words(left.id, val != neg)
            if rv is not None and left.id.startswith(("i_", "lo_")):
                return u"The scene is started with %s %s %s" % (left.id[2:].replace("_", " "), hisg_op_text(flip(op)), rv)
            if rv is not None:
                return u"In the scene: %s %s %s" % (left.id[2:].replace("_", " "), hisg_op_text(flip(op)), rv)
        # call compared with a value
        if left.__class__.__name__ == "Call" and rv is not None:
            if isinstance(rv, bool):
                want = rv if op in ("Eq", "Is") else (not rv if op in ("NotEq", "IsNot") else None)
                if want is not None:
                    out = hisg_call_words(left, want, neg, char)
                    if out:
                        return out
            else:
                out = hisg_call_value_words(left, flip(op), rv, char)
                if out:
                    return out
        # char.id == alice.id : whose scene this is
        mi = hisg_re.match(r"^(\w+)\.(id|fname)$", lsrc)
        if mi and op in ("Eq", "NotEq"):
            other = hisg.unparse(right)
            if hisg_re.search(r"\b(char[2-9]|event_char\d)\b", lsrc + " " + other):
                # char2: another girl the game may pick while it runs
                same = (op == "Eq") != neg
                return u"no other girl gets involved" if same else u"another girl there gets involved"
            mo = hisg_re.match(r"^(\w+)\.(?:id|fname)$", other)
            who = hisg_char_by_var(mo.group(1), char) if mo else None
            name = getattr(who, "fname", None) or (rv if isinstance(rv, str) else None)
            if name:
                return u"It is %s%s" % (u"" if (op == "Eq") != neg else u"not ", hisg_esc(name))
        # outfits: char.nightwear == 1
        mw = hisg_re.match(r"^(\w+)\.(swimwear|nightwear|dinerwear|receptionwear|doctorwear)$", lsrc)
        if mw and isinstance(rv, int) and op in ("Eq", "NotEq"):
            who = hisg_char_by_var(mw.group(1), char)
            return u"%s wears %s%s" % (hisg_esc(who.fname), u"" if (op == "Eq") != neg else u"not ",
                                       hisg_wear_name(mw.group(2), rv) if mw.group(2) in ("swimwear", "nightwear") else u"work outfit %s" % (rv + 1))
        # poker internals
        if "lo_participant" in lsrc:
            if lsrc.endswith(".undress") and hisg.unparse(right).endswith(".undress_old"):
                more = flip(op) in ("GtE", "Gt")
                return u"Poker: she %s" % (u"is taking something off (she just lost a hand)" if more else u"is dressing again (she just won a hand)")
            if lsrc.endswith(".undress") and isinstance(rv, int):
                return u"Poker: she is %s stage %s of undressing" % (u"at" if flip(op) == "Eq" else u"not at", rv)
        # the island has room for another girl
        if "g_max_chars_on_island" in hisg.unparse(right) or "g_max_chars_on_island" in lsrc:
            room = (flip(op) in ("LtE", "Lt"))
            return u"There is %s on the island for another girl (limit %s)" % (u"room" if room else u"no room", g_max_chars_on_island)
        # abs(her.island_days - l_x) <= K
        ma = hisg_re.match(r"^abs\((\w+)\.island_days - (\w+)\)$", lsrc)
        if ma and isinstance(rv, int):
            who = hisg_char_by_var(ma.group(1), char)
            near = (flip(op) in ("LtE", "Lt"))
            return u"%s's time on the island (%s days) is %s %d days of the anniversary day the scene counts from" % (
                hisg_esc(who.fname), getattr(who, "island_days", "?"), u"within" if near else u"more than", rv)
        # you are at the beach
        if left.__class__.__name__ == "Name" and left.id in ("location", "location1") and isinstance(rv, str) and op in ("Eq", "NotEq"):
            return u"you are %sat %s" % (u"" if (op == "Eq") != neg else u"not ", hisg_location_text(rv))
        # mia.active == True
        mb = hisg_re.match(r"^(\w+)\.(active|visible|introduced)$", lsrc)
        if mb and isinstance(rv, bool) and op in ("Eq", "NotEq"):
            who = hisg_char_by_var(mb.group(1), char)
            yes = ((rv) == (op == "Eq")) != neg
            return u"%s is %s%s" % (hisg_esc(getattr(who, "fname", mb.group(1))), u"" if yes else u"not ",
                                    {"active": u"on the island", "visible": u"visible in your phone", "introduced": u"introduced to you"}[mb.group(2)])
        # heather.rsm[0].love >= 75
        ms = hisg_re.match(r"^(\w+)\.rsm\[0\]\.(love|affection|anger|favor|lust)$", lsrc)
        if ms and isinstance(rv, (int, float)):
            who = hisg_char_by_var(ms.group(1), char)
            try:
                now = getattr(who.rsm[0], ms.group(2))
            except Exception:
                now = "?"
            return u"%s's %s %s %s (now %s)" % (hisg_esc(who.fname), ms.group(2), hisg_op_text(flip(op)), rv, now)
        # nobody else around
        if lsrc == "len(list_of_chars_display_3)" and isinstance(rv, int):
            alone = (flip(op) == "Eq" and rv == 0) or (flip(op) in ("Lt", "LtE") and rv <= 1)
            return u"nobody else is around" if alone else u"someone else is around"
        # room service on the schedule
        if lsrc.startswith("roomservice_schedule["):
            return u"room service is %sscheduled for now" % (u"" if (op == "Eq") != neg else u"not ")
        # char.get_interaction_gameday("sex") > gameday - 20 : did it recently
        m = hisg_re.match(r"""^(\w+)\.get_interaction_gameday\(["']([^"']+)["']\)$""", lsrc)
        mr = hisg_re.match(r"^gameday - (\d+)$", hisg.unparse(right))
        if m and mr:
            who = hisg_char_by_var(m.group(1), char)
            recent = (flip(op) in ("Gt", "GtE"))
            days = int(mr.group(1))
            return u"%s %s \u201c%s\u201d with you in the last %d days" % (
                hisg_esc(who.fname), u"did" if recent else u"did not do", m.group(2), days)
        # jennifer.get_event_seen_last("X") < gameday : not already today
        m = hisg_re.match(r"""^(\w+)\.get_(scene|event|appointment)_seen_last\(["']([^"']+)["']\)$""", lsrc)
        if m and hisg.unparse(right) == "gameday":
            who = hisg_char_by_var(m.group(1), char)
            before_today = (flip(op) in ("Lt", "LtE"))
            return u"%s %s \u201c%s\u201d %s" % (hisg_esc(who.fname), HISG_KIND_TEXT.get(m.group(2), m.group(2)),
                                                  hisg_title(m.group(3)), u"did not happen today" if before_today else u"happened today")
        # char.locations[actions_left - k] == "place"
        m = hisg_re.match(r"^(\w+)\.locations\[(?:actions_left|ap)\s*-\s*(\d+)\]$", lsrc)
        if m and isinstance(rv, str) and op in ("Eq", "NotEq"):
            who = hisg_char_by_var(m.group(1), char)
            k = int(m.group(2))
            where = hisg_location_text(rv) if not rv.endswith("_room") else u"her room"
            when = u"now" if k == 1 else u"%s min from now" % (30 * (k - 1))
            is_eq = (op == "Eq") != neg
            return u"%s is %sat %s %s" % (hisg_esc(who.fname), u"" if is_eq else u"not ", where, when)
        # a.times % 2 == 0, first_island_day + N <= gameday
        m = hisg_re.match(r"^(\w+)\.(\w+) % 2$", lsrc)
        if m and rv in (0, 1) and op in ("Eq", "NotEq"):
            who = hisg_char_by_var(m.group(1), char)
            even = ((rv == 0) == (op == "Eq")) != neg
            what = HISG_ATTR_TEXT.get(m.group(2), (m.group(2).replace("_", " "), u""))[0]
            return u"%s %s an %s number of times (now %s)" % (hisg_esc(who.fname), what, u"even" if even else u"odd", getattr(who, m.group(2), "?"))
        m = hisg_re.match(r"^(\w+)\.first_island_day \+ (\d+)$", lsrc)
        if m and hisg.unparse(right) == "gameday":
            who = hisg_char_by_var(m.group(1), char)
            days = int(m.group(2))
            ok = (op in ("LtE", "Lt")) != neg
            first = getattr(who, "first_island_day", 0)
            return u"%s %s at least %d days since she arrived (arrived on day %s, today is day %s)" % (
                hisg_esc(who.fname), u"is" if ok else u"is not yet", days, first, gameday)
        # location1 in gl_locations_outside ; plain weather flags
        if op in ("In", "NotIn") and hisg.unparse(right) == "gl_locations_outside":
            inside = (op == "NotIn") != neg
            return u"you are %s" % (u"indoors" if inside else u"outdoors")
        m = hisg_re.match(r"^g_rainy_(morning|afternoon)$", lsrc)
        if m and isinstance(rv, bool):
            rain = (rv if op in ("Eq", "Is") else not rv) != neg
            return u"it %s this %s" % (u"rains" if rain else u"doesn't rain", m.group(1))
        return None

    def hisg_call_words(call, want, neg, char):
        """get_action_allowed("x") and friends used as a plain true/false test."""
        src = hisg.unparse(call)
        want = want != neg
        m = hisg_re.match(r"""^(\w+)\.get_action_allowed\(["']([^"']+)["']\)$""", src)
        if m:
            who = player if m.group(1) == "player" else hisg_char_by_var(m.group(1), char)
            special = hisg_orgasm_text(m.group(2), want)
            if special:
                return special
            what = hisg_action_text(m.group(2), who) or m.group(2).replace("_", " ")
            left = hisg_cooldown_left(who, m.group(2))
            if want:
                return u"\u201c%s\u201d is possible right now" % what
            return u"Only shortly after \u201c%s\u201d%s" % (what, u"" if left is None else u" (%s left)" % hisg_hours(left))
        m = hisg_re.match(r"""^(\w+)\.get_action_icon_available\(["']([^"']+)["']\)$""", src)
        if m:
            who = hisg_char_by_var(m.group(1), char)
            what = m.group(2).replace("nightbar_poker_", "").replace("_", " ")
            return u"%s offers \u201c%s\u201d (unlocked)" % (hisg_esc(who.fname), what) if want else u"\u201c%s\u201d is not unlocked with %s" % (what, hisg_esc(who.fname))
        m = hisg_re.match(r"""^player\.get_quest_exists\(["']([^"']+)["'],\s*(\w+)\)$""", src)
        if m:
            who = hisg_quest_owner(m.group(1), hisg_char_by_var(m.group(2), char))
            return u"Quest \u201c%s\u201d %s" % (hisg_esc(hisg_quest_title(m.group(1), who)), u"has been given to you" if want else u"has not been given yet")
        m = hisg_re.match(r"""^player\.check_set_quest_fulfilled\(["']([^"']+)["'],\s*(\w+)\)$""", src)
        if m:
            who = hisg_quest_owner(m.group(1), hisg_char_by_var(m.group(2), char))
            return u"Quest \u201c%s\u201d %s" % (hisg_esc(hisg_quest_title(m.group(1), who)), u"is done" if want else u"is not done")
        return None

    def hisg_call_value_words(call, op, rv, char):
        src = hisg.unparse(call)
        m = hisg_re.match(r"""^(\w+)\.(get_\w+)\(\)$""", src)
        if m:
            who = player if m.group(1) == "player" else hisg_char_by_var(m.group(1), char)
            owner = u"Your" if who is player else u"%s's" % hisg_esc(who.fname)
            if m.group(2) in HISG_SKILL_NAMES:
                now = getattr(who, m.group(2))()
                return u"%s %s %s %s %s (now %s)" % (owner, HISG_SKILL_NAMES[m.group(2)], u"", hisg_op_text(op), rv, now)
            if m.group(2) == "get_mood":
                now = who.get_mood()
                return u"%s mood %s \u201c%s\u201d (now \u201c%s\u201d)" % (owner, hisg_op_text(op), rv, now)
        m = hisg_re.match(r"""^(\w+)\.get_interaction_gameday\(["']([^"']+)["']\)$""", src)
        if m:
            return None
        m = hisg_re.match(r"""^(\w+)\.get_sexting_times_used\((\d+)\)$""", src)
        if m and isinstance(rv, int):
            who = hisg_char_by_var(m.group(1), char)
            used = who.get_sexting_times_used(int(m.group(2)))
            return u"Picture message %s was sent %s (now %s)" % (m.group(2), hisg_count(HISG_OPNAME.get(op, op), rv, u"time"), hisg_count("Eq", used, u"time"))
        m = hisg_re.match(r"""^player\.get_quest_state\(["']([^"']+)["'],\s*(\w+)\)$""", src)
        if m and isinstance(rv, int):
            who = hisg_quest_owner(m.group(1), hisg_char_by_var(m.group(2), char))
            cur = hisg_quest_state(who, m.group(1))
            return u"Quest \u201c%s\u201d: %s (now %s)" % (hisg_esc(hisg_quest_title(m.group(1), who)), hisg_quest_need(HISG_OPSYM.get(op, op), rv),
                                                      "not started" if cur < 0 else ("done" if cur >= 100 else u"step %s" % cur))
        m = hisg_re.match(r"""^(\w+)\.get_(scene|event|appointment)_seen_last\(["']([^"']+)["']\)$""", src)
        if m and isinstance(rv, int) is False:
            return None
        return None

    HISG_OPNAME = {"Eq": "Eq", "NotEq": "NotEq", "Gt": "Gt", "GtE": "GtE", "Lt": "Lt", "LtE": "LtE"}
    HISG_OPSYM = {"Eq": "==", "NotEq": "!=", "Gt": ">", "GtE": ">=", "Lt": "<", "LtE": "<="}

    def hisg_cooldown_starter(action, who):
        """The scene / event that starts this waiting time (link target)."""
        idx = hisg_index()
        if idx is None:
            return None
        owners = idx.cooldown_setters.get(action, [])
        for owner in owners:
            for (kind, mname), mks in idx.markers.items():
                if kind in ("scene", "event", "appointment") and any(m.owner == owner for m in mks):
                    return (who, kind, mname)
        return None

    def hisg_orgasm_text(action, want):
        """The game's orgasm timers: orgasm3days runs for 3 days after you came."""
        m = hisg_re.match(r"^orgasm(\d)days?(_text)?$", action)
        if not m:
            return None
        days = int(m.group(1))
        span = u"%s day%s" % (days, u"" if days == 1 else u"s")
        if m.group(2):
            left = hisg_cooldown_left(player, action)
            if want:
                return u"No text from the doctor about %s without an orgasm in the last 3 days" % span
            return (u"The doctor texted you that you haven't come for %s (only with the sub-dermal monitor)%s"
                    % (span, u"" if left is None else u" - still valid for %s" % hisg_hours(left)))
        left = hisg_cooldown_left(player, "orgasm%sday%s" % (days, u"" if days == 1 else u"s"))
        if want:
            return u"You haven't had an orgasm for %s%s" % (
                span, u"" if left is None else u" (that's in %s)" % hisg_hours(left))
        return u"You had an orgasm in the last %s" % span

    def hisg_cum_text(c):
        """player.cum_in_pants(): a roll from erection, how horny you are and endurance."""
        must_not = not hisg.check_must_pass(c)
        try:
            erect = player.get_effect_state("erection") > 0
            horny = player.get_effect_state("horny")
            end = player.get_endurance()
        except Exception:
            return u"Whether you cum in your pants (random)" + hisg_engine(c), None
        limit = {3: 75 - end // 1.33, 2: 50 - end // 1.6, 1: 20 - end // 2.5}.get(horny, 0)
        risk = max(0.0, min(100.0, limit)) / 100.0 if erect else 0.0
        p = 1.0 - risk if must_not else risk
        what = u"You don't cum in your pants" if must_not else u"You cum in your pants"
        t = u"%s: %d%% chance now (horny level %s, endurance %s%s)" % (
            what, int(round(p * 100)), horny, end, u"" if erect else u", no erection right now")
        return t + hisg_engine(c), p

    HISG_SKILL_GETTER = {"charm": "get_charm", "strength": "get_strength", "looks": "get_looks",
                         "hacking": "get_hacking", "sneaking": "get_hacking", "endurance": "get_endurance"}

    def hisg_skill_text(c, char):
        """Your skill check: the chance to pass it, from your skill now."""
        m = hisg_re.search(r"player\.check_(\w+)\((.*?)(?:,|\)\s*(?:==|!=|\)|$))", c.src)
        if not m:
            return u"Your skill check (partly random)" + hisg_engine(c), None
        skill = m.group(1)
        must = hisg.check_must_pass(c)
        try:
            ns = dict((n, char) for n in hisg.CHAR_NAMES)
            level = int(hisg.safe_value(m.group(2), store.__dict__, ns)[0])
            cur = getattr(player, HISG_SKILL_GETTER.get(skill, "get_" + skill))()
        except Exception:
            return u"Your %s check (partly random)" % skill + hisg_engine(c), None
        if skill == "endurance":
            p = 1.0 if cur >= level else 0.0
            need = u"needs %s" % level
        else:
            p = 1.0 if cur > level else (0.5 if cur == level else (0.25 if cur == level - 1 else 0.0))
            need = u"sure above %s, 50%% at %s, 25%% at %s" % (level, level, level - 1)
        if not must:
            p = 1.0 - p
        what = u"Your %s check%s: %d%% chance (your %s: %s; %s)" % (
            skill, u"" if must else u" has to fail", int(round(p * 100)), skill, cur, need)
        return what + hisg_engine(c), p

    def hisg_rand_p(n, ns=None):
        """renpy.random.randint(1, 100) >= 66 -> 0.35; random() < 0.3 -> 0.3"""
        if n.__class__.__name__ != "Compare" or len(n.ops) != 1:
            return None
        left, right = n.left, n.comparators[0]
        op = n.ops[0].__class__.__name__
        flip = {"Lt": "Gt", "Gt": "Lt", "LtE": "GtE", "GtE": "LtE"}
        rand = lambda x: ("randint(" in hisg.unparse(x) or hisg.unparse(x).endswith("random.random()"))
        if not rand(left):
            if not rand(right):
                return None
            left, right, op = right, left, flip.get(op, op)

        def value(x):
            # Plain numbers, or a value the scene was given (i_cheat_probability).
            v, _r = hisg.safe_value(hisg.unparse(x), store.__dict__, ns or {})
            if _r:
                raise ValueError(_r)
            return v
        try:
            v = value(right)
            if hisg.unparse(left).endswith("random.random()"):
                return max(0.0, min(1.0, {"Lt": v, "LtE": v, "Gt": 1 - v, "GtE": 1 - v}[op]))
            a, b = [int(value(x)) for x in left.args[:2]]
        except Exception:
            return None
        test = {"Eq": lambda x: x == v, "NotEq": lambda x: x != v, "Lt": lambda x: x < v,
                "LtE": lambda x: x <= v, "Gt": lambda x: x > v, "GtE": lambda x: x >= v}.get(op)
        if test is None or b < a:
            return None
        return len([x for x in range(a, b + 1) if test(x)]) / float(b - a + 1)

    def hisg_chance_words(n, neg, char, ns=None):
        cn = n.__class__.__name__
        if cn == "UnaryOp" and n.op.__class__.__name__ == "Not":
            return hisg_chance_words(n.operand, not neg, char, ns)
        p = hisg_rand_p(n, ns)
        if p is not None:
            return u"%d%% chance" % int(round((1.0 - p if neg else p) * 100))
        if cn == "BoolOp":
            is_and = n.op.__class__.__name__ == "And"
            parts = [hisg_chance_words(v, neg, char, ns) for v in n.values]
            if any(x is None for x in parts):
                return None
            joiner = u", only if " if (is_and != neg) else u", or always if "
            out = parts[0]
            for part in parts[1:]:
                out += (joiner.replace(u" if ", u" ") if part == u"the first time" else joiner) + part
            return out
        return hisg_words(n, neg, char)

    def hisg_chance_text(c, char, defaults=None):
        ns = dict(defaults or {})
        ns.update((n, char) for n in hisg.CHAR_NAMES)
        try:
            tree = hisg.pyast.parse(c.src.replace("<>", "!="), mode="eval").body
            words = hisg_chance_words(tree, c.negated, char, ns)
        except Exception:
            words = None
        if words:
            return u"Random: " + words + hisg_engine(c)
        return u"Random: the chance depends on the scene" + hisg_engine(c)

    HISG_FLIP = {"Eq": "NotEq", "NotEq": "Eq", "Lt": "GtE", "GtE": "Lt", "Gt": "LtE", "LtE": "Gt"}

    HISG_ATTR_TEXT = {
        "times_send_home": (u"has been sent home", u"time"),
        "island_days": (u"has been on the island for", u"day"),
        "times_used": (u"has been used", u"time"),
        "sexiness": (u"has sexiness", u""),
        "strength": (u"has strength", u""),
        "breast_size": (u"has breast size", u""),
    }

    HISG_FLAG_TEXT = {
        "is_special_character": (u"is one of the special girls (her own visit scenes)", u"is not one of the special girls"),
        "room_number_known": (u"- you know her room number", u"- you don't know her room number"),
        "bra_size_known": (u"- you know her bra size", u"- you don't know her bra size"),
        "active": (u"is in the game", u"is not in the game"),
    }

    def hisg_count(op, v, unit):
        """"at least 2 times", "more than once", "never"."""
        def num(x):
            if not unit:
                return u"%s" % x
            if unit == u"time":
                return {0: u"never", 1: u"once", 2: u"twice"}.get(x, u"%s times" % x)
            return u"%s %s%s" % (x, unit, u"" if x == 1 else u"s")
        if op == "Eq":
            return u"exactly " + num(v) if v else num(v)
        if op == "NotEq":
            return u"not " + (u"exactly " + num(v) if v else num(v))
        if op == "GtE":
            return u"at least once" if (v == 1 and unit == u"time") else u"at least " + num(v)
        if op == "Gt":
            return u"at least once" if (v == 0 and unit == u"time") else u"more than " + num(v)
        if op == "LtE":
            return u"never" if (v == 0 and unit == u"time") else u"at most " + num(v)
        if op == "Lt":
            return u"never" if (v == 1 and unit == u"time") else u"fewer than " + num(v)
        return None

    def hisg_attr_words(n, neg, char):
        """char.times_send_home > 0 -> "Eva has been sent home at least once (now 0)"."""
        op = n.ops[0].__class__.__name__
        if neg:
            op = HISG_FLIP.get(op, op)
        left = hisg.unparse(n.left)
        m = hisg_re.match(r"^(\w+)\.(\w+)$", left)
        if not m:
            return None
        who = hisg_char_by_var(m.group(1), char)
        if not hasattr(who, "fname"):
            return None
        try:
            v = eval(hisg.unparse(n.comparators[0]), {}, {})
            now = getattr(who, m.group(2))
        except Exception:
            return None
        if isinstance(v, bool) and m.group(2) in HISG_FLAG_TEXT:
            yes = (op == "Eq") == v
            return u"%s %s (now %s)" % (hisg_esc(who.fname), HISG_FLAG_TEXT[m.group(2)][0 if yes else 1],
                                        u"yes" if now else u"no")
        if isinstance(v, bool) or not isinstance(v, int) or not isinstance(now, (int, float)):
            return None
        verb, unit = HISG_ATTR_TEXT.get(m.group(2), (u"has %s" % m.group(2).replace("_", " "), u""))
        need = hisg_count(op, v, unit)
        if not need:
            return None
        if unit == u"time":
            return u"%s %s %s (now %s)" % (hisg_esc(who.fname), verb, need, hisg_count("Eq", int(now), unit))
        return u"%s %s %s (now %s)" % (hisg_esc(who.fname), verb, need, now)

    def hisg_seen_words(n, neg, char):
        """x.get_scene_seen("Name") == False -> "Amy has not seen scene “Name” yet"."""
        cn = n.__class__.__name__
        call, want = None, True
        if cn == "Call":
            call = n
        elif cn == "Compare" and len(n.ops) == 1 and n.left.__class__.__name__ == "Call":
            try:
                rv = eval(hisg.unparse(n.comparators[0]), {}, {})
            except Exception:
                return None
            if not isinstance(rv, bool):
                return None
            op = n.ops[0].__class__.__name__
            if op not in ("Eq", "NotEq", "Is", "IsNot"):
                return None
            call, want = n.left, (rv == (op in ("Eq", "Is")))
        if call is None:
            return None
        m = hisg_re.match(r"""^(\w+)\.get_(scene|event|appointment)_seen\(["'](\w+)["']\)$""", hisg.unparse(call))
        if not m:
            return None
        if neg:
            want = not want
        who = hisg_char_by_var(m.group(1), char)
        what = u"%s \u201c%s\u201d" % (HISG_KIND_TEXT.get(m.group(2), m.group(2)), hisg_title(m.group(3)))
        if who is char and m.group(3) == hisg_current_name[0]:
            return u"the first time" if not want else u"once you have seen it"
        return u"%s has %sseen %s" % (hisg_esc(who.fname), u"" if want else u"not yet ", what)

    def hisg_words(n, neg, char):
        cn = n.__class__.__name__
        if cn == "UnaryOp" and n.op.__class__.__name__ == "Not":
            return hisg_words(n.operand, not neg, char)
        if cn == "BoolOp":
            is_and = n.op.__class__.__name__ == "And"
            parts = [hisg_words(v, neg, char) for v in n.values]
            if any(p is None for p in parts):
                return None
            joiner = u" and " if (is_and != neg) else u" or "
            return joiner.join(parts)
        leaf = hisg_leaf(n, neg, char)
        if leaf:
            return leaf
        if cn == "Compare" and len(n.ops) == 1:
            op = n.ops[0].__class__.__name__
            if neg:
                op = HISG_FLIP.get(op, op)
            left = hisg.unparse(n.left)
            right = n.comparators[0]
            rv = None
            try:
                rv = eval(hisg.unparse(right), {}, {})
            except Exception:
                pass
            if left == "actions_left" and isinstance(rv, int):
                tt = hisg_ap_time(rv)
                return {"GtE": u"it's %s or earlier" % tt, "Gt": u"it's earlier than %s" % tt,
                        "LtE": u"it's %s or later" % tt, "Lt": u"it's later than %s" % tt,
                        "Eq": u"it's %s" % tt, "NotEq": u"it's not %s" % tt}.get(op) + \
                       u" (now %s)" % hisg_ap_time(actions_left)
            if left == "cur_weekday" and rv in HISG_WEEKDAYS:
                return (u"it's %s" if op == "Eq" else u"it's not %s") % rv
            if left in ("gameday",) and isinstance(rv, int) and op in ("LtE", "Lt") and gameday > rv - (op == "Lt"):
                return u"day %s or earlier (today is day %s) - too late in your game" % (rv - (op == "Lt"), gameday)
            if left in ("gameday",) and isinstance(rv, int):
                return {"GtE": u"day %s or later", "Gt": u"after day %s", "LtE": u"day %s or earlier",
                        "Lt": u"before day %s", "Eq": u"day %s", "NotEq": u"not day %s"}.get(op, u"day %s") % rv + \
                       u" (today is day %s)" % gameday
            m = hisg_re.match(r"^(\w+)\.island_days$", left)
            if m and isinstance(rv, int):
                who = hisg_char_by_var(m.group(1), char)
                return u"%s has been on the island for %s%s days (now %s)" % (
                    hisg_esc(who.fname), {"GtE": u"at least ", "Gt": u"more than ", "LtE": u"at most ",
                                          "Lt": u"less than "}.get(op, u""), rv, getattr(who, "island_days", "?"))
            if hisg_re.match(r"^get_its_raining\(", left) and isinstance(rv, bool):
                raining = rv if op == "Eq" else not rv
                return u"it's raining" if raining else u"it's not raining"
            if left == "player.room2" and isinstance(rv, bool):
                has = rv if op == "Eq" else not rv
                return u"you have the new hotel room" if has else u"you still have the old hotel room"
            if op in ("In", "NotIn") and hisg.unparse(right) in ("list_of_characters",):
                who = hisg_char_by_var(left, char)
                return u"%s is %son the island" % (hisg_esc(getattr(who, "fname", left)), u"" if op == "In" else u"not ")
            m = hisg_re.match(r"^(\w+)\.(lust|anger)$", left)
            if m and isinstance(rv, int):
                who = hisg_char_by_var(m.group(1), char)
                sym = {"GtE": u"at least", "Gt": u"more than", "LtE": u"at most", "Lt": u"less than",
                       "Eq": u"exactly", "NotEq": u"not"}.get(op, u"?")
                return u"%s's %s is %s %s (now %s)" % (hisg_esc(who.fname), m.group(2), sym, rv, getattr(who, m.group(2), "?"))
        if cn == "Compare" and len(n.ops) == 1:
            op = n.ops[0].__class__.__name__
            if neg:
                op = HISG_FLIP.get(op, op)
            src = hisg.unparse(n)
            # gameday - x.get_scene_seen_last("Name") >= 14
            m = hisg_re.match(r'^gameday\s*-\s*(\w+)\.get_(scene|event|appointment)_seen_last\(["\'](\w+)["\']\)\s*\W+\s*(\d+)$', src)
            if m:
                who = hisg_char_by_var(m.group(1), char)
                days = int(m.group(4))
                try:
                    since = gameday - getattr(who, "get_%s_seen_last" % m.group(2))(m.group(3))
                except Exception:
                    since = "?"
                what = u"%s %s \u201c%s\u201d" % (hisg_esc(who.fname), HISG_KIND_TEXT.get(m.group(2), m.group(2)), hisg_title(m.group(3)))
                if op in ("GtE", "Gt"):
                    return u"at least %s days since %s (now %s)" % (days + (op == "Gt"), what, since)
                return u"less than %s days since %s (now %s)" % (days + (op == "LtE"), what, since)
            # cl_functions.get_bartender() == jennifer
            m = hisg_re.match(r'^cl_functions\.get_(\w+)\(\)(?:\.id)?\s*(==|!=)\s*(\w+)(?:\.id)?$', src)
            if m and op in ("Eq", "NotEq"):
                who = hisg_char_by_var(m.group(3), char)
                return u"%s is %sthe %s on duty" % (hisg_esc(getattr(who, "fname", m.group(3))),
                                                   u"" if op == "Eq" else u"not ", m.group(1).replace("_", " "))
            # plane_girl.id == yvette.id
            m = hisg_re.match(r'^plane_girl\.(?:id|fname)\s*(==|!=)\s*(\w+)\.(?:id|fname)$', src)
            if m and op in ("Eq", "NotEq"):
                who = hisg_char_by_var(m.group(2), char)
                return u"%s %s the girl you met on the plane" % (hisg_esc(getattr(who, "fname", m.group(2))),
                                                                  u"was" if op == "Eq" else u"was not")
            # jobs.roomservice.id != amy.id
            m = hisg_re.match(r'^jobs\.(\w+)(?:\.id)?\s*(==|!=)\s*(\w+)(?:\.id)?$', src)
            if m and op in ("Eq", "NotEq"):
                who = hisg_char_by_var(m.group(3), char)
                return u"%s is %sthe %s on duty" % (hisg_esc(getattr(who, "fname", m.group(3))),
                                                   u"" if op == "Eq" else u"not ", m.group(1).replace("_", " "))
        seen = hisg_seen_words(n, neg, char)
        if seen:
            return seen
        if cn == "Compare" and len(n.ops) == 1:
            attr = hisg_attr_words(n, neg, char)
            if attr:
                return attr
        if cn == "UnaryOp":
            return None
        if cn == "Call" and hisg.unparse(n).startswith("get_its_raining("):
            return u"it's not raining" if neg else u"it's raining"
        return None

    # The game's checks compare a stat with a value that depends on the
    # level (and on your looks); find that value by trying them all.
    HISG_STATS = {"lust": ("lust", None), "affection": ("affection", 0), "love": ("love", 0), "anger": ("anger", 0)}

    def hisg_stat_value(char, stat, index=0):
        attr, idx = HISG_STATS[stat]
        return getattr(char, attr) if idx is None else getattr(char.rsm[index], attr)

    def hisg_set_stat(char, stat, value, index=0):
        attr, idx = HISG_STATS[stat]
        if idx is None:
            setattr(char, attr, value)
        else:
            setattr(char.rsm[index], attr, value)

    def hisg_threshold(char, stat, level, index=0):
        """Smallest value of the stat that passes check_<stat>(level)
        (for anger: the largest that passes)."""
        meth = getattr(char, "check_" + stat)
        old = hisg_stat_value(char, stat, index)
        found = None
        try:
            values = range(0, 101) if stat != "anger" else range(100, -1, -1)
            for x in values:
                hisg_set_stat(char, stat, x, index)
                ok = meth(level, index, False, True) if stat != "lust" else meth(level, False, True)
                if ok:
                    found = x
                    break
        except Exception:
            found = None
        finally:
            hisg_set_stat(char, stat, old, index)
        return found

    def hisg_stat_text(c, char):
        m = hisg_re.search(r"(\w+)\.check_(\w+)\((-?\d+)(?:\s*,\s*(\d+))?", c.src)
        if not m:
            return u"Stat check" + hisg_engine(c)
        who = hisg_char_by_var(m.group(1), char)
        what, lvl = m.group(2), int(m.group(3))
        ix = int(m.group(4)) if (m.group(4) and what != "lust") else 0
        nm = hisg_esc(who.fname)
        must = hisg.check_must_pass(c)
        try:
            if what == "tease_sexual":
                l1, a1, l2 = hisg_threshold(who, "lust", lvl - 1), hisg_threshold(who, "affection", lvl - 1, ix), hisg_threshold(who, "lust", lvl)
                cur = u"now lust %s, affection %s" % (hisg_stat_value(who, "lust"), hisg_stat_value(who, "affection", ix))
                if l1 is None or a1 is None:
                    return (u"%s's lust %s %s (%s)" % (nm, u"at least" if must else u"below", l2, cur)) + hisg_engine(c)
                if must:
                    return u"%s is in the mood: lust %s+, or lust %s+ with affection %s+ (%s)" % (nm, l2, l1, a1, cur) + hisg_engine(c)
                return u"%s is not in the mood: lust below %s, and below %s or affection below %s (%s)" % (nm, l2, l1, a1, cur) + hisg_engine(c)
            if what in HISG_STATS:
                need = hisg_threshold(who, what, lvl, ix)
                cur = hisg_stat_value(who, what, ix)
                if what == "anger":
                    return (u"%s's anger at most %s (now %s)" if must else u"%s's anger above %s (now %s)") % (nm, need, cur) + hisg_engine(c)
                return (u"%s's %s at least %s (now %s)" if must else u"%s's %s below %s (now %s)") % (nm, what, need, cur) + hisg_engine(c)
        except Exception:
            pass
        return u"%s's %s check, level %s" % (nm, what, lvl) + hisg_engine(c)

    def hisg_times_need(op, value):
        """seen_times <op> <value> in words: "at least twice", "not exactly once"."""
        def n(x):
            return {0: u"never", 1: u"once", 2: u"twice"}.get(x, u"%s times" % x)
        if op == "==":
            return n(value) if value == 0 else u"exactly " + n(value)
        if op == "!=" and value == 0:
            return u"at least once"
        if op == "!=":
            return u"other than " + n(value)
        if op == ">=":
            return u"at least " + n(value)
        if op == ">":
            return u"more than " + n(value)
        if op == "<=":
            return u"at most " + n(value)
        if op == "<":
            return u"fewer than " + n(value)
        return u"%s %s times" % (op, value)

    def hisg_quest_owner(qname, who):
        """Lingerie_presents1_Yvette -> Yvette, whoever the scene asks it of."""
        try:
            names = hisg._girl_names(store)
        except Exception:
            return who
        for word in qname.split("_"):
            if word in names and word != getattr(who, "fname", None):
                obj = getattr(store, names[word], None)
                if obj is not None:
                    return obj
        return who

    def hisg_quest_need(op, value):
        """Plain words for "quest step <op> <value>"."""
        if (op, value) in (("!=", -1), (">=", 0), (">", -1)):
            return u"started"
        if (op, value) in (("==", -1), ("<", 0), ("<=", -1)):
            return u"not started yet"
        if (op, value) in (("==", 100), (">=", 100)):
            return u"finished"
        if (op, value) in (("!=", 100), ("<", 100)):
            return u"not finished yet"
        if op == "!=" and value == 0:
            return u"not at the first step"
        return {"==": u"at step %s", ">=": u"at step %s or later", ">": u"past step %s",
                "<=": u"at step %s or earlier", "<": u"before step %s", "!=": u"not at step %s"}.get(op, u"step " + op + u" %s") % value

    def hisg_cond_row(c, char, guided, defaults=None):
        """(state, text, link) for one condition, or None to hide it."""
        row = hisg_cond_row_raw(c, char, guided, defaults)
        if row is None:
            return None
        text = row[1]
        if HISG_ENGINE_SEP not in text and c.kind not in ("choice", "outfit", "location", "char_location", "alone", "poker", "invited"):
            text = text + hisg_engine(c)
        return (row[0], hisg_engine_last(text), row[2])

    def hisg_cond_row_raw(c, char, guided, defaults=None):
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
            if (who is char or d["op"] == "==") and (guided or hisg_outfit_allowed(who, d["attr"], d["value"]) or d["op"] != "=="):
                return "auto", t + " - the guide changes it", None
            return "bad", t + hisg_outfit_missing_text(who, d["attr"], d["value"]), hisg_outfit_link(who, d["attr"], d["value"])
        if k == "alone":
            return "auto", u"You are alone with %s - the guide sends the others away" % nm, None
        if k == "company":
            return "unknown", u"Someone else has to be there too", None
        mo = HISG_OTHER_LOC_RE.search(c.src) if not c.negated else None
        if mo and hisg_other_girl(mo.group(1), char) is not None:
            other = hisg_other_girl(mo.group(1), char)
            where = hisg_location_text(mo.group(3))
            if other in list_of_characters:
                return "auto", u"%s is at %s too - the guide brings her there" % (hisg_esc(other.fname), where) + hisg_engine(c), None
            return "bad", u"%s has to be at %s, but she is not on the island" % (hisg_esc(other.fname), where) + hisg_engine(c), None
        m = hisg_re.match(r"""^\s*(?:i_name|i_item_name|l_item_name|l_gift_name|i_gift|l_gift|l_item)\s*==\s*["'](.+)["']\s*$""", c.src)
        if m and k == "other":
            # The present you pick from your bag.
            if c.negated:
                return None
            item = m.group(1)
            try:
                has = player.has_item(item)
            except Exception:
                has = None
            if has is False:
                return "bad", u"You need \u201c%s\u201d in your bag to give it to her" % hisg_esc(item), None
            return "choice", u"Give her \u201c%s\u201d (pick it from your presents)" % hisg_esc(item), None
        if k == "invited":
            v, _r = hisg_eval(c, char, defaults)
            t = u"You invited %s to the island and her arrival day has come" % nm
            if v:
                return "ok", t, None
            return ("auto" if guided else "bad"), t, None
        if k == "poker":
            return "auto", u"You win every hand - the guide plays the cards for you, she undresses step by step", None
        if k == "location":
            return "auto", u"At %s - the guide takes you there" % hisg_location_text(d.get("location", "")), None
        if k == "char_location":
            who = hisg_char_by_var(d["who"], char)
            where = hisg_location_text(d.get("location", ""))
            back = d.get("back", 1)
            if who is char and d["op"] == "==":
                if back == 1:
                    return "auto", u"At %s - the guide takes you there" % where, None
                return "auto", u"%s goes to %s next - the guide arranges it" % (nm, where), None
            v, _r = hisg_eval(c, char, defaults)
            t = u"%s %s at %s%s" % (hisg_esc(who.fname), ("is" if back == 1 else "will be") if d["op"] == "==" else ("is not" if back == 1 else "won't be"), where,
                                   u" next" if back > 1 else u"")
            if v or who is char:
                return ("ok" if v else "auto"), t, None
            return ("auto" if guided else "bad"), t, None
        if k == "effect":
            if d["effect"] == "erection":
                return hisg_erection_row(c, char, guided)
            t = hisg_effect_text(c, d) + hisg_engine(c)
            v, _r = hisg_eval(c, char, defaults)
            if v:
                return "ok", t, None
            if guided:
                return "auto", t + " - set by Guided mode", None
            return "bad", t, None
        if k == "skill":
            t, p = hisg_skill_text(c, char)
            if guided:
                return "auto", t + u" - Guided mode makes it go your way", None
            if p is not None and p >= 0.999:
                return "ok", t, None
            if p is not None and p <= 0.001:
                return "bad", t, None
            return "unknown", t, None
        if k == "chance":
            t = hisg_chance_text(c, char, defaults)
            if guided:
                return "auto", t + u" - Guided mode makes it go your way", None
            return "unknown", t, None
        if k == "other" and hisg.RUNTIME["index"] is not None and hisg.uses_label_locals(hisg.RUNTIME["index"], c):
            return None  # depends on values the scene sets while it runs
        v, _r = hisg_eval(c, char, defaults)
        if k == "other" and (v or _r == "local"):
            return None  # a technical condition that is fine or set while it runs
        if k == "other" and hisg_current_kind[0] in ("message", "schedule"):
            return None  # the game's own timing checks for sending messages
        state = "unknown" if v is None else ("ok" if v else "bad")
        if guided and state != "ok":
            state = "auto"
        link = None
        if k == "quest":
            who = hisg_quest_owner(d["quest"], hisg_char_by_var(d["who"], char))
            cur = hisg_quest_state(who, d["quest"])
            t = u"Quest “%s”: %s (now %s)" % (
                hisg_esc(hisg_quest_title(d["quest"], who)), hisg_quest_need(d["op"], d["value"]),
                "not started" if cur < 0 else ("done" if cur >= 100 else u"step %s" % cur))
            if v is False:
                link = (who, "quest", d["quest"])
        elif k == "seen":
            who = hisg_char_by_var(d["who"], char)
            if who is char and d["name"] == hisg_current_name[0]:
                if not d["want"] or v:
                    return None  # about this very scene: nothing to do
                return ("auto" if guided else "unknown"), u"This version plays when it has been seen once before", None
            t = u"%s %s “%s” %s" % (hisg_esc(who.fname), HISG_KIND_TEXT.get(d["what"], d["what"]),
                                           hisg_title(d["name"]), "seen" if d["want"] else "not seen yet")
            if v is False and d["want"]:
                link = (who, d["what"], d["name"])
            elif v is False:
                t += u" - it already happened, so the game won't start this again"
        elif k == "seen_times":
            who = hisg_char_by_var(d["who"], char)
            if who is char and d["name"] == hisg_current_name[0]:
                t = u"Seen %s before (now %s)" % (hisg_times_need(d["op"], d["value"]), hisg_seen_times(who, d["what"], d["name"]))
                return ("ok" if v else ("auto" if guided else "unknown")), t, None
            t = u"%s %s \u201c%s\u201d seen %s (now %s)" % (
                hisg_esc(who.fname), HISG_KIND_TEXT.get(d["what"], d["what"]), hisg_title(d["name"]),
                hisg_times_need(d["op"], d["value"]), hisg_seen_times(who, d["what"], d["name"]))
            if v is False:
                link = (who, d["what"], d["name"])
        elif k == "stat":
            t = hisg_stat_text(c, char)
        elif k == "cooldown":
            # Your own waiting times are kept on you, not on her.
            who = player if d["who"] == "player" else hisg_char_by_var(d["who"], char)
            if d["action"] == "anger_block":
                t = u"%s is not angry with you" % hisg_esc(who.fname)
            elif hisg_orgasm_text(d["action"], d.get("want", True)):
                t = hisg_orgasm_text(d["action"], d.get("want", True))
            elif not d.get("want", True):
                # The scene needs the waiting time to be running.
                what = hisg_action_text(d["action"], who) or hisg_esc(d["action"].replace("_", " "))
                left = hisg_cooldown_left(who, d["action"])
                if not v:
                    link = hisg_cooldown_starter(d["action"], who)
                if left is not None:
                    t = u"Only shortly after \u201c%s\u201d (%s left)" % (what, hisg_hours(left))
                else:
                    t = u"Only shortly after \u201c%s\u201d - that isn't the case now" % what
            else:
                what = hisg_action_text(d["action"], who) or hisg_esc(d["action"].replace("_", " "))
                left = hisg_cooldown_left(who, d["action"])
                if v:
                    t = u"\u201c%s\u201d is possible right now" % what
                elif left is None:
                    t = u"\u201c%s\u201d is not possible yet (the game doesn't say for how long)" % what
                elif who is player:
                    t = u"\u201c%s\u201d possible again in %s" % (what, hisg_hours(left))
                else:
                    t = u"%s: \u201c%s\u201d possible again in %s" % (hisg_esc(who.fname), what, hisg_hours(left))
        elif k == "role":
            expr = d.get("expr", "")
            role = expr.split(".")[-1].replace("_", " ")
            t = u"%s has to be the %s on duty right now" % (nm, hisg_esc(role))
            if guided and v is False:
                t = u"%s takes over as the %s" % (nm, hisg_esc(role))
                return "auto", t, None
        elif k == "item":
            t = u"You have “%s”" % hisg_esc(d["item"])
        elif "cum_in_pants()" in c.src:
            t, p = hisg_cum_text(c)
            if guided:
                return "auto", t + u" - Guided mode makes it go your way", None
            if p is not None and p >= 0.999:
                return "ok", t, None
            return "unknown", t, None
        elif v is None and _r.startswith("call") and not hisg_describe(c, char).startswith(u"Another check"):
            t = hisg_describe(c, char)
            return "unknown", t, None
        elif v is None and _r.startswith("call"):
            m = hisg_re.search(r"\.(\w+)\(", c.src)
            what = m.group(1).replace("_", " ") if m else u"how it goes"
            t = u"Decided while the scene plays (%s)" % hisg_esc(what) + hisg_engine(c)
        elif k == "other" and hisg_re.search(r"\bll?_\w+", c.src) and not hisg_re.search(r"\b[a-z]+\.ll?_", c.src):
            words = hisg_describe(c, char)
            t = (words if not words.startswith(u"Another check") else u"Decided during the scene" + hisg_engine(c))
            return ("auto" if guided else "unknown"), t, None
        else:
            t = hisg_describe(c, char)
            if k == "time" and guided and v is False:
                t += u" - ignored in Guided mode"
                return "auto", t, None
        if guided and state == "auto":
            t += u" - forced by Guided mode"
        return state, t, link

    HISG_BLOCKING = hisg.PROGRESS_KINDS + ("appointment", "presence", "invited")

    def hisg_invited_arrived(c):
        """Invited to the island, and the day she said she'd come has passed."""
        try:
            return any(x.char is c and x.gameday < gameday for x in player.chars_invited)
        except Exception:
            return None

    def hisg_appointment_ids(plan):
        try:
            return [a.id for a in gl_appointment_pool if plan.entry_return and a.action_event == plan.entry_return]
        except Exception:
            return []

    def hisg_had_appointment(char, plan, name):
        """Has she been to the appointment this one starts from (e.g. a
        poker evening, for what happens after you win)?"""
        idx = hisg_index()
        if idx is None or len(plan.hops) < 2:
            return False
        first = plan.hops[1].label
        for (kind, mname), mks in idx.markers.items():
            if kind != "appointment" or mname == name:
                continue
            if any(m.owner == first for m in mks):
                try:
                    if char.get_appointment_seen(mname):
                        return True
                except Exception:
                    pass
        return False

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

    def hisg_special_outfit_quest(char, attr):
        """The quest that gives her the special outfit (as the game checks it)."""
        if attr == "swimwear":
            item = char.fname + " swimwear"
        elif attr == "nightwear":
            item = "Heather_sexy_nurse_outfit" if char.id == heather.id else char.fname + "_nightwear"
        else:
            return None
        idx = hisg_index()
        q = idx.item_quests.get(item, item) if idx is not None else item
        try:
            if any(qp.name == q for qp in gl_quest_pool):
                return q
        except Exception:
            pass
        return None

    def hisg_outfit_missing_text(char, attr, value):
        if value == 1:
            return u" - she wears it once her affection is high enough (level 2)"
        if value == 2:
            return u" - she wears it once she is in the mood for it (tease check, level 3)"
        if value >= 3:
            if hisg_special_outfit_quest(char, attr):
                return u" - she doesn't have it yet: it comes from a quest"
            return u" - she doesn't have it yet"
        return u" - she won't wear it yet"

    def hisg_outfit_link(char, attr, value):
        if value >= 3:
            q = hisg_special_outfit_quest(char, attr)
            if q:
                return (char, "quest", q)
        return None

    def hisg_outfit_row(char, meta, plan, guided):
        """The outfit the game lists for the scene (e.g. her special dress)."""
        if meta is None or not plan.location:
            return None
        attr = hisg_wear_attr(plan.location)
        clothes = list(getattr(meta, "clothes", []) or [])
        if not attr or not clothes or sorted(clothes) == [0, 1, 2]:
            return None
        for c in plan.conds:
            if c.kind == "outfit" and c.data["attr"] == attr:
                return None  # already listed
        cur = getattr(char, attr, 0)
        names = u" or ".join(hisg_wear_name(attr, v) for v in clothes)
        t = u"%s wears her %s" % (hisg_esc(char.fname), names)
        if cur in clothes:
            return "ok", t, None
        if guided or any(hisg_outfit_allowed(char, attr, v) for v in clothes):
            return "auto", t + u" - the guide changes it", None
        v = clothes[0]
        return "bad", t + hisg_outfit_missing_text(char, attr, v), hisg_outfit_link(char, attr, v)

    def hisg_arrange_link(char, ids):
        """How the game arranges one of these appointments."""
        idx = hisg_index()
        for i in ids:
            if idx.markers_for("schedule", str(i)):
                return (char, "schedule", str(i))
        try:
            for mp in gl_message_pool:
                if getattr(mp, "appointment_pool_id", None) in ids and idx.markers_for("message", str(mp.id)):
                    return (char, "message", str(mp.id))
        except Exception:
            pass
        return None

    def hisg_pool_text(pool, i, char, attr):
        try:
            for x in pool:
                if x.id == i:
                    return hisg_esc(getattr(x, attr, "").replace("&1", char.fname).replace("&2", "her room"))
        except Exception:
            pass
        return u""

    hisg_current_name = [""]
    hisg_current_kind = [""]

    def hisg_card_data(char, kind, name):
        hisg_current_name[0] = name
        hisg_current_kind[0] = kind
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
            if meta is not None and meta.is_sexting:
                hisg_sexting_card(char, name, d, guided)
                cache[key] = d
                return d
            if meta is not None and meta.is_web_search:
                hisg_websearch_card(char, name, d, guided)
                cache[key] = d
                return d
            if meta is None:
                hisg_other_title(char, kind, name, d)

        plan = hisg_plan(char, kind, name)
        rows = []
        unmet = False
        blocked = []
        me = char
        lead = getattr(store, plan.lead, None) if getattr(plan, "lead", "") else None
        if lead is not None:
            # She is the second girl: the scene starts with the other one.
            char = lead
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
        # Scenes reached through an appointment need it arranged as well
        # (e.g. an event that happens during the photo studio session).
        ids = hisg_appointment_ids(plan) if plan.launchable else []
        had = d.get("seen") or hisg_had_appointment(char, plan, name)
        if ids and kind != "appointment" and not had:
            if hisg_appointment_arranged(char, ids):
                rows.insert(0, ("ok", u"The appointment it happens at is arranged: %s" % hisg_pool_text(gl_appointment_pool, ids[0], char, "description"), None))
            elif guided:
                rows.insert(0, ("auto", u"Happens at an appointment that is not arranged - played anyway in Guided mode", None))
            else:
                rows.insert(0, ("bad", u"Happens at an appointment that is not arranged yet: %s" % hisg_pool_text(gl_appointment_pool, ids[0], char, "description"),
                                hisg_arrange_link(char, ids)))
                blocked.append("appointment")
        if kind == "appointment" and plan.launchable:
            if not ids and plan.entry_return.startswith("do_"):
                pass  # you start it yourself (e.g. a poker game at the bar)
            elif not ids:
                rows.insert(0, ("unknown", u"Could not check whether the appointment is arranged", None))
            elif hisg_appointment_arranged(char, ids):
                rows.insert(0, ("ok", u"The appointment is arranged", None))
            elif had:
                rows.insert(0, ("ok", u"Not arranged right now, but you have had it before", None))
            elif guided:
                rows.insert(0, ("auto", u"Not arranged yet - played anyway in Guided mode", None))
            else:
                rows.insert(0, ("bad", u"Not arranged yet - the game arranges it", hisg_arrange_link(char, ids)))
                blocked.append("appointment")

        if plan.launchable and plan.pick:
            rows.insert(0, ("auto", u"%s takes part - the guide makes sure the game's draw picks her" % hisg_esc(char.fname), None))
        for value in (getattr(plan, "pick_values", []) if plan.launchable else []):
            if isinstance(value, basestring):
                what = value.replace("visit_girls_room_", "").replace("visit_", "").replace("_", " ")
                t = u"Random: the game draws what happens (“%s” is one of the options) - the guide makes it this one" % hisg_esc(what)
            else:
                t = u"Random: the game draws which version of the scene you get - the guide makes it number %s" % value
            rows.insert(0, ("auto", t, None))
        orow = hisg_outfit_row(char, meta, plan, guided)
        if orow is not None:
            rows.insert(0, orow)
            if orow[0] == "bad":
                blocked.append("outfit")

        absent = [o for o in hisg_others_involved(char, meta, plan) if not hisg_on_island(o) and o is not me]
        for other in absent:
            rows.insert(0, ("bad", u"%s is not on the island right now" % hisg_esc(other.fname), None))
        if lead is not None:
            t = u"The game starts this scene with %s, %s joins her - the guide sets it up with both of them%s" % (
                hisg_esc(lead.fname), hisg_esc(me.fname), u"" if not plan.location else u" at " + hisg_location_text(plan.location))
            if hisg_on_island(lead):
                rows.insert(0, ("auto", t, None))
            else:
                rows.insert(0, ("bad", t + u" - but %s is not on the island right now" % hisg_esc(lead.fname), None))
                blocked.append("lead")
            char = me
        d["rows"] = rows
        d["notes"].extend(plan.notes)
        if plan.location:
            d["where"] = u"Where: %s" % hisg_location_text(plan.location)
        if plan.entry_return:
            how = hisg_action_text(plan.entry_return, lead or char)
            if how:
                d["how"] = u"In the game: select %s, then \u201c%s\u201d" % (hisg_esc((lead or char).fname), how)
        if plan.skipped:
            d["notes"].append("The random trigger of this %s is skipped by the guide." % HISG_KIND_TEXT.get(kind, kind))

        # Honest mode only plays what it could check: a scene the guide has
        # to start directly (no route from the game found) is not seen as safe.
        unchecked = (plan.launchable and plan.entry == "direct" and not guided and not d.get("seen")
                     and kind in ("scene", "event", "appointment"))
        on_island = hisg_on_island(char)
        if (plan.launchable and hisg.needs_two_girls(idx, plan.target_label)
                and not hisg.chars_in_label(plan.target_label, char, store)):
            plan.launchable = False
            plan.reason = "This scene needs a second girl and the guide can't tell which one."
        if not plan.launchable:
            d["play_hint"] = plan.reason or "The guide cannot start this one."
        elif not on_island:
            d["play_hint"] = "%s is not on the island right now." % char.fname
        elif absent:
            d["play_hint"] = "%s is not on the island right now." % absent[0].fname
        elif lead is not None and not hisg_on_island(lead):
            d["play_hint"] = "%s, who this scene starts with, is not on the island right now." % lead.fname
        elif not guided and plan.location and not hisg_location_open(plan.location):
            d["play_hint"] = "%s is closed at this time of day." % hisg_location_text(plan.location).capitalize()
        elif not guided and blocked:
            d["play_hint"] = "Not all requirements are met (marked with a cross) - switch to Guided mode to play it anyway."
        elif unchecked:
            d["play_hint"] = ("The guide could not find where the game starts this, so it cannot check "
                              "the requirements above - switch to Guided mode to play it anyway.")
        else:
            d["play"] = True
            if any(r[0] == "unknown" for r in rows) and not guided:
                d["play_hint"] = "Rows marked ? are decided by chance or during the scene."
        if plan.launchable and d.get("seen"):
            d["replay"] = True
        elif plan.launchable:
            d["replay_hint"] = "Replay is available after you have seen it once."
        if kind == "message":
            d["replay"] = False
            d["replay_hint"] = ""
            d["play_label"] = "Get the message now"
            d["play_call"] = ("hisg_message_run", name)
            d["notes"].append("The game sends this message on its own when the time passes and the "
                              "conditions hold (often with a random chance). The button sends it now.")
            if not plan.marker:
                d["play"] = False
        elif kind in ("sexting", "websearch", "schedule"):
            d["replay"] = False
            d["replay_hint"] = ""
        cache[key] = d
        return d

    def hisg_other_title(char, kind, name, d):
        if kind == "sexting":
            used = char.get_sexting_times_used(int(name), False) if hasattr(char, "get_sexting_times_used") else 0
            d["title"] = u"Picture message %s" % name
            d["status"] = "Received" if used else "Not received yet"
            d["seen"] = bool(used)
            d["notes"].append("The scene below sends this picture to your phone (it arrives a little later).")
        elif kind == "websearch":
            ws = char.get_web_search(name) if hasattr(char, "get_web_search") else None
            d["title"] = u"Unlock web search: " + hisg_title(name)
            d["status"] = "Unlocked" if (ws is not None and ws.known) else "Not unlocked yet"
            d["seen"] = bool(ws is not None and ws.known)
        elif kind == "schedule":
            i = int(name)
            d["title"] = u"Arrange: " + (hisg_pool_text(gl_appointment_pool, i, char, "description") or name)
            arranged = hisg_appointment_arranged(char, [i])
            d["status"] = "Arranged" if arranged else "Not arranged yet"
        elif kind == "message":
            d["title"] = u"Message: " + (hisg_pool_text(gl_message_pool, int(name), char, "description") or name)
            d["desc"] = hisg_pool_text(gl_message_pool, int(name), char, "message_text")

    # -- picture messages and web searches --------------------------------

    def hisg_sexting_rules():
        rt = hisg.RUNTIME
        if rt.get("sexting_rules") is None:
            rt["sexting_rules"] = hisg.sexting_rules(hisg_index())
        return rt["sexting_rules"]

    def hisg_sexting_card(char, name, d, guided):
        level = int(name[8]) * 100 if len(name) > 8 and name[8].isdigit() else 0
        d["title"] = u"Picture messages (%s)" % name.replace("Sexting_", "")
        d["replay"] = False
        if level == 500:
            imgs = list(getattr(char, "images_sexting_5xx", []))
            got = len([x for x in imgs if x.times_used > 0])
            d["status"] = u"Received %s of %s" % (got, len(imgs))
            idx = hisg_index()
            for img in imgs:
                if img.times_used > 0:
                    d["rows"].append(("ok", u"Picture %s received" % img.image, None))
                else:
                    link = (char, "sexting", str(img.image)) if idx.markers_for("sexting", str(img.image)) else None
                    d["rows"].append(("bad", u"Picture %s not received yet" % img.image, link))
            d["notes"].append("These pictures are sent by particular scenes; open a missing one to see which.")
            return
        rules = hisg_sexting_rules()
        lst = list(getattr(char, "images_sexting_%sxx" % (level // 100), []))
        got = len([x for x in lst if x.times_used > 0])
        d["status"] = u"Received %s of %s" % (got, len(lst))
        nm = hisg_esc(char.fname)
        rows, bad = d["rows"], []
        def add(ok, text):
            state = "ok" if ok else ("auto" if guided else "bad")
            if guided and not ok:
                text += u" - skipped in Guided mode"
            rows.append((state, text, None))
            if not ok:
                bad.append(text)
        add(getattr(char, "active", False), u"%s can text you (she is active)" % nm)
        add(char.rsm[0].anger < 20, u"%s is not angry with you (anger below 20)" % nm)
        add(player.get_action_allowed("sexting"), u"You haven't received a picture in the last hours")
        add(char.get_action_allowed("sexting"), u"%s hasn't sent you a picture in the last days" % nm)
        cond = rules["levels"].get(level)
        if cond:
            for src, neg in hisg.atoms(cond):
                c = hisg.Cond(src, neg)
                row = hisg_cond_row(c, char, guided)
                if row is not None:
                    rows.append(row)
                    if row[0] == "bad":
                        bad.append(row[1])
        d["notes"].append("The game only sends these by chance (15% when time passes during the day) "
                          "and a few hours later; the button sends the next one now.")
        if got >= len(lst):
            d["play_hint"] = "You have all pictures of this kind."
        elif bad and not guided:
            d["play_hint"] = "Not all requirements are met (marked with a cross) - switch to Guided mode to get one anyway."
        else:
            d["play"] = True
            d["play_label"] = "Get a picture now"
            d["play_call"] = ("hisg_sexting_run", level)

    def hisg_websearch_card(char, name, d, guided):
        ws = char.get_web_search(name) if hasattr(char, "get_web_search") else None
        d["title"] = u"Web search: " + hisg_title(name)
        d["replay"] = False
        if ws is None:
            d["notes"].append("This web search is not part of your game yet.")
            return
        d["status"] = u"Found %s of %s pictures" % (ws.last_image_found, ws.number_of_images)
        rows = d["rows"]
        blocked = False
        if ws.known:
            rows.append(("ok", u"Unlocked - you can search for it", None))
        else:
            idx = hisg_index()
            link = (char, "websearch", name) if idx.markers_for("websearch", name) else None
            rows.append(("bad", u"Not unlocked yet - a scene with %s tells you about it" % hisg_esc(char.fname), link))
            blocked = True
        free = player.get_action_allowed("pl_action_read")
        if free:
            rows.append(("ok", u"You haven't searched the web or read in the last hours", None))
        elif guided:
            rows.append(("auto", u"You searched the web not long ago - skipped in Guided mode", None))
        else:
            rows.append(("bad", u"You searched the web or read not long ago - wait a bit", None))
            blocked = True
        d["notes"].append("In the game every search only finds the next picture by chance (60%, then 50%, 40%, 30%). "
                          "The guide's search always finds it.")
        if ws.last_image_found >= ws.number_of_images:
            d["play_hint"] = "You have found all pictures."
        elif blocked and not (guided and ws.known):
            d["play_hint"] = "Not all requirements are met (marked with a cross)."
        else:
            d["play"] = True
            d["play_label"] = "Search the web now"
            d["play_call"] = ("hisg_websearch_run", name)

    def hisg_send_sexting(char, level, guided):
        img = char.get_sexting_with_lowest_usage(level)
        if img is None or img.times_used > 0:
            renpy.notify("There is no new picture of this kind.")
            return
        a, b = hisg_sexting_rules()["texts"].get(level, (level, level))
        char.add_queued_sexting(img.image, renpy.random.randint(a, b), 0)
        char.check_send_queued_sexting(0)
        if not guided:
            # The same waiting times the game sets after a picture.
            char.add_action_cooldown("sexting", 96, "")
            player.add_action_cooldown("sexting", 4, "")
        renpy.notify("%s sent you a picture - look at your messages." % char.fname)

    def hisg_send_message(char, msg_id):
        """Runs the game's own statement that sends this phone message."""
        plan = hisg_plan(char, "message", msg_id)
        mk = plan.marker if plan is not None else None
        if mk is None:
            renpy.notify("The guide cannot send this message.")
            return
        src = hisg.text(getattr(mk.node.code, "source", ""))
        line = ""
        for l in src.splitlines():
            if hisg_re.search(r"(create_message|send_message|create_text_message|i_message_text)\W*\(?\s*=?\s*%s\b" % msg_id, l):
                line = l.strip()
                break
        if not line:
            renpy.notify("The guide cannot send this message.")
            return
        m = hisg_re.match(r"^(\w+)\s*=\s*(.*create_message\(.*)$", line)
        if m and "add_conversation" not in line:
            line = "player.add_conversation(%s)" % m.group(2)
        ns = dict((n, char) for n in hisg.CHAR_NAMES)
        exec(compile(line, "<scene-guide>", "exec"), store.__dict__, ns)
        renpy.notify("%s sent you a message - look at your phone." % char.fname)

    def hisg_websearch_steps():
        return hisg.random_exit_steps(hisg_index(), "pl_action_web_search_item")

    # -- special actions (flash / grope / pose) -----------------------------

    # Where a work outfit is worn: location, outfit attribute, who is on duty.
    HISG_WORK_PLACES = {"reception": ("reception", "receptionwear", "reception"),
                        "doctor": ("doctor", "doctorwear", "doctor"),
                        "restaurant_table": ("restaurant", None, None)}
    HISG_WORK_TEXT = {"reception": "at the reception desk", "doctor": "as the nurse on duty",
                      "restaurant_table": "at your restaurant table"}

    def hisg_table_of(value):
        """Her seat for the restaurant_table<value> pictures (tables 1-3, 4-6, 7-9)."""
        return (int(value) - 1) * 3 + 1 if value else 1

    def hisg_work_reason(char, info, guided):
        """Why this can't be played right now ("" when it can)."""
        if not hisg_on_island(char):
            return "%s is not on the island right now." % char.fname
        if guided:
            return ""
        group = info["work"]
        if group == "restaurant_table":
            try:
                ok = (char.get_restaurant_table() == str(info["value"]) and getattr(char, "restaurant", 0)
                      and char.locations[actions_left - 1] == "restaurant" and hisg_location_open("restaurant"))
            except Exception:
                ok = False
            if not ok:
                return "Only while she sits at your table in the restaurant (Honest mode)."
            return ""
        on_duty = getattr(jobs, info["role"], None)
        if on_duty is not char:
            return "Only while she is on duty %s - now it's %s (Honest mode)." % (
                HISG_WORK_TEXT[group].replace("as the nurse on duty", "as the nurse").replace("at the reception desk", "at the reception"),
                getattr(on_duty, "fname", "nobody"))
        if not hisg_location_open(info["location"]):
            return "%s is closed at this time of day." % hisg_location_text(info["location"]).capitalize()
        if getattr(char, info["work_attr"], None) != info["value"]:
            return "She wears a different work outfit right now (Honest mode)."
        return ""

    def hisg_temp_set(obj, attr, value):
        """Changed for this scene only (put back afterwards, see hisg_roles_restore)."""
        try:
            hisg.RUNTIME.setdefault("roles", []).append((obj, attr, getattr(obj, attr), value))
            setattr(obj, attr, value)
        except Exception:
            pass

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
        elif group in HISG_WORK_PLACES:
            # At work (reception, doctor's office) or at your restaurant table:
            # the same scenes, told where they happen.
            place, attr, role = HISG_WORK_PLACES[group]
            info["location"], info["work"], info["role"] = place, group, role
            info["work_attr"], info["value"] = attr, value
            if group == "restaurant_table":
                info["label"] = label if sa.special_type == "F" else label + "_restaurant_table"
                info["args"] = [char, "restaurant_table"] if sa.special_type == "F" else [char]
        else:
            info["reason"] = "The guide doesn't know where this one happens."
        outfit = hisg_wear_name(info["attr"], value) if info["attr"] else HISG_WORK_TEXT.get(group, group.replace("_", " "))
        if info.get("work") and info.get("work_attr"):
            outfit += u" (work outfit %s)" % (value + 1)
        info["title"] = u"%s - %s" % (tname, outfit)
        if label and info.get("work") and not info["reason"]:
            info["reason"] = hisg_work_reason(char, info, bool(persistent.hisg_guided))
            info["launchable"] = not info["reason"]
        elif label and info["location"] and not info["reason"]:
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

    HISG_PLAIN_BACKGROUND = ("doctor", "reception")

    def hisg_plain_background(loc):
        for name in ("locations/loc_%s%s_main.webp" % (loc, daytime), "locations/loc_%s_main.webp" % loc,
                     "locations/loc_%s_main.jpg" % loc):
            if renpy.loadable(name):
                return name
        return None

    def hisg_draw_background(char):
        scenes = hisg.RUNTIME.get("background") or []
        for node in reversed(scenes):
            try:
                imspec = node.imspec
                if not imspec:
                    continue
                name, expr = imspec[0], imspec[1]
                if expr:
                    img = renpy.python.py_eval(expr)
                    if isinstance(img, basestring) and not renpy.loadable(renpy.substitute(img, translate=False)):
                        continue
                elif not renpy.has_image(" ".join(name), exact=True):
                    continue
                renpy.config.scene(getattr(node, "layer", "master"))
                renpy.ast.show_imspec(imspec, atl=getattr(node, "atl", None))
                return True
            except Exception:
                continue
        return False

    HISG_OTHER_LOC_RE = hisg_re.compile(r"""(\w+)\.locations\[\s*(?:actions_left|ap)\s*-\s*(\d+)\s*\]\s*==\s*["'](\w+)["']""")

    def hisg_other_girl(name, char):
        other = getattr(store, name, None)
        if other is None or other is char or not hasattr(other, "locations") or not getattr(other, "fname", ""):
            return None
        return other

    def hisg_arrange_others(plan, char, guided):
        """
        Another girl the scene needs (Jessica at the beach in her bikini for
        the couple pose): bring her there and dress her, like the girl herself.
        Returns True when the people on screen have to be redrawn.
        """
        moved = False
        for c in plan.conds:
            if c.negated:
                continue
            d = c.data
            if c.kind == "outfit":
                other = hisg_other_girl(d.get("who", ""), char)
                if other is not None and d.get("op") == "==" and (guided or hisg_outfit_allowed(other, d["attr"], d["value"])):
                    setattr(other, d["attr"], d["value"])
                continue
            if c.kind == "char_location" and d.get("op") == "==":
                other = hisg_other_girl(d.get("who", ""), char)
                if other is not None and other in list_of_characters:
                    try:
                        other.locations[actions_left - d.get("back", 1)] = d["location"]
                        moved = True
                    except Exception:
                        pass
                continue
            m = HISG_OTHER_LOC_RE.search(c.src)
            if m:
                other = hisg_other_girl(m.group(1), char)
                if other is not None and other in list_of_characters:
                    try:
                        other.locations[actions_left - 1] = m.group(3)
                        other.locations[actions_left - int(m.group(2))] = m.group(3)
                        moved = True
                    except Exception:
                        pass
        return moved

    def hisg_set_role(expr, char):
        """jobs.doctor -> setattr(jobs, "doctor", char) for this scene."""
        try:
            parts = expr.split(".")
            obj = getattr(store, parts[0])
            for part in parts[1:-1]:
                obj = getattr(obj, part)
            # Kept for the whole scene (the game re-picks who is on duty on
            # the way, e.g. when it draws the doctor's office) and put back
            # afterwards.
            hisg.RUNTIME.setdefault("roles", []).append((obj, parts[-1], getattr(obj, parts[-1]), char))
            setattr(obj, parts[-1], char)
        except Exception:
            pass

    def hisg_roles_apply():
        for obj, attr, _old, ch in hisg.RUNTIME.get("roles") or []:
            if getattr(obj, attr, None) is not ch:
                setattr(obj, attr, ch)

    def hisg_roles_restore():
        for obj, attr, old, _ch in reversed(hisg.RUNTIME.get("roles") or []):
            try:
                setattr(obj, attr, old)
            except Exception:
                pass
        hisg.RUNTIME["roles"] = []

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
        rt["background"] = []
        hisg_pick_remove()
        hisg_roles_restore()
        rt["patcher"].restore()
        rt["highlight"].clear()
        if kind == "special":
            info = hisg_special_info(char, int(name))
            if not info["launchable"] and not replay:
                renpy.notify(info["reason"] or "This interaction cannot be started.")
                return None
            if info.get("work"):
                rebuild = hisg_setup_env(char, info["location"], None, True, guided)
                if info["role"]:
                    hisg_temp_set(jobs, info["role"], char)
                    if info["role"] == "reception":
                        hisg_temp_set(store, "g_receptionist_location", "reception")
                if info["work_attr"]:
                    hisg_temp_set(char, info["work_attr"], info["value"])
                if info["work"] == "restaurant_table" and char.get_restaurant_table() != str(info["value"]):
                    hisg_temp_set(char, "restaurant", hisg_table_of(info["value"]))
                args = info.get("args") or [char, info["location"]]
                kwargs = {"auto_succeed": guided} if len(args) > 1 else {}
                return (info["label"], args, kwargs, rebuild)
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
        me = char
        if getattr(plan, "lead", ""):
            # She is the second girl: set the scene up with the girl it
            # starts with, and bring her along.
            char = getattr(store, plan.lead)
            try:
                if plan.location:
                    me.locations[actions_left - 1] = plan.location
            except Exception:
                pass
        alone = any(c.kind == "alone" for c in plan.conds)
        rebuild = hisg_setup_env(char, plan.location, hisg_outfit_target(plan, char, meta if me is char else None), alone, guided)
        if me is not char and plan.location:
            try:
                me.locations[actions_left - 1] = plan.location  # "alone" means without other girls
            except Exception:
                pass
        for var, src in plan.preset.items():
            # As the game sets them before it starts the scene
            # (event_char = miriam, event_char2 = mercedes).
            v, _r = hisg.safe_value(src, store.__dict__, {})
            if not _r:
                setattr(store, var, v)
        if hisg_arrange_others(plan, char, guided):
            rebuild = True
        if guided:
            # The game only draws from girls whose waiting time is over.
            for c in plan.conds:
                if getattr(c, "from_pool", False) and c.kind == "cooldown" and c.data.get("want", True):
                    try:
                        char.rem_action_cooldown(c.data["action"])
                    except Exception:
                        pass
        for c in plan.conds:
            # Where she is headed next (the elevator takes her to her room).
            if (c.kind == "char_location" and c.data.get("back", 1) > 1 and c.data["op"] == "=="
                    and hisg_char_by_var(c.data["who"], char) is char):
                try:
                    char.locations[actions_left - c.data["back"]] = c.data["location"]
                except Exception:
                    pass
        if guided:
            hisg_setup_effects(plan)
            rt["patcher"].force(hisg.forceable_steps(hisg_index(), plan.steps))
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
        rt["background"] = list(getattr(plan, "background", []) or [])
        values, kwvalues = hisg.resolve_args(hisg_index(), plan, char, store)
        if guided:
            kwvalues.update(hisg.auto_succeed_kwargs(hisg_index(), plan))
        if plan.poker_win:
            hisg_poker_shortcut(True)
        picks = ([char] if plan.pick else []) + list(getattr(plan, "pick_values", []) or [])
        if picks:
            hisg_pick_install(picks)
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

    # -- poker: scenes after a won game skip the card game itself ----------

    # -- contests: the game draws who takes part; make the draw pick her ---

    def hisg_pick_install(targets):
        """
        The game's draws give what the scene needs: her (contests, the gym
        shower), the scene's number (Pool_distraction1) or the visit it is
        (visit_girls_room_shower). Each target is used once.
        """
        rng = renpy.python.rng
        rt = hisg.RUNTIME
        hisg_pick_remove()
        rt["pick_targets"] = list(targets)
        original = rng.choice

        def same_kind(a, b):
            if hisg._is_char_obj(a) or hisg._is_char_obj(b):
                return a is b
            return type(a) == type(b) and a == b

        def choice(seq):
            todo = rt.get("pick_targets") or []
            for target in list(todo):
                try:
                    for item in seq:
                        if same_kind(item, target):
                            todo.remove(target)
                            return item
                except Exception:
                    pass
            return original(seq)
        rng.choice = choice

    def hisg_pick_remove():
        rng = renpy.python.rng
        if "choice" in rng.__dict__:
            del rng.__dict__["choice"]
        hisg.RUNTIME["pick_targets"] = []

    def hisg_poker_shortcut(on):
        if on:
            config.label_overrides["poker_screen_call"] = "hisg_poker_win_call"
        else:
            config.label_overrides.pop("poker_screen_call", None)

    def hisg_label_reached(name, abnormal):
        if hisg.RUNTIME.get("roles"):
            hisg_roles_apply()
        if name == "play_poker_start" and "poker_screen_call" in config.label_overrides:
            # Your turn first, so the win comes before she plays a hand.
            try:
                store.g_poker_game.next_turn = 0
            except Exception:
                pass
        if hisg_prev_label_callback[0] is not None:
            hisg_prev_label_callback[0](name, abnormal)

    hisg_prev_label_callback = [config.label_callback]
    config.label_callback = hisg_label_reached

    def hisg_poker_round():
        """
        You win one hand: she loses up to 100 chips, so (as in the game) she
        takes off one more piece and the game shows that scene. When her
        chips are gone the game goes on with your win. Returns True then.
        """
        g = store.g_poker_game
        girl, me = g.participants[1], g.participants[0]
        take = girl.chips % 100 or min(100, girl.chips)
        girl.chips -= take
        me.chips += take + g.pot + me.bet + girl.bet
        g.pot = 0
        me.bet = girl.bet = 0
        g.next_turn = 0  # your turn again next time round
        if girl.max_undress > 0:
            hundreds = (girl.chips + 99) // 100
            girl.undress = max(1, girl.max_undress - hundreds)
        if girl.chips <= 0:
            g.out_of_chips = True
            g.winner = 0
            return True
        return False

    def hisg_finish():
        rt = hisg.RUNTIME
        run = rt["run"]
        hisg_poker_shortcut(False)
        hisg_pick_remove()
        hisg_roles_restore()
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
        if kind == "quest":
            char = hisg_quest_owner(name, char)
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
    if hisg_call[3]:
        # Moved to another place: draw it, since many scenes only show
        # the people on top of whatever is on screen.
        if location in HISG_PLAIN_BACKGROUND:
            # The game's own routine would greet us as whoever is "at" this
            # place (the doctor's office starts a scene with the nurse list).
            $ hisg_bg = hisg_plain_background(location)
            if hisg_bg:
                scene expression hisg_bg
        else:
            call main_game_background (location, location_detail, "goto_" + location) from _call_hisg_bg
    # The picture the game shows just before this part (e.g. the arrival
    # in the hallway before Desire's own lines).
    $ hisg_draw_background(hisg_char)
    # Like the game's own replay: hide the people standing around while
    # the scene plays, and redraw the location afterwards.
    $ start_scene()
    $ renpy.call(hisg_call[0], *hisg_call[1], **hisg_call[2])
    $ hisg_finish()
    $ stop_scene()
    return


label hisg_poker_win_call(l_entension, l_zoom, l_clothes_folder=""):
    # Instead of a hand of cards: you win it, and the game shows what follows.
    if hisg_poker_round():
        "The cards are on your side tonight - you win the game."
    else:
        "You win the hand."
    return "hisg_poker_win"


label hisg_sexting_run(hisg_char, hisg_level):
    $ hisg_send_sexting(hisg_char, hisg_level, bool(persistent.hisg_guided))
    $ hisg_clear_cache()
    return


label hisg_message_run(hisg_char, hisg_msg_id):
    $ hisg_send_message(hisg_char, hisg_msg_id)
    $ hisg_clear_cache()
    return


label hisg_websearch_run(hisg_char, hisg_ws_name):
    $ hisg_ws_item = hisg_char.get_web_search(hisg_ws_name)
    # The search always finds the next picture.
    $ hisg.RUNTIME["patcher"].force(hisg_websearch_steps())
    $ hisg_begin(False)
    $ start_scene()
    call pl_action_web_search_item (hisg_ws_item, hisg_char) from _call_hisg_websearch
    $ hisg_finish()
    $ stop_scene()
    if not persistent.hisg_guided:
        $ player.add_action_cooldown("pl_action_read", 8, "You did a web search not long ago.")
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

style hisg_row is default:
    padding (0, 0)
    background None
    hover_background None

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
                        if True:
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
                                $ hisg_main, hisg_sep, hisg_eng = hisg_text.partition(HISG_ENGINE_SEP)
                                if hisg_eng:
                                    # The game's own condition shows when you point at the row.
                                    button:
                                        style "hisg_row"
                                        action NullAction()
                                        tooltip "hisg:" + hisg_eng
                                        text hisg_main style "hisg_text"
                                    if GetTooltip() == "hisg:" + hisg_eng:
                                        text "In the game's script: " + hisg_eng style "hisg_small" color "#8fa0b0"
                                else:
                                    text hisg_text style "hisg_text"
                                if hisg_link is not None:
                                    textbutton "Show how to get it":
                                        style "hisg_link"
                                        action Function(hisg_goto, hisg_link[0], hisg_link[1], hisg_link[2], (hisg_char, hisg_kind, hisg_name))

                for hisg_note in hisg_d["notes"]:
                    text hisg_note style "hisg_small"

        hbox:
            spacing 8
            if hisg_d.get("play_call"):
                textbutton hisg_d.get("play_label", "Play"):
                    style "hisg_button"
                    sensitive hisg_d["play"]
                    action [Hide("hisg_card"), Call(hisg_d["play_call"][0], hisg_char, hisg_d["play_call"][1])]
            else:
                textbutton ("Play next step" if hisg_kind == "quest" else "Play"):
                    style "hisg_button"
                    sensitive hisg_d["play"]
                    action [Hide("hisg_card"), Call("hisg_run", hisg_kind, hisg_name, hisg_char, False)]
            if hisg_kind != "quest" and not hisg_d.get("play_call"):
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
