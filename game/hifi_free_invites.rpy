## Holiday Island - Free Invites (mod)
##
## Inviting girls to the island and sending them home at the reception costs
## no company favor, and the island has no maximum number of girls any more.
## The invite list lets you pick several girls, or all of them, at once.
##
## The game's script is not replaced: at start-up the mod finds the few
## statements that charge favor or check the maximum and changes them in
## memory. Saves stay compatible; removing the mod brings the game's own
## rules back.

# Sending a girl home is offered only while more than this many girls who
# can be sent home are on the island: the weekly jobs (doctor, room service,
# reception) are drawn from them and the game breaks with none left.
define HIFI_MIN_GIRLS_LEFT = 3

default hifi_last_invited = []
default hifi_invited_text = ""

init 900 python:

    import renpy.ast as hifi_ast

    HIFI_INVITE_ITEM = "Ask for a new girl to be invited to the island"
    HIFI_SEND_HOME_ITEM = "Ask for a girl to be sent home, away from the island"

    # Conditions anywhere in the script that enforce the maximum number of
    # girls (g_max_chars_on_island). Whole conditions, compared exactly.
    HIFI_MAX_CONDITIONS = {
        # add_specific_girl_to_island: the arriving girl would be turned away
        "len(list_of_characters) >= g_max_chars_on_island and i_no_max_check == False": "False",
        # add_specific_girl_to_chars_invited / invite_specific_girl_to_island
        "len(list_of_characters) + len(player.chars_invited) >= g_max_chars_on_island": "False",
        # Joy's office after 10 days: send one home before inviting
        "len(list_of_characters) < g_max_chars_on_island": "True",
        "len(list_of_characters) >= g_max_chars_on_island": "False",
    }
    # Parts of longer conditions (Amy coming back after the implant removal).
    HIFI_MAX_PARTS = {
        "len(player.chars_invited) + len(list_of_characters) <= (g_max_chars_on_island-1)": "True",
    }

    # Reception, inside the invite / send home choices.
    HIFI_INVITE = {
        "menu": ("gameday >= 10 and len(list_of_characters) < get_max_chars_on_island() and len(player.chars_invited) == 0",
                 "gameday >= 10 and len(hifi_invitable()) > 0"),
        "if": {"player.company_favor < 100": "False",
               "player.get_quest_state(\"Yvette_worry_about_sister\", yvette) == 1 and l_char_invited.char.id == yvette.id":
                   "player.get_quest_state(\"Yvette_worry_about_sister\", yvette) == 1 and yvette in hifi_last_invited"},
        "python": "player.change_company_favor(-100)",
        "say": [("if you have the necessary company favor", "Sure [jobs.reception.playername]."),
                ("will cost 100 company favor", "Inviting girls is free now, and there's no limit. You can invite as many as you like."),
                ("we will remove 100 company fav", "Here's the list of girls. Pick as many as you want."),
                ("[l_char_invited.char.fname] should arrive tomorrow", "[hifi_invited_text] should arrive tomorrow.")],
    }
    HIFI_SEND_HOME = {
        "menu_part": ("len(list_of_characters) >= 8", "hifi_can_send_home()"),
        "if": {"player.company_favor < 50": "False"},
        "python": "player.change_company_favor(-50)",
        "say": [("if you have the necessary company favor", "Sure [jobs.reception.playername]."),
                ("will cost 50 company favor", "Sending a girl home is free now."),
                ("we will remove 50 company fav", "This is the list of girls.")],
    }

    hifi_report = []

    def hifi_invitable():
        """Girls the invite list offers, filtered the way the game's list is."""
        rv = []
        invited = [i.char.fname for i in player.chars_invited]
        for c in list_of_all_characters:
            if c.is_staff_character:
                continue
            if player.get_quest_state("Yvette_worry_about_sister", c) == 1 and player.get_action_allowed("Yvette_worry_about_sister_come_back") == False:
                continue
            if player.get_quest_state("Love_max_level5_A", c) == 7:
                continue
            if c in list_of_characters or c.fname in invited:
                continue
            if c.id == player.char_send_home.id and gameday == player.char_send_home_gameday:
                continue
            rv.append(c)
        return rv

    def hifi_can_send_home():
        return len([c for c in list_of_characters if not c.is_staff_character]) > HIFI_MIN_GIRLS_LEFT

    def hifi_names(chars):
        names = [c.fname for c in chars]
        if len(names) <= 1:
            return "".join(names)
        return ", ".join(names[:-1]) + " and " + names[-1]

    def hifi_children(block):
        rv = []
        for n in block or []:
            n.get_children(rv.append)
        return rv

    def hifi_cond(c):
        return unicode(c).strip()

    def hifi_patch_ifs(nodes, mapping, parts=None, what="if"):
        for n in nodes:
            if not isinstance(n, hifi_ast.If):
                continue
            entries = []
            for c, b in n.entries:
                s = hifi_cond(c)
                if s in mapping:
                    hifi_report.append("%s:%d %s" % (n.filename, n.linenumber, what))
                    c = mapping[s]
                elif parts:
                    for old, new in parts.items():
                        if old in s:
                            hifi_report.append("%s:%d %s" % (n.filename, n.linenumber, what))
                            c = s.replace(old, new)
                entries.append((c, b))
            n.entries = entries

    def hifi_patch_python(nodes, source):
        for n in nodes:
            if isinstance(n, hifi_ast.Python) and hifi_cond(n.code.source) == source:
                code = hifi_ast.PyCode("pass", (n.filename, n.linenumber))
                code.bytecode = renpy.python.py_compile("pass", "exec")
                n.code = code
                hifi_report.append("%s:%d free" % (n.filename, n.linenumber))

    def hifi_patch_says(nodes, says):
        for n in nodes:
            if not isinstance(n, hifi_ast.Say):
                continue
            for part, new in says:
                if part in n.what:
                    n.what = new
                    hifi_report.append("%s:%d text" % (n.filename, n.linenumber))
                    break

    def hifi_patch_item(menu, i, rules):
        label, cond, block = menu.items[i]
        s = hifi_cond(cond)
        if "menu" in rules and s == rules["menu"][0]:
            cond = rules["menu"][1]
            hifi_report.append("%s:%d menu" % (menu.filename, menu.linenumber))
        elif "menu_part" in rules and rules["menu_part"][0] in s:
            cond = s.replace(*rules["menu_part"])
            hifi_report.append("%s:%d menu" % (menu.filename, menu.linenumber))
        menu.items[i] = (label, cond, block)
        nodes = hifi_children(block)
        hifi_patch_ifs(nodes, rules["if"])
        hifi_patch_python(nodes, rules["python"])
        hifi_patch_says(nodes, rules["say"])

    def hifi_patch():
        # The namemap holds every statement of the script, nested ones too.
        everything = list(renpy.game.script.namemap.values())

        hifi_patch_ifs(everything, HIFI_MAX_CONDITIONS, HIFI_MAX_PARTS, "max")

        for n in everything:
            if not isinstance(n, hifi_ast.Menu):
                continue
            for i, item in enumerate(n.items):
                if item[2] is None:
                    continue
                if item[0] == HIFI_INVITE_ITEM:
                    hifi_patch_item(n, i, HIFI_INVITE)
                elif item[0] == HIFI_SEND_HOME_ITEM:
                    hifi_patch_item(n, i, HIFI_SEND_HOME)

    hifi_patch()

    # The game's invite list takes one girl; ours takes any number.
    config.label_overrides["invite_specific_girl_to_island"] = "hifi_invite_girls"


label hifi_invite_girls(i_location, i_cancel_possible=True):
    if g_replay == True:
        return False
    $ hifi_last_invited = []
    if len(hifi_invitable()) == 0:
        return False
    call screen hifi_select_girls_to_invite(i_location, i_cancel_possible)
    if unicode(_return) == "none" or not _return:
        return False
    python:
        # Yvette last: the reception reads the last invite for her quest.
        hifi_last_invited = sorted(_return, key=lambda c: c.id == yvette.id)
        for c in hifi_last_invited:
            player.chars_invited.append(cl_char_invite(c, gameday, True))
        hifi_invited_text = hifi_names(hifi_last_invited)
    return True


screen hifi_select_girls_to_invite(l_location, i_cancel_possible):
    zorder 160
    modal True

    default picked = []
    $ chars = hifi_invitable()
    $ cols = 6 if len(chars) <= 12 else 8
    $ thumb = (140, 190) if len(chars) <= 12 else (110, 135)

    add "locations/loc_" + l_location + "_girl_selection.jpg"
    add im.Alpha("gui/loc_overlay_girl_selection.png", 0.35)

    text "{b}Select the girls you want to invite to the island!{/b}":
        xalign 0.5 yalign 0.14 size 25 outlines [(1, "#000000")] color "#66c1e0"

    vbox:
        xalign 0.5 yalign 0.50
        spacing 12
        for row in range(0, len(chars), cols):
            hbox:
                xalign 0.5
                spacing 12
                for c in chars[row:row + cols]:
                    $ pic = "phone/phone_" + c.fname + "0_hover.png"
                    button:
                        padding (0, 0)
                        background None
                        action ToggleSetMembership(picked, c)
                        tooltip c.fname
                        fixed:
                            fit_first True
                            add Transform(pic, maxsize=thumb, alpha=(1.0 if c in picked else 0.5))
                            if c in picked:
                                text u"\u2714" font "DejaVuSans.ttf" size 30 color "#7bd88f" outlines [(2, "#000000")] xalign 0.95 yalign 0.05

    $ tip = GetTooltip()
    if tip:
        text tip xalign 0.5 yalign 0.80 size 22 outlines [(1, "#000000")] color "#66c1e0"

    hbox:
        xalign 0.5 yalign 0.90
        spacing 30
        textbutton ("Invite all (%d)" % len(chars)) action Return(list(chars))
        textbutton ("Invite selected (%d)" % len(picked)):
            action Return(list(picked))
            sensitive len(picked) > 0
        textbutton "Select all" action SetScreenVariable("picked", list(chars))
        textbutton "Clear" action SetScreenVariable("picked", [])
        if i_cancel_possible:
            textbutton "Cancel" action Return("none")
