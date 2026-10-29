# -*- coding: utf-8 -*-
"""
Holiday Island - Scene Guide mod: core logic.

This module does not depend on any hand-written per-character data. It reads
the game's own script (the Ren'Py AST that is already loaded in memory) and
builds an index of:

  * every place where a scene / event / appointment gets marked as seen
    (char.add_scene_seen("Name") and friends),
  * every place where a quest is started or advanced,
  * every label call / jump, so that a path can be traced from the main game
    loop down to the statement that unlocks a scene.

For one target (e.g. Ivy's "Workout_pullups_help") it then works out:

  * which label has to be called (and with which arguments) to get there,
  * which `if` conditions and menu choices lie on the way,
  * which of those conditions are "environment" (location, outfit, being
    alone...) that the mod can set up, and which are progression (quests,
    earlier scenes, stats) that are only shown.

It runs inside Ren'Py 7.4 (Python 2.7) and under Python 3 (for offline
testing), so it avoids syntax specific to either version.
"""

from __future__ import print_function

import copy
import re
import ast as pyast

try:
    string_types = (basestring,)  # noqa: F821 (Python 2)
except NameError:  # Python 3
    string_types = (str,)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARK_RE = re.compile(r'(\w+(?:\[\w*\])?)\s*\.\s*add_(scene|event|appointment)_seen\(\s*["\']([^"\']+)["\']')
QUEST_RE = re.compile(r'player\s*\.\s*(inc_quest_state|set_quest_state|add_quest)\(([^()]*(?:\([^()]*\)[^()]*)*)\)')
LUST_RE = re.compile(r'player\s*\.\s*change_lust(?:_simple)?\(([^()]*(?:\([^()]*\)[^()]*)*)\)')
ASSIGN_RE = re.compile(r'^\s*(\w+)\s*=\s*(True|False|None|-?\d+)\s*$')
ANY_ASSIGN_RE = re.compile(r'^\s*(\w+)\s*(?:[-+*/]?=)(?!=)')
TRIGGER_RE = re.compile(r'\baction_event\s*=\s*["\'](\w+)["\']')
EVENT_CHAR_RE = re.compile(r'\bevent_char\s*=\s*([\w.]+)')
# "event_char = miriam" before a call: who the called label is about.
CHARVAR_RE = re.compile(r'^\s*(event_char\d*|char\d|selected_char)\s*=\s*([\w.]+)\s*$')
# (id(inner If), branch) -> conditions of the outer branches it sits in
GUARD_OUTER = {}

COOLDOWN_SET_RE = re.compile(r'(\w+)\s*\.\s*add_action_cooldown\(\s*["\']([^"\']+)["\']')
SCHEDULE_RE = re.compile(r'add_appointment\(\s*(\d+)\s*,')
MESSAGE_RES = (re.compile(r'(\w+)\s*\.\s*(?:create_message|send_message|create_text_message)\(\s*(\d+)'),
               re.compile(r'(\w+)\s*\.\s*add_action_cooldown\([^)]*i_message_text\s*=\s*(\d+)'))
SEXT_RE = re.compile(r'(\w+)\s*\.\s*(?:add_queued_sexting|use_sexting_image)\(\s*(\d+)')
WEBACT_RE = re.compile(r'(\w+)\s*\.\s*activate_web_search\(\s*["\']([^"\']+)["\']')
PYCALL_RE = re.compile(r'renpy\s*\.\s*(call|jump)\(\s*["\']([\w\.]+)["\']')
PYCALL_VAR_RE = re.compile(r'renpy\s*\.\s*(call|jump)\(\s*(\w+)\s*[,)]')
DYN_MARK_RE = re.compile(r'(\w+(?:\[\w*\])?)\s*\.\s*add_(scene|event|appointment)_seen\(')

WEAR_ATTRS = ("swimwear", "nightwear", "dinerwear", "receptionwear", "doctorwear")

# Character parameter names commonly used by the game's labels.
CHAR_NAMES = ("char1", "selected_char", "event_char", "i_char", "l_char", "phone_char",
              "i_girl", "char", "np_char", "l_girl", "i_char1")

# Known location ids of the game (used to read the location out of a
# main-loop action like "do_nightbar_drink").
KNOWN_LOCATIONS = ("workout", "pool", "beach", "nightbar", "massage", "reception",
                   "doctor", "restaurant", "player_room")

# The main game loop. Its callers are not followed.
MAIN_LOOP_LABEL = "test1_new"

# Character methods that are safe to call while only *looking* at a condition
# (they are called with repercussions=False, silent=True).
SAFE_CHECKS = ("check_affection", "check_love", "check_lust", "check_tease_sexual", "check_anger")
# Player checks roll dice - they are reported as a chance, never evaluated.
CHANCE_CHECKS = ("check_charm", "check_strength", "check_looks", "check_hacking",
                 "check_sneaking", "check_endurance")
SAFE_FUNCS = ("len", "int", "unicode", "str", "abs", "min", "max", "float", "bool", "get_its_raining")
STRING_METHODS = ("lower", "upper", "strip", "replace", "capitalize", "title")


def cls_name(node):
    return node.__class__.__name__


def text(s):
    """Plain text of an AST string (PyExpr is a unicode subclass)."""
    if s is None:
        return u""
    try:
        return u"" + s
    except Exception:
        return u"%s" % (s,)


def norm(src):
    """Condition source without whitespace (outside of strings), '<>' written as '!='."""
    parts = re.split(r"(\"[^\"]*\"|'[^']*')", text(src))
    return "".join(p if i % 2 else re.sub(r"\s+", "", p).replace("<>", "!=") for i, p in enumerate(parts))


def split_args(argtext):
    """Split a call argument list at top-level commas."""
    out, depth, cur, quote = [], 0, [], None
    for ch in argtext:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def call_args_at(src, pos):
    """The argument text of the call whose "(" is at src[pos]."""
    depth, quote = 0, None
    for i in range(pos, len(src)):
        ch = src[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[pos + 1:i]
    return None


def split_plus(expr):
    """Split "a" + unicode(b) + "c" at top-level plus signs."""
    out, depth, cur, quote = [], 0, [], None
    for ch in expr:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "+" and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur).strip())
    return out


def name_template(expr, rhs, depth=0):
    """
    "Pool_distraction" + unicode(l_distraction_id) -> (regex, [variables]),
    following "l_name = ..." assignments. None if it is not that simple.
    """
    expr = expr.strip()
    if re.match(r"^\w+$", expr):
        if expr in rhs and depth < 3:
            return name_template(rhs[expr], rhs, depth + 1)
        return None
    rx, names = "", []
    for part in split_plus(expr):
        lit = re.match(r'^(?:u?)["\']([^"\']*)["\']$', part)
        if lit:
            rx += re.escape(lit.group(1))
            continue
        m = re.match(r"^(?:unicode|str)\(\s*(\w+)\s*\)$", part) or re.match(r"^(\w+)$", part)
        if not m:
            return None
        rx += r"(\w+?)"
        names.append(m.group(1))
    if not names:
        return None
    return "^" + rx + "$", names


def strip_quotes(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x[0] != y[0] or x[1] is not y[1] or x[2] != y[2]:
            break
        n += 1
    return n


# ---------------------------------------------------------------------------
# A small unparser (Python 2 has no ast.unparse)
# ---------------------------------------------------------------------------

_BINOPS = {"Add": "+", "Sub": "-", "Mult": "*", "Div": "/", "Mod": "%", "FloorDiv": "//"}
_CMPOPS = {"Eq": "==", "NotEq": "!=", "Lt": "<", "LtE": "<=", "Gt": ">", "GtE": ">=",
           "In": "in", "NotIn": "not in", "Is": "is", "IsNot": "is not"}


def unparse(n):
    c = cls_name(n)
    if c == "BoolOp":
        op = " and " if cls_name(n.op) == "And" else " or "
        return op.join(_paren(v, ("BoolOp",)) for v in n.values)
    if c == "UnaryOp":
        if cls_name(n.op) == "Not":
            return "not " + _paren(n.operand, ("BoolOp", "Compare"))
        if cls_name(n.op) == "USub":
            return "-" + _paren(n.operand, ("BinOp",))
        return unparse(n.operand)
    if c == "Compare":
        s = _paren(n.left, ("BoolOp",))
        for op, right in zip(n.ops, n.comparators):
            s += " %s %s" % (_CMPOPS.get(cls_name(op), "?"), _paren(right, ("BoolOp",)))
        return s
    if c == "BinOp":
        # Keep (a + b) % 3 apart from a + b % 3.
        prec = _binop_prec(n)
        left = unparse(n.left)
        if cls_name(n.left) in ("BoolOp", "Compare", "UnaryOp") or \
                (cls_name(n.left) == "BinOp" and _binop_prec(n.left) < prec):
            left = "(%s)" % left
        return "%s %s %s" % (left, _BINOPS.get(cls_name(n.op), "?"),
                             _paren(n.right, ("BoolOp", "Compare", "BinOp")))
    if c == "Call":
        args = [unparse(a) for a in n.args]
        args += ["%s=%s" % (k.arg, unparse(k.value)) for k in n.keywords]
        return "%s(%s)" % (unparse(n.func), ", ".join(args))
    if c == "Attribute":
        return "%s.%s" % (unparse(n.value), n.attr)
    if c == "Name":
        return n.id
    if c == "Num":
        return repr(n.n)
    if c == "Str":
        return '"%s"' % n.s
    if c == "Constant":
        if isinstance(n.value, string_types):
            return '"%s"' % n.value
        return repr(n.value)
    if c == "NameConstant":
        return repr(n.value)
    if c == "Subscript":
        sl = n.slice
        if cls_name(sl) == "Index":
            sl = sl.value
        return "%s[%s]" % (unparse(n.value), unparse(sl))
    if c in ("List", "Tuple"):
        inner = ", ".join(unparse(e) for e in n.elts)
        return "[%s]" % inner if c == "List" else "(%s)" % inner
    return "?"


def _binop_prec(n):
    return {"Add": 1, "Sub": 1, "Mult": 2, "Div": 2, "Mod": 2, "FloorDiv": 2, "Pow": 3}.get(cls_name(n.op), 0)


def _paren(n, kinds):
    s = unparse(n)
    if cls_name(n) in kinds:
        return "(%s)" % s
    return s


def atoms(src, negated=False):
    """
    Splits a condition into atoms that must all hold.

    `a and b` gives [a, b]; `not (a or b)` gives [not a, not b].
    Returns [(source, negated)].
    """
    try:
        tree = pyast.parse(text(src).replace("<>", "!="), mode="eval").body
    except SyntaxError:
        return [(text(src), negated)]
    return _atoms(tree, negated)


def _atoms(node, negated):
    c = cls_name(node)
    if c == "UnaryOp" and cls_name(node.op) == "Not":
        return _atoms(node.operand, not negated)
    if c == "BoolOp":
        is_and = cls_name(node.op) == "And"
        if is_and != negated:  # "a and b", or "not (a or b)"
            out = []
            for v in node.values:
                out.extend(_atoms(v, negated))
            return out
    return [(unparse(node), negated)]


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

class Marker(object):
    """A statement that unlocks something (scene seen, quest advanced...)."""

    def __init__(self, kind, name, subject, owner, entry, path, relpath, node, value=None, op=None):
        self.kind = kind          # scene / event / appointment / quest
        self.name = name          # scene name or quest name
        self.subject = subject    # variable the call was made on (char1, ivy...)
        self.owner = owner        # top level label containing the statement
        self.entry = entry        # nearest label before it (may be nested)
        self.path = path          # steps from the owner label
        self.relpath = relpath    # steps from the entry label
        self.node = node
        self.value = value        # quest: new state or None for "+1"
        self.op = op              # quest: "add", "inc" or "set"
        self.dyn = {}             # name built at run time: variable -> value

    def __repr__(self):
        return "<Marker %s %s in %s>" % (self.kind, self.name, self.entry)


class Edge(object):
    """A call, jump or fall-through from one label to another."""

    def __init__(self, target, caller, path, args, how="call", expr=None, node=None):
        self.target = target      # label name
        self.caller = caller      # label (top level or nested) of the call site
        self.path = path          # steps from `caller` to the call site
        self.args = args          # list of argument source strings
        self.how = how            # call / jump / fall / python
        self.expr = expr          # "call expression": the expression
        self.node = node
        self.charvars = {}        # character variables set before the call
        self.pick_value = None    # label drawn from a list (renpy.call(l_call))
        self.scenes = []          # Scene statements shown just before it


class Index(object):

    def __init__(self):
        self.labels = {}          # every label name -> Label node
        self.top = set()          # top level label names
        self.params = {}          # label name -> [(param, default)]
        self.markers = {}         # (kind, name) -> [Marker]
        self.callers = {}         # label name -> [Edge]
        self.expr_edges = []      # [Edge] with expr set
        self.main_loop_idle = set()   # node names of "call screen main_game"
        self.dispatch = {}        # main loop action -> Edge
        self.node_assigns = {}    # id(If/Menu node) -> flags set before it
        self.node_lust = {}       # id(If/Menu node) -> player lust changes before it
        self.node_owner = {}      # id(If/Menu node) -> top level label
        self.label_locals = {}    # top level label -> names it assigns
        self.cooldown_setters = {}  # waiting time name -> labels that start it
        self.cooldown_sites = {}    # waiting time name -> [(top level label, path)] where it starts
        self.item_quests = {}     # quest item name -> quest it belongs to
        self.dyn_markers = []     # Marker with a name built while the game runs
        self.flag_setters = {}    # (top level label, local flag) -> [(value source, path)]
        self.top_of = {}          # label (nested too) -> its top level label
        self.callees = {}         # top level label -> labels it calls
        self.statement_count = 0

    # -- building ----------------------------------------------------------

    def build(self, namemap):
        labels = {}
        for key, node in namemap.items():
            if not isinstance(key, string_types) or cls_name(node) != "Label":
                continue
            if key.startswith("_"):
                continue
            labels[key] = node
        self.labels = labels

        nested = set()
        for name, node in labels.items():
            self._collect_nested(node.block, nested)
        self.top = set(n for n in labels if n not in nested)
        for name in labels:
            self.params[name] = self._params(labels[name])

        for name in self.top:
            ctx = {"owner": name, "entry": name, "entry_path": (),
                   "assigns": {}, "unstable": set(), "created": [], "snapshots": [],
                   "lust": (), "all_assigned": set(), "charvars": {}, "scenes": [],
                   "rhs": {}, "appends": {}}
            self._ctx = ctx
            self._walk(labels[name].block, ctx, ())
            # Variables changed while the label runs (counters...) cannot
            # be known in advance.
            self.label_locals[name] = set(ctx["unstable"]) | set(ctx["all_assigned"])
            for obj in ctx["created"]:
                for var in ctx["unstable"]:
                    obj.assigns.pop(var, None)
            for snap in ctx["snapshots"]:
                for var in ctx["unstable"]:
                    snap.pop(var, None)
        self._ctx = None

        for name in self.top:
            self.top_of[name] = name
        for target, edges in self.callers.items():
            for e in edges:
                if e.how == "call" and target:
                    lst = self.callees.setdefault(self.top_of.get(e.caller, e.caller), [])
                    if target not in lst:
                        lst.append(target)

        # Items that are really the state of a quest
        # (get_display_quest_item: "Amy_nightwear" -> "Affection_max_level5_A").
        self.item_quests = {}
        self.init_sources = []
        for node in namemap.values():
            if cls_name(node) not in ("Python", "EarlyPython"):
                continue
            src = _python_source(node)
            if "def " in src:
                self.init_sources.append(src)
            if "def get_display_quest_item" not in src:
                continue
            for m in re.finditer(r'l_quest\.name\s*==\s*["\']([^"\']+)["\']\s+and\s+i_name\s*==\s*["\']([^"\']+)["\']', src):
                self.item_quests.setdefault(m.group(2), m.group(1))

        # Main loop actions: "do_workout_pullups" -> call edge.
        self.dispatch = {}
        for edges in self.callers.values():
            for e in edges:
                if e.caller != MAIN_LOOP_LABEL or e.how != "call":
                    continue
                for st in e.path:
                    for src, negated in step_conditions(st):
                        if negated:
                            continue
                        for m in re.finditer(r'_return\s*==\s*["\'](\w+)["\']', src):
                            self.dispatch.setdefault(m.group(1), e)
        return self

    def _collect_nested(self, block, nested):
        for node in block or []:
            if cls_name(node) == "Label":
                nested.add(text(node.name))
            for sub in self._sub_blocks(node):
                self._collect_nested(sub, nested)

    @staticmethod
    def _sub_blocks(node):
        c = cls_name(node)
        if c == "If":
            return [b for _c, b in node.entries]
        if c == "Menu":
            return [it[2] for it in node.items if it[2] is not None]
        blk = getattr(node, "block", None)
        if isinstance(blk, list):
            return [blk]
        return []

    @staticmethod
    def _params(label):
        p = getattr(label, "parameters", None)
        if p is None:
            return []
        out = []
        for name, default in getattr(p, "parameters", None) or []:
            out.append((text(name), None if default is None else text(default)))
        return out

    @staticmethod
    def _rel(ctx, path):
        base = ctx["entry_path"]
        return path[common_prefix(path, base):]

    @classmethod
    def _terminal(cls, node):
        """Does control never continue after this statement?"""
        c = cls_name(node)
        if c in ("Jump", "Return"):
            return True
        if c == "If":
            has_else = any(text(cond).strip() == "True" for cond, _b in node.entries)
            return has_else and all(b and cls._terminal(b[-1]) for _c, b in node.entries)
        if c == "Menu":
            blocks = [it[2] for it in node.items if it[2] is not None]
            return bool(blocks) and all(b and cls._terminal(b[-1]) for b in blocks)
        return False

    def _walk(self, block, ctx, path):
        prev = None
        saved_assigns = ctx["assigns"]
        saved_lust = ctx["lust"]
        saved_charvars = ctx["charvars"]
        ctx["assigns"] = dict(saved_assigns)
        ctx["charvars"] = dict(saved_charvars)
        for node in block or []:
            self.statement_count += 1
            c = cls_name(node)
            if c in ("If", "Menu", "While"):
                # Flags as they are when this condition is checked.
                snap = dict(ctx["assigns"])
                self.node_assigns[id(node)] = snap
                self.node_owner[id(node)] = ctx["owner"]
                self.node_lust[id(node)] = ctx["lust"]
                ctx["snapshots"].append(snap)
            if c == "If":
                for i, entry in enumerate(node.entries):
                    self._cond_markers(text(entry[0]), node, ctx, path + (("if", node, i),))
                    self._walk(entry[1], ctx, path + (("if", node, i),))
            elif c == "While":
                self._walk(node.block, ctx, path + (("while", node, 0),))
            elif c == "Menu":
                for i, item in enumerate(node.items):
                    if item[2] is not None:
                        self._walk(item[2], ctx, path + (("menu", node, i),))
            elif c == "Label":
                name = text(node.name)
                if not name.startswith("_"):
                    # Reaching this label by simply running on from above.
                    if prev is None or not self._terminal(prev):
                        self._add_edge(Edge(name, ctx["entry"], self._rel(ctx, path), [], how="fall"))
                    ctx["entry"] = name
                    self.top_of[name] = ctx["owner"]
                    ctx["entry_path"] = path
                self._walk(node.block, ctx, path)
            elif c in ("Python", "EarlyPython"):
                self._scan_python(node, ctx, path)
            elif c == "Scene":
                # The last backgrounds shown before a call: a called label
                # often only adds to what its caller put on screen.
                ctx["scenes"] = (ctx.get("scenes") or [])[-3:] + [node]
            elif c == "Call":
                args = self._call_args(node)
                rel = self._rel(ctx, path)
                if getattr(node, "expression", False):
                    edge = Edge(None, ctx["entry"], rel, args, expr=text(node.label), node=node)
                    edge.scenes = list(ctx.get("scenes") or [])
                    self.expr_edges.append(self._remember(edge))
                else:
                    edge = Edge(text(node.label), ctx["entry"], rel, args, node=node)
                    edge.scenes = list(ctx.get("scenes") or [])
                    self._add_edge(edge)
            elif c == "Jump":
                if not getattr(node, "expression", False):
                    self._add_edge(Edge(text(node.target), ctx["entry"], self._rel(ctx, path), [],
                                        how="jump", node=node))
            elif c == "UserStatement":
                line = text(getattr(node, "line", ""))
                if ctx["owner"] == MAIN_LOOP_LABEL and line.replace(" ", "").startswith("callscreenmain_game"):
                    self.main_loop_idle.add(node.name)
            else:
                blk = getattr(node, "block", None)
                if isinstance(blk, list):
                    self._walk(blk, ctx, path)
            if c == "If":
                # Branches that leave (return / jump) must not be taken by
                # anything that comes after this statement.
                path = path + self._guards(node)
            elif c == "Menu":
                # "Ignore her" leaves, "Spy on her" goes on: what comes
                # after the menu needs the one choice that goes on.
                stay = [i for i, it in enumerate(node.items)
                        if it[2] is not None and not (it[2] and self._terminal(it[2][-1]))]
                if len(stay) == 1 and len([it for it in node.items if it[2] is not None]) > 1:
                    path = path + (("menu", node, stay[0]),)
            if c not in ("Translate", "EndTranslate") and not (c == "Label" and text(node.name).startswith("_")):
                prev = node
        # Values set inside a block are not known after it.
        ctx["pending_trigger"] = None
        ctx["assigns"] = saved_assigns
        ctx["lust"] = saved_lust
        ctx["charvars"] = saved_charvars

    def _cond_markers(self, src, node, ctx, path):
        """if player.add_quest("Aly_breast_development", aly, aly): - a quest
        started by the condition itself."""
        if "add_quest(" not in src and "_seen(" not in src:
            return
        rel = self._rel(ctx, path)
        for m in QUEST_RE.finditer(src):
            args = split_args(m.group(2))
            if m.group(1) != "add_quest" or not args or strip_quotes(args[0]) == args[0].strip():
                continue
            about = args[2] if len(args) > 2 else (args[1] if len(args) > 1 else "")
            self.markers.setdefault(("quest", strip_quotes(args[0])), []).append(self._remember(
                Marker("quest", strip_quotes(args[0]), about, ctx["owner"], ctx["entry"], path, rel, node, value=0, op="add")))
        for m in MARK_RE.finditer(src):
            self.markers.setdefault((m.group(2), m.group(3)), []).append(self._remember(
                Marker(m.group(2), m.group(3), m.group(1), ctx["owner"], ctx["entry"], path, rel, node)))

    def _guards(self, node, outer=(), depth=0):
        """
        Branches that leave the label (return / jump). Also the ones inside
        a branch that does not leave: "if no_checks == False:" with the
        cooldown / anger / affection checks inside. Those remember the
        outer condition (GUARD_OUTER) so a plan can tell whether it applies.
        """
        out = []
        for i, (cond, blk) in enumerate(node.entries):
            src = text(cond).strip()
            if src == "True" and not outer:
                if blk and not self._terminal(blk[-1]) and depth < 2:
                    out.extend(self._inner_guards(blk, outer + ("__else__",), depth))
                elif blk and i > 0 and any(b and not self._terminal(b[-1]) for _c, b in node.entries[:i]):
                    # if A: ... elif roll: ... else: leave - one of them must be true
                    out.append(("elseguard", node, i))
                continue
            if blk and self._terminal(blk[-1]):
                if src != "True":
                    out.append(("guard", node, i))
                    if outer:
                        GUARD_OUTER[(id(node), i)] = outer
            elif blk and depth < 2:
                out.extend(self._inner_guards(blk, outer + (src,), depth))
        return tuple(out)

    def _inner_guards(self, blk, outer, depth):
        out = []
        for st in blk:
            if cls_name(st) == "If":
                out.extend(self._guards(st, outer, depth + 1))
        return out

    def _remember(self, obj):
        ctx = getattr(self, "_ctx", None)
        obj.assigns = dict(ctx["assigns"]) if ctx else {}
        obj.lust = ctx["lust"] if ctx else ()
        if ctx:
            ctx["created"].append(obj)
        return obj

    def _add_edge(self, edge):
        if getattr(self, "_ctx", None) is not None and edge.how in ("call", "jump"):
            edge.charvars = dict(self._ctx.get("charvars", {}))
        self._remember(edge)
        self.callers.setdefault(edge.target, []).append(edge)

    @staticmethod
    def _call_args(node):
        a = getattr(node, "arguments", None)
        if a is None:
            return []
        out = []
        for name, expr in getattr(a, "arguments", None) or []:
            if name:
                out.append(u"%s=%s" % (text(name), text(expr)))
            else:
                out.append(text(expr))
        return out

    def _scan_python(self, node, ctx, path):
        code = getattr(node, "code", None)
        src = text(getattr(code, "source", code))
        if not src:
            return
        rel = self._rel(ctx, path)
        owner, entry = ctx["owner"], ctx["entry"]
        for m in COOLDOWN_SET_RE.finditer(src):
            lst = self.cooldown_setters.setdefault(m.group(2), [])
            if owner not in lst:
                lst.append(owner)
            self.cooldown_sites.setdefault(m.group(2), []).append((owner, path))
        for line in src.splitlines():
            m = re.match(r"^\s*(\w+)\s*=(?!=)\s*(.+?)\s*$", line)
            if m:
                ctx["rhs"][m.group(1)] = m.group(2)
                if FLAG_NAME_RE.match(m.group(1)):
                    self.flag_setters.setdefault((owner, m.group(1)), []).append((m.group(2), path))
            m = re.match(r"""^\s*(\w+)\s*\.\s*append\(\s*["'](\w+)["']\s*\)\s*$""", line)
            if m:
                ctx["appends"].setdefault(m.group(1), []).append((m.group(2), entry, rel))
        for m in MARK_RE.finditer(src):
            subj, kind, name = m.group(1), m.group(2), m.group(3)
            self.markers.setdefault((kind, name), []).append(self._remember(
                Marker(kind, name, subj, owner, entry, path, rel, node)))
        for m in DYN_MARK_RE.finditer(src):
            # add_event_seen("Pool_distraction" + unicode(l_distraction_id))
            args = split_args(call_args_at(src, m.end() - 1) or "")
            if not args or re.match(r"""^["'][^"']*["']$""", args[0]):
                continue
            tpl = name_template(args[0], ctx["rhs"])
            if tpl is None:
                continue
            mk = self._remember(Marker(m.group(2), tpl[0], m.group(1), owner, entry, path, rel, node))
            mk.dyn_vars, mk.dyn_src = [], {}
            for var in tpl[1]:
                seen = 0
                while var in ctx["rhs"] and re.match(r"^\w+$", ctx["rhs"][var]) and seen < 3:
                    var, seen = ctx["rhs"][var], seen + 1  # l_set = i_set
                mk.dyn_vars.append(var)
                mk.dyn_src[var] = ctx["rhs"].get(var)
            self.dyn_markers.append(mk)
        for m in PYCALL_VAR_RE.finditer(src):
            # l_call = renpy.random.choice(l_list) ... renpy.call(l_call, char1):
            # one route to each label put on the list.
            args = split_args(call_args_at(src, src.index("(", m.start())) or "")
            pm = re.match(r"^renpy\.random\.choice\(\s*(\w+)\s*\)$", ctx["rhs"].get(m.group(2), ""))
            if not args or not pm:
                continue
            for label, a_entry, a_rel in ctx["appends"].get(pm.group(1), []):
                if a_entry != entry:
                    continue
                edge = Edge(label, entry, tuple(a_rel) + tuple(rel), args[1:], how="call", node=node)
                edge.pick_value = label
                edge.scenes = list(ctx.get("scenes") or [])
                self._add_edge(edge)
        for m in SEXT_RE.finditer(src):
            # A picture message: the scene that queues it "unlocks" it.
            self.markers.setdefault(("sexting", m.group(2)), []).append(self._remember(
                Marker("sexting", m.group(2), m.group(1), owner, entry, path, rel, node)))
        for m in SCHEDULE_RE.finditer(src):
            # An appointment being arranged (player.add_appointment(N, ...)),
            # about the girl it is made with.
            args = split_args(call_args_at(src, src.index("(", m.start())) or "")
            mk = Marker("schedule", m.group(1), args[1] if len(args) > 1 else "", owner, entry, path, rel, node)
            mk.args = args
            self.markers.setdefault(("schedule", m.group(1)), []).append(self._remember(mk))
        for rx in MESSAGE_RES:
            for m in rx.finditer(src):
                # A phone message being sent; some of them arrange appointments.
                self.markers.setdefault(("message", m.group(2)), []).append(self._remember(
                    Marker("message", m.group(2), m.group(1), owner, entry, path, rel, node)))
        for m in WEBACT_RE.finditer(src):
            self.markers.setdefault(("websearch", m.group(2)), []).append(self._remember(
                Marker("websearch", m.group(2), m.group(1), owner, entry, path, rel, node)))
        for m in QUEST_RE.finditer(src):
            func, args = m.group(1), split_args(m.group(2))
            if not args:
                continue
            qname = strip_quotes(args[0])
            mt = re.match(r"""^(\w+)\.fname\s*\+\s*["']([^"']+)["']$""", args[0].strip())
            if mt and func == "add_quest":
                # add_quest(char1.fname + " swimwear", ...): "Amy swimwear" for Amy.
                about = args[2] if len(args) > 2 else (args[1] if len(args) > 1 else "")
                mk = self._remember(Marker("quest", "^(\\w+)" + re.escape(mt.group(2)) + "$", about, owner, entry,
                                           path, rel, node, value=0, op="add"))
                mk.dyn_vars, mk.dyn_src, mk.quest_fname = [], {}, mt.group(1)
                self.dyn_markers.append(mk)
                continue
            if qname == args[0].strip():
                # add_quest(l_quest.name, ...) under if l_quest.name == "Brenda_photo_studio":
                qname = None
                for st in reversed(path):
                    if st[0] != "if":
                        continue
                    mq = re.search(r"%s\s*==\s*[\"']([^\"']+)[\"']" % re.escape(args[0].strip()), text(st[1].entries[st[2]][0]))
                    if mq:
                        qname = mq.group(1)
                        break
                if qname is None:
                    continue
            value, op = None, "inc"
            if func == "add_quest":
                about = args[2] if len(args) > 2 else (args[1] if len(args) > 1 else "")
                value, op = 0, "add"
            elif func == "inc_quest_state":
                about = args[1] if len(args) > 1 else ""
            else:
                about, op = (args[1] if len(args) > 1 else ""), "set"
                if len(args) > 2:
                    try:
                        value = int(args[2])
                    except ValueError:
                        value = None
            self.markers.setdefault(("quest", qname), []).append(self._remember(
                Marker("quest", qname, about, owner, entry, path, rel, node, value=value, op=op)))
        for m in PYCALL_RE.finditer(src):
            # renpy.call("label", ...) inside Python: arguments are unknown.
            self._add_edge(Edge(m.group(2), entry, rel, [], how="python", node=node))
        # Player lust changes (they can give an erection during the scene).
        for m in LUST_RE.finditer(src):
            args = split_args(m.group(1))
            if args:
                ctx["lust"] = ctx["lust"] + (args[0],)
        # Events started by the main loop: action_event = "event_x" (often
        # followed by event_char = amy).
        for m in TRIGGER_RE.finditer(src):
            mk = self._remember(Marker("trigger", m.group(1), "", owner, entry, path, rel, node))
            # Set just before ("event_char = amy"), or None if not known.
            mk.event_char = ctx["charvars"].get("event_char")
            self.markers.setdefault(("trigger", m.group(1)), []).append(mk)
            ctx["pending_trigger"] = mk
        m = EVENT_CHAR_RE.search(src)
        if m and ctx.get("pending_trigger") is not None:
            if ctx["pending_trigger"].event_char is None:
                ctx["pending_trigger"].event_char = m.group(1)
        # Simple flags like "option11 = True" set before a menu.
        for line in src.splitlines():
            m = CHARVAR_RE.match(line)
            if m:
                ctx["charvars"][m.group(1)] = m.group(2)
            else:
                m = ANY_ASSIGN_RE.match(line)
                if m:
                    ctx["charvars"].pop(m.group(1), None)
            m = ASSIGN_RE.match(line)
            if m:
                ctx["assigns"][m.group(1)] = m.group(2)
                ctx["all_assigned"].add(m.group(1))
                continue
            m = ANY_ASSIGN_RE.match(line)
            if m:
                ctx["unstable"].add(m.group(1))

    # -- queries -------------------------------------------------------------

    def markers_for(self, kind, name):
        found = list(self.markers.get((kind, name), []))
        if found:
            return found
        # Names put together while the game runs ("Clothes" + unicode(i_clothes)
        # + "_show_posing"): the value each part must have.
        for mk in self.dyn_markers:
            if mk.kind != kind:
                continue
            m = re.match(mk.name, name)
            if not m:
                continue
            clone = copy.copy(mk)
            clone.name = name
            clone.dyn = dict(zip(mk.dyn_vars, m.groups()))
            found.append(clone)
        return found


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

# Values a scene keeps for itself while it runs: l_tease, lo_x, option3.
FLAG_NAME_RE = re.compile(r"^(?:l_|lo_|ll_)\w+$|^option\d+$")
PLAIN_WORDS = set(["True", "False", "None", "not", "and", "or", "in", "is"])

def common_steps(a, b):
    """How many steps two paths share from the start."""
    n = 0
    for x, y in zip(a, b):
        if x[0] != y[0] or x[1] is not y[1] or x[2] != y[2]:
            break
        n += 1
    return n


def can_mark(index, kind, name, char, store):
    """Does the game ever mark this scene seen for her (not only for other girls)?"""
    cache = index.__dict__.setdefault("_can_mark", {})
    key = (kind, name, getattr(char, "fname", ""))
    if key not in cache:
        cache[key] = any(subject_ok(m, char, store, index) and not other_char_label(m.owner, char, store)
                         for m in index.markers_for(kind, name))
    return cache[key]


def step_conditions(step):
    """
    Conditions that must hold to take one step of a path.

    Returns [(source, negated)]. For an `elif` the earlier branches must be
    false, so they are returned with negated=True. Menu steps also return
    the caption, marked with negated=None.
    """
    kind, node, idx = step
    out = []
    if kind == "if":
        for j in range(idx):
            out.append((text(node.entries[j][0]), True))
        cond = text(node.entries[idx][0])
        if cond.strip() != "True":
            out.append((cond, False))
    elif kind == "menu":
        out.append((text(node.items[idx][0]), None))
        cond = text(node.items[idx][1])
        if cond.strip() != "True":
            out.append((cond, False))
    elif kind == "while":
        out.append((text(node.condition), False))
    elif kind == "guard":
        out.append((text(node.entries[idx][0]), True))
    elif kind == "elseguard":
        alts = [text(c) for c, b in node.entries[:idx] if b and not Index._terminal(b[-1])]
        if alts:
            out.append((" or ".join("(%s)" % a if len(alts) > 1 else a for a in alts), False))
    return out


def path_conds(steps):
    conds = []
    for st in steps:
        outer = GUARD_OUTER.get((id(st[1]), st[2])) if st[0] == "guard" else None
        for src, negated in step_conditions(st):
            if negated is None:
                conds.append(Cond(src, kind="choice", step=st))
                continue
            for a, neg in atoms(src, negated):
                c = Cond(a, neg, step=st)
                if outer:
                    c.outer = outer
                conds.append(c)
    return conds


def drop_unreachable_guards(conds, global_ns, local_ns):
    """
    A check nested in "if no_checks == False:" only applies when that outer
    condition holds. Keep it when it does (or can't be told), drop it when
    the outer condition is false for this route.
    """
    out = []
    for c in conds:
        outer = getattr(c, "outer", None)
        if outer:
            live = True
            for src in outer:
                if src == "__else__":
                    continue
                v, _r = safe_eval(src, global_ns, local_ns)
                if v is False:
                    live = False
                    break
            if not live:
                continue
        out.append(c)
    return out


def _step_key(st):
    return (st[0], id(st[1]), st[2])


def _cond_names(src):
    return set(re.findall(r"(?<![.\w])([A-Za-z_]\w*)", re.sub(r"\"[^\"]*\"|'[^']*'", "", text(src)))) - PLAIN_WORDS


LITERAL_RE = re.compile(r"""^(True|False|None|-?\d+(\.\d+)?|u?"[^"]*"|u?'[^']*')$""")


def _flag_route(setter_path, route_keys, route_branch):
    """
    The steps of the way to a flag's setter that the route does not take
    already, or None when the setter lies on another branch of an if the
    route goes through (menus may be gone through again, ifs not).
    """
    extra = []
    for st in setter_path:
        if st[0] not in ("if", "menu", "while"):
            continue
        if _step_key(st) in route_keys:
            continue
        if st[0] == "if" and route_branch.get(id(st[1]), st[2]) != st[2]:
            return None
        extra.append(st)
    return extra


def _flag_owners(index, plan, owner):
    """Labels whose flags the scene reads: its own, the ones it calls, the route."""
    out = [owner]
    for name in index.callees.get(owner, ()):
        if name not in out:
            out.append(name)
    for hop in plan.hops:
        top = index.top_of.get(hop.label, hop.label)
        if top not in out:
            out.append(top)
    return out


def _expand_one(index, c, owners, route_keys, route_branch):
    """
    One condition on a single flag. Returns "start" when it holds from the
    start of the scene, None when nothing sets it, else (score, extra steps,
    condition source that replaces it or None).
    """
    names = _cond_names(c.src)
    if len(names) > 1:
        # option1 == False and option2 == False: each of them.
        parts = atoms(c.src, c.negated)
        if len(parts) < 2:
            return None
        total, steps, subs = 0, [], []
        for a, neg in parts:
            r = _expand_one(index, Cond(a, neg, step=c.step), owners, route_keys, route_branch)
            if r is None:
                return None
            if r == "start":
                continue
            total += r[0]
            steps.extend(st for st in r[1] if st not in steps)
            if r[2]:
                subs.append("(%s)" % r[2])
        if not steps and not subs:
            return "start"
        return (total, steps, " and ".join(subs) or None)
    if len(names) != 1:
        return None
    var = list(names)[0]
    best = None
    for owner in owners:
        for rhs, spath in index.flag_setters.get((owner, var), []):
            extra = _flag_route(spath, route_keys, route_branch)
            if extra is None:
                continue
            if rhs.strip()[:1] in "[({":
                continue  # a list the scene fills
            if LITERAL_RE.match(rhs.strip()):
                ok = safe_eval(c.expr, {}, {var: safe_value(rhs, {}, {})[0]})[0]
                if ok is not True:
                    continue
                if not extra and owner == owners[0]:
                    return "start"
                expr = None
            else:
                # l_horny = char1.check_lust(3): the check itself.
                expr = re.sub(r"(?<![.\w])%s\b" % re.escape(var), "(%s)" % rhs, c.expr)
            score = len(extra) + (0 if any(st[0] == "menu" for st in extra) else 1)
            if best is None or score < best[0]:
                best = (score, extra, expr)
        if best is not None:
            break
    return best


def expand_flags(index, plan, global_ns):
    """
    Conditions on a value the scene sets for itself (l_tease == True,
    option3, l_horny) become what sets it: the choice to make earlier in
    the scene, or the check that decides it. A flag that already holds
    from the start of the scene is left out.
    """
    route_keys = set(_step_key(st) for st in plan.steps)
    route_branch = dict((id(st[1]), st[2]) for st in plan.steps if st[0] == "if")
    out, added = [], []
    for c in plan.conds:
        names = _cond_names(c.src)
        flags = [n for n in names if FLAG_NAME_RE.match(n)]
        if c.kind == "choice" or not flags or c.step is None:
            out.append(c)
            continue
        owner = index.node_owner.get(id(c.step[1]))
        owners = _flag_owners(index, plan, owner)
        if names - set(flags):
            # l_auto_succeed == False and char1.check_affection(1) == False:
            # a flag that only ever gets one value is that value.
            src = c.src
            for var in flags:
                sets = index.flag_setters.get((owner, var), [])
                if sets and len(set(r for r, _p in sets)) == 1 and \
                        (LITERAL_RE.match(sets[0][0].strip()) or re.match(r"^[A-Za-z_]\w*$", sets[0][0].strip())):
                    src = re.sub(r"(?<![.\w])%s\b" % re.escape(var), "(%s)" % sets[0][0], src)
            out.append(_carry(Cond(src, c.negated, step=c.step), c) if src != c.src else c)
            continue
        if len(flags) == 1:
            alts = [c]
        else:
            # not l_option3 or not l_option4: one of them is enough.
            alts = [Cond(a, neg, step=c.step) for a, neg in atoms(c.src, not c.negated)]
            alts = [Cond(a.src, not a.negated, step=c.step) for a in alts]
            if len(alts) < 2:
                out.append(c)
                continue
        best = None
        for alt in alts:
            r = _expand_one(index, alt, owners, route_keys, route_branch)
            if r == "start":
                best = "start"
                break
            if r is not None and (best is None or r[0] < best[0]):
                best = r
        if best == "start":
            continue
        if best is None:
            out.append(c)
            continue
        _score, extra, sub = best
        new = [nc for nc in path_conds(extra)
               if not any(o.src == nc.src and o.negated == nc.negated for o in out)]
        if sub is not None:
            new.extend(_carry(Cond(a, neg, step=c.step), c) for a, neg in atoms(sub, False))
        # What has to happen first goes before the choice it unlocks.
        at = len(out)
        for i, o in enumerate(out):
            if o.kind == "choice" and o.step is c.step:
                at = i
                break
        out[at:at] = new
        added.extend(extra)
    plan.conds = out
    # The roll that starts it can sit in a flag too (l_random_check = roll).
    skipped = []
    for c in plan.skipped:
        names = _cond_names(c.src)
        flags = [n for n in names if FLAG_NAME_RE.match(n)]
        src = c.src
        if flags and c.step is not None:
            owner = index.node_owner.get(id(c.step[1]))
            for var in flags:
                sets = index.flag_setters.get((owner, var), [])
                if len(set(r for r, _p in sets if not LITERAL_RE.match(r.strip()))) == 1:
                    rhs = [r for r, _p in sets if not LITERAL_RE.match(r.strip())][0]
                    src = re.sub(r"(?<![.\w])%s\b" % re.escape(var), "(%s)" % rhs, src)
        if src != c.src:
            nc = _carry(Cond(src, c.negated, step=c.step), c)
            nc.kind = c.kind if nc.kind == "other" else nc.kind
            c = nc
        skipped.append(c)
    plan.skipped = skipped
    keys = set(_step_key(st) for st in plan.steps)
    for st in added:
        if _step_key(st) not in keys:
            keys.add(_step_key(st))
            plan.steps.append(st)


OUTFIT_RE = re.compile(r'^(\w+)\.(swimwear|nightwear|dinerwear|receptionwear|doctorwear)(==|!=|>=|<=|>|<)(\d+)$')
ALONE_RE = re.compile(r'^len\(list_of_chars_display_3\)(==|<=|<|>|>=|!=)(\d+)$')
EFFECT_RE = re.compile(r'^player\.get_effect_state\(["\'](\w+)["\']\)(==|!=|>=|<=|>|<)(\d+)$')
CHARLOC_RE = re.compile(r'^(\w+)\.locations\[actions_left-(\d+)\](==|!=)["\'](\w+)["\']$')
PLOC_RE = re.compile(r'^(?:i_)?location\d*(==|!=)["\'](\w+)["\']$')
QUESTCOND_RE = re.compile(r'^player\.get_quest_state\(["\']([^"\']+)["\'],(\w+)\)(==|!=|>=|<=|>|<)(-?\d+)$')
QUESTCOND_DYN_RE = re.compile(r'^player\.get_quest_state\((\w+)\.fname\+["\']([^"\']+)["\'],(\w+)\)(==|!=|>=|<=|>|<)(-?\d+)$')
SEEN_RE = re.compile(r'^(\w+)\.get_(scene|event|appointment)_seen\(["\']([^"\']+)["\']\)(?:(==|!=)(True|False))?$')
SEEN_TIMES_RE = re.compile(r'^(\w+)\.get_(scene|event|appointment)_seen_times\(["\']([^"\']+)["\'][^)]*\)(==|!=|>=|<=|>|<)(\d+)$')
ITEM_RE = re.compile(r'player\.has_item\(["\']([^"\']+)["\']')
IDENTITY_RE = re.compile(r'\b(char1|selected_char|event_char|i_char|l_char|char|i_girl)\s*(\.\s*(id|fname)\b|\s*(==|!=|<>|\bis\b|\bin\b))')
STAT_RE = re.compile(r'\.(check_affection|check_love|check_lust|check_tease_sexual|check_anger)\(')
SKILL_RE = re.compile(r'player\.(check_charm|check_strength|check_looks|check_hacking|check_sneaking|check_endurance)\(')
COOLDOWN_RE = re.compile(r'^(\w+)\.get_action_allowed\(["\']([^"\']+)["\']\)(?:(==|!=)(True|False))?$')
# Conditions about progress in the story; Honest mode never skips them.
PROGRESS_KINDS = ("quest", "seen", "seen_times", "item", "role", "time")
ENGINE_RE = re.compile(r'\b(actions_event_checked|actions_used|g_replay|menu_active|location_old|current_action|g_scene_mode)\b')
TIME_RE = re.compile(r'\b(actions_left|daytime|cur_weekday|gameday|get_its_raining|g_rainy_\w+|island_days|cur_time)\b')
CMP_FLIP = {"==": "!=", "!=": "==", ">=": "<", "<=": ">", ">": "<=", "<": ">="}


class Cond(object):
    """One atomic condition on the path to a target."""

    def __init__(self, src, negated=False, kind=None, step=None):
        self.src = text(src)
        self.negated = bool(negated)
        self.step = step
        self.kind = "other"
        self.data = {}
        self.value = None         # True / False / None (unknown)
        self.reason = ""
        self.fixed = False        # set up by the mod
        self.lust_before = ()     # player lust changes before the check
        if kind:
            self.kind = kind
        else:
            classify(self)

    @property
    def expr(self):
        if self.negated:
            return u"not (%s)" % self.src
        return self.src


def classify(cond):
    n = norm(cond.src)
    neg = cond.negated
    d = cond.data

    if n.startswith("g_poker_game."):
        # How the card game went; the guide lets the player win it.
        cond.kind = "poker"
        return

    m = OUTFIT_RE.match(n)
    if m:
        op = CMP_FLIP[m.group(3)] if neg else m.group(3)
        cond.kind = "outfit"
        d.update(who=m.group(1), attr=m.group(2), op=op, value=int(m.group(4)))
        return
    m = ALONE_RE.match(n)
    if m:
        op, v = m.group(1), int(m.group(2))
        if neg:
            op = CMP_FLIP[op]
        if (op in ("==", "<=") and v == 1) or (op == "<" and v == 2):
            cond.kind = "alone"
        elif (op == ">" and v >= 1) or (op == ">=" and v >= 2) or (op == "!=" and v == 1):
            cond.kind = "company"
        d.update(op=op, value=v)
        return
    m = EFFECT_RE.match(n)
    if m:
        cond.kind = "effect"
        d.update(effect=m.group(1), op=CMP_FLIP[m.group(2)] if neg else m.group(2), value=int(m.group(3)))
        return
    m = PLOC_RE.match(n)
    if m:
        cond.kind = "location"
        d.update(op=CMP_FLIP[m.group(1)] if neg else m.group(1), location=m.group(2))
        return
    m = QUESTCOND_RE.match(n)
    if m:
        cond.kind = "quest"
        d.update(quest=m.group(1), who=m.group(2), op=CMP_FLIP[m.group(3)] if neg else m.group(3),
                 value=int(m.group(4)))
        return
    m = QUESTCOND_DYN_RE.match(n)
    if m:
        # get_quest_state(char1.fname + " swimwear", char1): her own quest.
        cond.kind = "quest"
        d.update(quest="", quest_var=m.group(1), quest_suffix=m.group(2), who=m.group(3),
                 op=CMP_FLIP[m.group(4)] if neg else m.group(4), value=int(m.group(5)))
        return
    m = SEEN_RE.match(n)
    if m:
        want = True
        if m.group(4) and (m.group(4) == "==") != (m.group(5) == "True"):
            want = False
        if neg:
            want = not want
        cond.kind = "seen"
        d.update(who=m.group(1), what=m.group(2), name=m.group(3), want=want)
        return
    m = SEEN_TIMES_RE.match(n)
    if m:
        cond.kind = "seen_times"
        d.update(who=m.group(1), what=m.group(2), name=m.group(3),
                 op=CMP_FLIP[m.group(4)] if neg else m.group(4), value=int(m.group(5)))
        return
    if ENGINE_RE.search(n):
        cond.kind = "dispatch"
        return
    m = CHARLOC_RE.match(n)
    if m:
        cond.kind = "char_location"
        d.update(who=m.group(1), back=int(m.group(2) or 1), op=CMP_FLIP[m.group(3)] if neg else m.group(3),
                 location=m.group(4))
        return
    if TIME_RE.search(n) and not STAT_RE.search(n) and ".locations[" not in n and "random" not in n:
        cond.kind = "time"
        return
    m = COOLDOWN_RE.match(n)
    if m:
        want = m.group(4) != "False" if m.group(3) == "==" else (m.group(4) == "False" if m.group(3) else True)
        if neg:
            want = not want
        cond.kind = "cooldown"
        d.update(who=m.group(1), action=m.group(2), want=want)
        return
    if "random" in n:
        cond.kind = "chance"
        return
    if SKILL_RE.search(n):
        cond.kind = "skill"
        return
    m = ITEM_RE.search(text(cond.src))
    if m:
        cond.kind = "item"
        d["item"] = m.group(1)
        return
    if STAT_RE.search(n):
        cond.kind = "stat"
        return
    if IDENTITY_RE.search(text(cond.src)):
        cond.kind = "identity"
        return
    if "_return" in n or "action_event" in n or ENGINE_RE.search(n):
        cond.kind = "dispatch"
        return


# ---------------------------------------------------------------------------
# Safe evaluation
# ---------------------------------------------------------------------------

class Unsafe(Exception):
    pass


class _SafeTransformer(pyast.NodeTransformer):
    """Rejects calls with side effects; makes char.check_x(...) quiet."""

    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if cls_name(f) == "Attribute":
            if f.attr == "check_set_quest_fulfilled":
                # Read only: is the quest done (or ready to be)?
                tmpl = pyast.parse("_hisg_quest_done(__o__)", mode="eval").body
                tmpl.args = [f.value] + list(node.args)
                return tmpl
            if f.attr in SAFE_CHECKS:
                tmpl = pyast.parse("_hisg_quiet(__o__, %r)" % str(f.attr), mode="eval").body
                tmpl.args[0] = f.value
                node.func = tmpl
                return node
            dotted = _dotted(f)
            if f.attr in CHANCE_CHECKS or "random" in dotted:
                raise Unsafe("chance")
            if dotted in ("renpy.loadable", "renpy.has_label"):
                return node
            if f.attr in STRING_METHODS:
                return node
            if f.attr.startswith(("get_", "has_", "is_", "count_")):
                return node
            raise Unsafe("call %s" % f.attr)
        if cls_name(f) == "Name":
            if f.id in SAFE_FUNCS:
                return node
            raise Unsafe("call %s" % f.id)
        raise Unsafe("call")


def _dotted(node):
    parts = []
    while cls_name(node) == "Attribute":
        parts.append(node.attr)
        node = node.value
    if cls_name(node) == "Name":
        parts.append(node.id)
    return ".".join(reversed(parts))


def _quiet(obj, name):
    meth = getattr(obj, name)

    def call(*args, **kwargs):
        argnames = _argnames(meth)
        if argnames and argnames[0] == "self":
            argnames = argnames[1:]
        args = list(args)
        for name, value in (("repercussions", False), ("silent", True)):
            if name not in argnames:
                continue
            pos = argnames.index(name)
            if pos < len(args):
                args[pos] = value
            else:
                kwargs[name] = value
        return meth(*args, **kwargs)
    return call


def _quest_done(player, name, about):
    for q in getattr(player, "quests", []):
        if q.name == name and q.quest_about.id == about.id:
            return bool(q.fulfilled or q.get_quest_fulfilled())
    return False


def _argnames(func):
    import inspect
    for getter in ("getargspec", "getfullargspec"):
        try:
            return getattr(inspect, getter)(func).args
        except Exception:
            continue
    return []


_compiled = {}


def _compile_safe(src):
    key = text(src)
    code = _compiled.get(key)
    if code is None:
        try:
            tree = pyast.parse(key.replace("<>", "!="), mode="eval")
            tree = _SafeTransformer().visit(tree)
            pyast.fix_missing_locations(tree)
            code = compile(tree, "<scene-guide>", "eval")
        except Unsafe as e:
            code = ("unsafe", str(e))
        except SyntaxError:
            code = ("unsafe", "syntax")
        _compiled[key] = code
    return code


def safe_value(src, global_ns, local_ns):
    """Evaluates an expression without side effects; returns (value, reason)."""
    code = _compile_safe(src)
    if isinstance(code, tuple):
        return None, code[1]
    ns = dict(local_ns)
    ns["_hisg_quiet"] = _quiet
    ns["_hisg_quest_done"] = _quest_done
    try:
        return eval(code, global_ns, ns), ""
    except NameError:
        return None, "local"
    except Exception as e:
        return None, "error %s" % e.__class__.__name__


def safe_eval(src, global_ns, local_ns):
    """
    Evaluates a game condition without side effects.

    Returns (value, reason): value is True / False, or None when the
    condition cannot be evaluated (local variable, dice roll, unknown call).
    """
    value, reason = safe_value(src, global_ns, local_ns)
    if reason:
        return None, reason
    try:
        return bool(value), ""
    except Exception as e:
        return None, "error %s" % e.__class__.__name__


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class Hop(object):
    """One label on the way from the top label down to the target."""

    def __init__(self, label, edge=None):
        self.label = label        # label reached at this hop
        self.edge = edge          # Edge used to get here from the hop above


POKER_WIN_LABEL = "poker_win"


class Plan(object):

    def __init__(self, kind, name):
        self.kind = kind
        self.name = name
        self.marker = None
        self.hops = []            # top label first
        self.entry = None         # "main" (from the main loop) or "direct"
        self.entry_return = ""    # main-loop action ("do_workout_pullups")
        self.target_label = None  # label the mod calls
        self.target_idx = 0       # index of target_label in hops
        self.call_args = []       # [(keyword or None, source)] for target_label
        self.bound = {}           # parameter values worked out along the chain
        self.conds = []           # [Cond] below the target label
        self.skipped = []         # [Cond] above it (random triggers...)
        self.steps = []           # path steps below the target label
        self.location = ""
        self.defaults = {}        # label parameter -> default value source
        self.preset = {}          # character variables the game sets before the call
        self.background = []      # Scene statements the caller shows before the target
        self.pick = ""            # variable the game fills with a random draw (contests)
        self.pick_values = []     # values other draws must give (a label, a number)
        self.argfix = {}          # parameter of the target label -> value it must have
        self.lead = ""            # the girl the scene starts with, when she is the second one
        self.statement = False    # no route: the guide runs the marker's statement itself
        self.never = False        # the game never does it for her (only for other girls)
        self.drawn = False        # the game draws who takes part; started directly with her
        self.index = None
        self.launchable = False
        self.reason = ""
        self.notes = []

    @property
    def poker_win(self):
        """The target comes after winning a poker game."""
        return any(h.label == POKER_WIN_LABEL for h in self.hops[self.target_idx + 1:])

    def __repr__(self):
        return "<Plan %s %s via %s>" % (self.kind, self.name, self.target_label)


def _is_char_obj(obj):
    return obj is not None and hasattr(obj, "fname") and hasattr(obj, "locations")


def _arg_ok(arg, char, store):
    """False when the argument is a fixed character that is not `char`."""
    a = arg.split("=", 1)[1].strip() if re.match(r"^\w+\s*=[^=]", arg) else arg.strip()
    if not re.match(r"^\w+$", a) or store is None or char is None or a in CHAR_NAMES:
        return True
    if re.match(r"^(char|event_char|selected_char)\d*$", a):
        return True  # char2: a variable set while the game runs
    if a.startswith(("l_", "i_", "ll_")):
        # A local variable or parameter: decided while the game runs.
        return True
    obj = getattr(store, a, None)
    if not _is_char_obj(obj):
        return True
    return obj is char


_char_names_cache = {}


def _all_char_names(store):
    """Lower case first names of every character object in the store."""
    key = id(store)
    names = _char_names_cache.get(key)
    if names is None:
        names = set()
        for value in list(getattr(store, "__dict__", {}).values()):
            if _is_char_obj(value):
                try:
                    names.add(text(value.fname).lower())
                except Exception:
                    pass
        _char_names_cache[key] = names
    return names


def other_char_label(label, char, store):
    """Is the label named after another character (e.g. "..._natasha")?"""
    if char is None or store is None:
        return False
    tokens = set(text(label).lower().split("_"))
    mine = text(char.fname).lower()
    if mine in tokens:
        return False
    return bool(tokens & _all_char_names(store))


def subject_ok(marker, char, store, index):
    """Is the marker about `char`?"""
    subj = marker.subject.strip()
    if "=" in subj:
        subj = subj.split("=", 1)[1].strip()
    params = [p for p, _d in index.params.get(marker.owner, [])]
    if subj.startswith("l_") and subj not in params and store is not None:
        named = fixed_local_char(index, marker.owner, subj)
        obj = getattr(store, named, None) if named else None
        if _is_char_obj(obj) and (obj.fname or "").lower() == named:
            return obj is char  # l_moderator = jennifer: only about Jennifer
    if subj in params or subj in CHAR_NAMES or re.match(r"^event_char\d*$", subj):
        # Set by whoever starts the label (checked along the route).
        return True
    return _arg_ok(subj, char, store)


_FNAMES = {}


def _girl_names(store):
    """First names of the characters ("Yvette" -> its variable name)."""
    key = id(store)
    if key not in _FNAMES:
        out = {}
        for var, obj in list(getattr(store, "__dict__", {}).items()):
            if _is_char_obj(obj) and getattr(obj, "fname", "") and (obj.fname or "").lower() == var:
                out[obj.fname] = var
        _FNAMES.clear()
        _FNAMES[key] = out
    return _FNAMES[key]


def _names_other_girl(src, char, store, also=None):
    """A text like "Yvette blue underwear" in a condition about `char`."""
    if store is None or char is None or not any(n in src for n in CHAR_NAMES + ("i_char",)):
        return False
    if not re.search(r"get_quest_state\(|\bi_name\b|_item", src):
        return False  # only presents and quests are named after a girl
    names = _girl_names(store)
    for lit in re.findall(r'"([^"]*)"|\'([^\']*)\'', src):
        words = re.split(r"[_\s]+", lit[0] or lit[1])
        if getattr(char, "fname", None) in words:
            continue
        for w in words:
            if w in names and w != getattr(char, "fname", None) and w != getattr(also, "fname", None) \
                    and not re.search(r"\b%s\b" % names[w], src):
                return True
    return False


def _label_sources(index, label):
    """Python statements anywhere in a label (cached)."""
    cache = index.__dict__.setdefault("_label_src_cache", {})
    if label in cache:
        return cache[label]
    out, seen = [], set()

    def walk(block):
        for node in block or []:
            if id(node) in seen:
                continue
            seen.add(id(node))
            code = getattr(node, "code", None)
            if code is not None:
                out.append(text(getattr(code, "source", code)))
            walk(getattr(node, "block", None))
            for entry in getattr(node, "entries", None) or []:
                if isinstance(entry, (tuple, list)) and len(entry) == 2:
                    walk(entry[1])
            for item in getattr(node, "items", None) or []:
                if isinstance(item, (tuple, list)) and len(item) == 3:
                    walk(item[2])
    node = index.labels.get(label)
    if node is not None:
        walk(node.block)
    cache[label] = out
    return out


def fixed_local_char(index, label, var):
    """l_moderator = jennifer in the label: the name it is set to, else None."""
    rx = re.compile(r"^\s*%s\s*=\s*([a-z]+)\s*$" % re.escape(var), re.M)
    names = []
    for src in _label_sources(index, label):
        for m in rx.finditer(src):
            if m.group(1) not in ("no_char", "none") and m.group(1) not in names:
                names.append(m.group(1))
    # l_char1 = no_char ... l_char1 = amy: only ever her.
    return names[0] if len(names) == 1 else None


def _target_literals(index, chain, target_idx):
    """Parameter values of the target label that are plain literals."""
    literal = {}
    if chain[target_idx].edge is None:
        return literal
    lit_re = r'^(True|False|None|-?\d+|"[^"]*"|\'[^\']*\')$'
    params = [p for p, _d in index.params.get(chain[target_idx].label, [])]
    args = chain[target_idx].edge.args
    for i, arg in enumerate(args):
        kw, src = _split_kw(arg)
        pname = kw or (params[i] if i < len(params) else None)
        if pname and re.match(lit_re, src.strip()):
            literal[pname] = safe_value(src, {}, {})[0]
    passed = set(params[:len([a for a in args if _split_kw(a)[0] is None])])
    passed |= set(_split_kw(a)[0] for a in args if _split_kw(a)[0])
    for pname, default in index.params.get(chain[target_idx].label, []):
        if pname not in passed and default is not None and re.match(lit_re, text(default).strip()):
            literal[pname] = safe_value(text(default), {}, {})[0]
    return literal


def _chain_literals(index, chain, target_idx):
    """
    Plain values handed to the target label and to the labels below it
    (contest_round(..., i_type="win")). A route that needs them otherwise
    can't be taken.
    """
    literal = _target_literals(index, chain, target_idx)
    for hop in chain[target_idx + 1:]:
        if hop.edge is None or hop.edge.how not in ("call", "python"):
            continue
        params = index.params.get(hop.label, [])
        names = [p for p, _d in params]
        pos, passed = 0, set()
        for arg in hop.edge.args:
            kw, src = _split_kw(arg)
            name = kw or (names[pos] if pos < len(names) else None)
            if kw is None:
                pos += 1
            if name:
                passed.add(name)
                if LITERAL_RE.match(src.strip()):
                    literal[name] = safe_value(src, {}, {})[0]
                else:
                    literal.pop(name, None)
        for pname, default in params:
            if pname not in passed and default is not None and LITERAL_RE.match(text(default).strip()):
                literal[pname] = safe_value(text(default), {}, {})[0]
    return literal


def pool_conditions(index, plan):
    """
    The draw only picks from girls who pass a filter while the pool is built
    (in the gym, "workout_shower" waiting time over...). Those filters are
    requirements for her, written as char1 conditions.
    """
    out = []
    var = plan.pick
    rx_pick = re.compile(r"\b%s\s*=\s*renpy\.random\.choice\(\s*(\w+)\s*\)" % re.escape(var))
    for hop in plan.hops[1:]:
        srcs = "\n".join(_label_sources(index, hop.label))
        m = rx_pick.search(srcs)
        if not m:
            continue
        pool = m.group(1)
        node = index.labels.get(hop.label)
        if node is None:
            continue
        for st in _all_nodes(node.block):
            if cls_name(st) != "If":
                continue
            for cond, blk in st.entries:
                code = " ".join(text(getattr(getattr(x, "code", None), "source", getattr(x, "code", ""))) for x in (blk or []))
                if "%s.append(" % pool not in code:
                    continue
                src = re.sub(r"\b\w+\[\s*\w+\s*\]", "char1", text(cond))
                for a, neg in atoms(src, False):
                    if "renpy.loadable" in a or "renpy.has_label" in a:
                        continue
                    c = Cond(a, neg)
                    c.from_pool = True
                    out.append(c)
        break
    return out


SELECT_RE = re.compile(r"call\s+screen\s+select_girl\(\s*(\w+)")


def choice_list_conditions(index, plan):
    """
    "Which girl do you want to visit?": the game only lists girls who pass a
    filter (you know her room number, not visited too recently). Those
    filters are requirements for her too.
    """
    out = []
    for hop in plan.hops[1:]:
        node = index.labels.get(hop.label)
        if node is None:
            continue
        pool = None
        for st in _all_nodes(node.block):
            m = SELECT_RE.search(text(getattr(st, "line", "")))
            if m:
                pool = m.group(1)
        if not pool:
            continue
        for st in _all_nodes(node.block):
            if cls_name(st) != "If":
                continue
            for cond, blk in st.entries:
                code = " ".join(text(getattr(getattr(x, "code", None), "source", getattr(x, "code", ""))) for x in (blk or []))
                if "%s.append(" % pool not in code:
                    continue
                src = re.sub(r"\b\w+\[\s*\w+\s*\]", "char1", text(cond))
                for a, neg in atoms(src, False):
                    c = Cond(a, neg)
                    c.from_pool = True
                    out.append(c)
    return out


def clock_params(index, plan):
    """i_actions_left / ap handed the current time: read them as the clock."""
    rename = {}
    for i, hop in enumerate(plan.hops):
        params = index.params.get(hop.label, [])
        for pname, default in params:
            if text(default or "").strip() == "actions_left":
                rename[pname] = "actions_left"
        if hop.edge is not None:
            pos = [a for a in hop.edge.args if _split_kw(a)[0] is None]
            for j, arg in enumerate(hop.edge.args):
                kw, src = _split_kw(arg)
                name = kw or (params[j][0] if j < len(params) and kw is None and j < len(pos) else None)
                if name and src.strip() == "actions_left":
                    rename[name] = "actions_left"
    rename.pop("actions_left", None)
    if not rename:
        return plan.conds
    out = []
    for c in plan.conds:
        if c.kind != "choice" and any(re.search(r"\b%s\b" % re.escape(n), c.src) for n in rename):
            new = _carry(Cond(_rename_vars(c.src, rename), c.negated, step=c.step), c)
            for attr in ("from_pool",):
                if getattr(c, attr, None):
                    setattr(new, attr, getattr(c, attr))
            c = new
        out.append(c)
    return out


ROOM_LOC_RE = re.compile(r'^\s*location\s*=\s*\w+\.fname\s*\+\s*["\']_room["\']', re.M)
PIC_WEAR_RE = re.compile(r'renpy\.loadable\([^\n]*_swim["\']\s*\+\s*unicode\(\s*[\w\[\]]+\.swimwear')


def picture_outfit(index, plan, meta, char, store):
    """
    Pool distractions: the game only plays them when her pictures exist for
    the swimwear she has on. The entry's picture (..._swim1.jpg) is tried
    with each swimwear to see which ones she has pictures for.
    """
    pic = getattr(meta, "image_name1", "") or ""
    if not re.search(r"_swim\d\b", pic) or store is None or char is None:
        return []
    if any(c.kind == "outfit" and c.data.get("attr") == "swimwear" for c in plan.conds):
        return []
    checked = False
    for hop in plan.hops[1:]:
        node = index.labels.get(hop.label)
        if node is not None and any(cls_name(st) == "If" and any(PIC_WEAR_RE.search(text(c)) for c, _b in st.entries)
                                    for st in _all_nodes(node.block)):
            checked = True
            break
    if not checked:
        return []
    first = (list(getattr(meta, "image_list", []) or []) or [1])[0]
    base = re.sub(r"\.(jpg|webp|png)$", "", pic.replace("[number]", text(first)))
    have = []
    for v in range(0, 4):
        stem = re.sub(r"_swim\d\b", "_swim%d" % v, base)
        try:
            if any(store.renpy.loadable(stem + ext) for ext in (".jpg", ".webp")):
                have.append(v)
        except Exception:
            return []
    if not have:
        return []
    cur = getattr(char, "swimwear", None)
    if cur in have:
        return [Cond(u"char1.swimwear == %d" % cur)]
    if have == list(range(have[0], have[-1] + 1)) and len(have) > 1:
        out = [Cond(u"char1.swimwear >= %d" % have[0])]
        if have[-1] < 3:
            out.append(Cond(u"char1.swimwear <= %d" % have[-1]))
        return out
    return [Cond(u"char1.swimwear == %d" % have[0])]


_ROLE_RE = None


def role_holders(index, store, role):
    """
    Who can have a job (jobs.bartender): the girls the game ever puts in it
    (jobs.bartender = yumiko, get_bartender() returning jennifer, the job's
    list), and whoever has it now.
    """
    cache = index.__dict__.setdefault("_role_holders", {})
    attr = role.split(".")[-1]
    if attr in cache:
        return cache[attr]
    names = set()
    rx = re.compile(r"\bjobs\.%s\d*\s*=\s*([A-Za-z_][\w.]*(?:\(\))?)" % re.escape(attr))
    srcs = []
    for label in index.labels:
        srcs.extend(_label_sources(index, label))
    srcs.extend(index.__dict__.get("init_sources", []))
    funcs = []
    for src in srcs:
        for m in rx.finditer(src):
            v = m.group(1)
            if v.endswith("()"):
                funcs.append(v.split(".")[-1][:-2])
            elif "." not in v:
                names.add(v)
    for src in srcs:
        for f in funcs:
            i = src.find("def %s(" % f)
            if i >= 0:
                body = src[i:i + 1500].split("\n    def ")[0]
                names.update(re.findall(r"return\s+([a-z]\w*)", body))
    jobs = getattr(store, "jobs", None)
    for extra in ("%s_list" % attr, attr):
        v = getattr(jobs, extra, None)
        for o in (v if isinstance(v, (list, tuple)) else [v]):
            if _is_char_obj(o):
                names.add((o.fname or "").lower())
    cache[attr] = names
    return names


def role_possible(index, store, role, char):
    if store is None or char is None:
        return True
    holders = role_holders(index, store, role)
    return not holders or (char.fname or "").lower() in holders


def role_local(index, label, var):
    """l_bartender = jobs.bartender in the label: "jobs.bartender", else None."""
    rx = re.compile(r"^\s*%s\s*=\s*(jobs\.\w+)\s*$" % re.escape(var), re.M)
    for src in _label_sources(index, label):
        m = rx.search(src)
        if m:
            return m.group(1)
    return None


def random_pick(index, label, var):
    """Does the label set `var` by drawing a girl (var = renpy.random.choice(...))?
    For list_round1A[counter]: is the list filled with drawn girls?"""
    m = re.match(r"^(\w+)\[", var)
    if m:
        srcs = "\n".join(_label_sources(index, label))
        for item in re.findall(r"\b%s\.append\(\s*(\w+)\s*\)" % re.escape(m.group(1)), srcs):
            if item != var and random_pick(index, label, item):
                return True
        return False
    rx = re.compile(r"\b%s\s*=\s*renpy\.random\.choice\(" % re.escape(var))
    seen = set()

    def walk(block):
        for node in block or []:
            if id(node) in seen:
                continue
            seen.add(id(node))
            code = getattr(node, "code", None)
            if code is not None and rx.search(text(getattr(code, "source", code))):
                return True
            for attr in ("block",):
                if walk(getattr(node, attr, None)):
                    return True
            for entry in getattr(node, "entries", None) or []:
                if isinstance(entry, (tuple, list)) and len(entry) == 2 and walk(entry[1]):
                    return True
            for item in getattr(node, "items", None) or []:
                if isinstance(item, (tuple, list)) and len(item) == 3 and walk(item[2]):
                    return True
        return False
    node = index.labels.get(label)
    return bool(node is not None and walk(node.block))


def _edge_identity_ok(edge, global_ns, local_ns):
    """False when the call site is only reached for another character."""
    try:
        return refine_identity(path_conds(edge.path), global_ns, local_ns) is not None
    except Exception:
        return True


def find_chains(index, start, char, store, global_ns, local_ns, max_depth=12, max_chains=48,
                fixed_subject=False):
    """
    Walks the call graph upwards from label `start`.

    Returns chains, each a list of Hop objects from the top label down to
    `start`. A chain stops at the main loop or at a label nobody calls.
    """
    results = []
    queue = [([Hop(start)], fixed_subject)]
    expanded = 0
    me = (getattr(char, "fname", "") or "").lower()
    while queue and len(results) < max_chains and expanded < 800:
        chain, fixed = queue.pop(0)
        expanded += 1
        top = chain[0].label
        seen = set(h.label for h in chain)
        edges = list(index.callers.get(top, []))
        for e in index.expr_edges:
            name, _r = safe_value(e.expr, global_ns, local_ns)
            if name == top:
                edges.append(Edge(top, e.caller, e.path, e.args, node=e.node))
        fresh = [e for e in edges if e.caller not in seen]
        usable = [e for e in fresh
                  if fixed or (
                      (all(_arg_ok(a, char, store) for j, a in enumerate(e.args) if _subject_arg(index, top, j, a))
                       or (me and me in [_split_kw(a)[1].strip() for a in e.args]))  # yvette, faye
                      and _edge_identity_ok(e, global_ns, local_ns))]
        if fresh and not usable and top != MAIN_LOOP_LABEL:
            continue  # only ever reached for another girl
        if top == MAIN_LOOP_LABEL or not usable or len(chain) > max_depth:
            results.append(chain)
            continue
        for e in usable:
            if e.caller == MAIN_LOOP_LABEL:
                results.append([Hop(MAIN_LOOP_LABEL), Hop(top, e)] + chain[1:])
        for e in usable:
            if e.caller != MAIN_LOOP_LABEL:
                # call beach_bar_event_amy(amy): above it char1 is someone else.
                named = fixed or bool(me and me in [_split_kw(a)[1].strip() for a in e.args])
                queue.append(([Hop(e.caller), Hop(top, e)] + chain[1:], named))
    return results


def location_from_return(value):
    v = value[3:] if value.startswith("do_") else value
    for loc in KNOWN_LOCATIONS:
        if v.startswith(loc + "_") or v == loc:
            return loc
    # do_pl_shower_workout: the place is somewhere in the name
    words = v.split("_")
    for loc in KNOWN_LOCATIONS:
        if "_" not in loc and loc in words[1:]:
            return loc
    return ""


def _split_kw(arg):
    m = re.match(r"^(\w+)\s*=([^=].*)$", arg)
    if m:
        return m.group(1), m.group(2).strip()
    return None, arg


def _bind(index, label, values, kwvalues):
    out = {}
    params = index.params.get(label, [])
    for i, (pname, _default) in enumerate(params):
        if i < len(values):
            out[pname] = values[i]
    out.update(kwvalues)
    return out


def _evaluate_chain(index, chain, target_idx, char, global_ns, base_ns, location):
    """
    Works out the argument values from the top of the chain down to the
    target hop. Returns (values, kwvalues, bound) for the target call.
    """
    ns = dict(base_ns)
    values, kwvalues = [], {}
    for i in range(1, target_idx + 1):
        hop = chain[i]
        values, kwvalues = [], {}
        for arg in hop.edge.args:
            kw, src = _split_kw(arg)
            v, reason = safe_value(src, global_ns, ns)
            if reason:
                v = _guess_value(src, char, location)
            elif _is_char_obj(v) and v is not char and _is_local_char_var(src) and src not in ns:
                v = char  # a leftover value of a local variable
            if kw:
                kwvalues[kw] = v
            else:
                values.append(v)
        bound = _bind(index, hop.label, values, kwvalues)
        ns = dict(base_ns)
        ns.update(bound)
    return values, kwvalues, ns


def _is_local_char_var(src):
    s = src.strip()
    return bool(re.match(r"^\w+$", s)) and (s in CHAR_NAMES or s.startswith(("l_", "i_", "ll_")))


def _guess_value(src, char, location):
    low = src.lower()
    if "return" in low:
        return "goto_%s" % (location or "player_room")
    if low in CHAR_NAMES:
        return char
    return None


SECOND_RE = re.compile(r"^(event_char\d|char[2-9])\.id==(\w+)\.id$")
LEAD_SUBJ_RE = re.compile(r"^(char|event_char|i_char|l_char)[2-9]$")


def _about_second(marker, girl):
    """Is the marker about `girl` as the second girl of a scene (amy, char2)?"""
    subj = marker.subject.strip().split("=", 1)[-1].strip()
    # l_bartender: the girl on duty next to the one the scene is about.
    return subj == (getattr(girl, "fname", "") or "").lower() or bool(LEAD_SUBJ_RE.match(subj)) \
        or bool(re.match(r"^l_[a-z]\w*$", subj))


def lead_candidates(index, kind, name, char, store, marker=None):
    """
    Girls a scene about `char` starts with: Alice for the shower with Amy,
    Faye for her drink with Natasha. Taken from the labels on the way
    (shower_event_alice_amy) and from "char1.id == alice.id" checks.
    Girls on the island come first.
    """
    if store is None or char is None:
        return []
    gns = store.__dict__
    lns = dict((n, char) for n in CHAR_NAMES)
    names = _girl_names(store)
    found = []
    markers = [marker] if marker is not None else index.markers_for(kind, name)
    for mk in markers:
        if not _about_second(mk, char):
            continue
        for chain in find_chains(index, mk.entry, char, store, gns, lns, fixed_subject=True):
            words = []
            for hop in chain[1:]:
                words.extend(text(hop.label).lower().split("_"))
                if hop.edge is not None:
                    for c in path_conds(hop.edge.path):
                        words.extend(re.findall(r"\bchar1\.id\s*==\s*(\w+)\.id", c.src))
            for w in words:
                obj = getattr(store, w, None)
                if _is_char_obj(obj) and obj is not char and (obj.fname or "").lower() == w and w not in found \
                        and obj.fname in names:
                    found.append(w)
    on = getattr(store, "list_of_characters", [])
    return sorted(found, key=lambda w: 0 if getattr(store, w) in on else 1)


def build_plan(index, kind, name, char, store, meta=None, marker=None):
    """
    Works out how to reach a target.

    `meta` is the game's own cl_image_with_desc entry (scenes_available...),
    used for the location, outfits and call_label it provides.

    A scene where she is the second girl (the shower with Alice for Amy) is
    planned for the girl it starts with; plan.lead names her.
    """
    plan = _build_plan(index, kind, name, char, store, meta, marker)
    if plan.launchable or kind not in ("scene", "event", "appointment"):
        return plan
    for var in lead_candidates(index, kind, name, char, store, marker):
        p = _build_plan(index, kind, name, getattr(store, var), store, meta, marker, lead_for=char)
        if p.launchable:
            p.lead = var
            return p
    return plan


def _build_plan(index, kind, name, char, store, meta=None, marker=None, lead_for=None):
    plan = Plan(kind, name)
    plan.index = index
    global_ns = store.__dict__ if store is not None else {}
    local_ns = dict((n, char) for n in CHAR_NAMES)

    markers = [marker] if marker is not None else index.markers_for(kind, name)
    all_markers = list(markers)
    if lead_for is not None:
        # A quest about her can be started in the other girl's scene.
        markers = [m for m in markers if _about_second(m, lead_for) or m.kind == "quest"]
    else:
        own = [m for m in markers if subject_ok(m, char, store, index)]
        if kind in SENDER_KINDS:
            # Sent by someone else (the reception's contest invitation):
            # only when nothing is about her.
            own = own + [m for m in markers if m not in own and fixed_sender(m, store)]
        markers = own

    candidates = []
    routed = set()  # markers with a way there from the game, for her or not
    for mk in markers:
        if candidates and kind in SENDER_KINDS and fixed_sender(mk, store) and not subject_ok(mk, char, store, index):
            break
        for start, mk_steps in [(mk.entry, mk.relpath)]:
            subj = mk.subject.strip().split("=", 1)[-1].strip()
            fixed = bool(store is not None and char is not None and subj == (getattr(char, "fname", "") or "").lower())
            for chain in find_chains(index, start, char, store, global_ns, local_ns,
                                     fixed_subject=fixed or lead_for is not None or fixed_sender(mk, store)):
                if chain[0].label != MAIN_LOOP_LABEL and chain[0].label.startswith("test"):
                    continue  # the developer's test labels
                if len(chain) > 1:
                    routed.add(id(mk))
                cand = _candidate(index, mk, chain, list(mk_steps), char, global_ns, local_ns, store,
                                  also=lead_for)
                if cand is not None:
                    candidates.append(cand)

    if not candidates:
        call_label = getattr(meta, "call_label", "") if meta is not None else ""
        if call_label and call_label in index.labels:
            plan.entry = "direct"
            plan.target_label = call_label
            args = _direct_args(index, call_label)
            plan.call_args = args or []
            plan.launchable = args is not None
            if not plan.launchable:
                plan.reason = args_reason(index, call_label)
            plan.notes.append("No unlock statement found in the script; the game's own replay label is used.")
            _fill_location(plan, meta, char, store)
            return plan
        action = getattr(meta, "scene_action", "") if meta is not None else ""
        edge = index.dispatch.get("do_" + action) if action else None
        if edge is not None:
            # Start the activity the scene belongs to; how it goes is up
            # to the game and the player.
            plan.entry = "main"
            plan.entry_return = "do_" + action
            plan.target_label = edge.target
            plan.hops = [Hop(MAIN_LOOP_LABEL), Hop(edge.target, edge)]
            plan.target_idx = 1
            plan.call_args = [_split_kw(a) for a in edge.args]
            plan.launchable = True
            plan.notes.append("The guide starts the activity this one belongs to; "
                              "the outcome depends on how it goes.")
            _fill_location(plan, meta, char, store)
            return plan
        if markers and kind in STATEMENT_KINDS:
            # Done by a statement deep in the game's own routines (the end
            # of the day, a phone message): what leads to it is shown, the
            # guide does the statement itself.
            for mk in markers:
                if id(mk) in routed or other_char_label(mk.owner, char, store):
                    continue  # the game gets there, only not for her
                conds = refine_identity(path_conds(mk.path), global_ns, local_ns)
                if conds is None:
                    continue
                plan.marker = mk
                plan.statement = True
                plan.steps = list(mk.path)
                plan.conds = [c for c in conds if c.kind not in ("dispatch",)]
                for _i in range(3):
                    expand_flags(index, plan, global_ns)
                _fill_location(plan, meta, char, store)
                return plan
        if all_markers and kind in STATEMENT_KINDS and lead_for is None:
            # The game only does it for other girls (Yvette's picture 505):
            # the guide can still do the statement for her.
            plan.marker = all_markers[0]
            plan.statement = True
            plan.never = True
            _fill_location(plan, meta, char, store)
            return plan
        plan.reason = "No route found in the game's script for this entry."
        _fill_location(plan, meta, char, store)
        return plan

    candidates.sort(key=lambda c: c["score"])
    best = candidates[0]
    arrange = getattr(index, "arrange_check", None)
    for cand in candidates:
        # Skip routes the game only takes for another girl (picture 501
        # is a different picture for each of them), and routes through an
        # appointment the game never makes with her.
        probe = Plan(kind, name)
        probe.marker, probe.hops = cand["marker"], cand["chain"]
        probe.entry, probe.entry_return = cand["entry"], cand["entry_return"]
        if _trigger_conds(index, probe, char, store, global_ns, local_ns) is False:
            continue
        if arrange is not None and kind != "schedule" and arrange(cand["entry_return"], char) is False:
            continue
        best = cand
        break
    plan.marker = best["marker"]
    plan.hops = best["chain"]
    plan.steps = best["steps"]
    plan.conds = best["conds"]
    plan.skipped = best["skipped"]
    plan.entry = best["entry"]
    plan.entry_return = best["entry_return"]
    plan.target_label = best["target_label"]
    # The random trigger above the target is skipped, but where it takes
    # place and what she wears still matter.
    # Everything above the random gate that is a real requirement stays
    # (waiting times, stats, effects...); only rolls, skill checks, menu
    # plumbing of the main loop are left out.
    skip_kinds = ("chance", "skill", "dispatch", "choice", "identity", "poker")
    # "Not when another girl's event comes first" (the earlier branches of
    # the game's event check) does not matter when the guide starts this one.
    me = (getattr(char, "fname", "") or "").lower()
    mine = re.compile(r"\b(%s|%s)\b" % (re.escape(me or "char1"), "|".join(CHAR_NAMES)))
    plan.skipped = [c for c in plan.skipped if not (c.negated and c.step is not None and c.step[0] in ("if", "guard")
                                                     and not mine.search(c.src))]
    plan.conds = [c for c in plan.skipped if c.kind not in skip_kinds] + plan.conds
    plan.skipped = [c for c in plan.skipped if c.kind in skip_kinds]
    trig = _trigger_conds(index, plan, char, store, global_ns, local_ns)
    if trig is False:
        plan.reason = "In the game this event only happens with another girl."
        _fill_location(plan, meta, char, store)
        return plan
    if trig:
        # "Not when another girl's event comes first" does not matter when
        # the guide starts this one.
        me = (getattr(char, "fname", "") or "").lower()
        trig = [c for c in trig if not c.negated
                or re.search(r"\b(%s|char1|event_char)\b" % re.escape(me or "char1"), c.src)]
        plan.conds = [c for c in trig if c.kind not in skip_kinds] + plan.conds
        plan.skipped += [c for c in trig if c.kind in skip_kinds]
    subj = plan.marker.subject.strip()
    owner_params = [p for p, _d in index.params.get(plan.marker.owner, [])]
    # The label above the scene draws the girl (char1 = renpy.random.choice(...)
    # and then reaches the scene with her).
    if subj in CHAR_NAMES and subj not in ("event_char", "selected_char"):
        names = set([subj])
        for hop in plan.hops[1:]:
            if hop.edge is not None:
                for arg in hop.edge.args:
                    nm = _split_kw(arg)[1].strip()
                    if nm in CHAR_NAMES:
                        names.add(nm)
        for hop in plan.hops[1:]:
            for name in sorted(names):
                if random_pick(index, hop.label, name):
                    plan.pick = name
    if plan.pick:
        plan.conds = plan.conds + pool_conditions(index, plan)
    plan.conds = plan.conds + picture_outfit(index, plan, meta, char, store)
    plan.conds = plan.conds + choice_list_conditions(index, plan)
    plan.conds = clock_params(index, plan)
    role = named = None
    if subj.startswith("l_"):
        # Set in the scene itself, or in a label on the way to it.
        for label in [plan.marker.owner] + [index.top_of.get(h.label, h.label) for h in reversed(plan.hops)]:
            role = role or role_local(index, label, subj)
            named = named or fixed_local_char(index, label, subj)
            if role or named:
                break
    alias = None
    for rhs, _p in index.flag_setters.get((plan.marker.owner, subj), []):
        if rhs.strip() in owner_params:
            alias = rhs.strip()  # l_opponent = i_opponent1
    if named and store is not None and getattr(store, named, None) is char:
        # l_char1 = amy when she is at the beach: what makes it her.
        route_keys = set(_step_key(st) for st in plan.steps)
        route_branch = dict((id(st[1]), st[2]) for st in plan.steps if st[0] == "if")
        for rhs, spath in index.flag_setters.get((plan.marker.owner, subj), []):
            if rhs.strip() != named:
                continue
            extra = _flag_route(spath, route_keys, route_branch) or []
            more = refine_identity(path_conds(extra), global_ns, local_ns) or []
            plan.conds = plan.conds + more
            plan.steps = plan.steps + list(extra)
            break
    elif alias and best["target_idx"] < len(plan.hops) - 1:
        # Handed in by a contest round that drew the girls: start that
        # part directly with her.
        plan.drawn = True
        top = index.top_of.get(plan.marker.entry, plan.marker.owner)
        args = _direct_args(index, top)
        if args is not None:
            plan.hops = [Hop(top)]
            plan.target_label = top
            plan.target_idx = 0
            plan.entry, plan.entry_return = "direct", ""
            plan.call_args = args
            plan.steps = list(plan.marker.path)
            plan.conds = refine_identity(path_conds(plan.marker.path), global_ns, local_ns) or []
            plan.launchable = True
            plan.notes.append("The game draws who takes part while it runs; the guide starts this part directly with her.")
            _fill_location(plan, meta, char, store)
            return plan
    elif role and store is not None:
        # l_bartender = jobs.bartender: she has to be the one on duty.
        who = "char1"
        if lead_for is not None and store is not None:
            who = (lead_for.fname or "").lower()  # the second girl is the one on duty
        rc = Cond(u"%s.id == %s.id" % (role, who), kind="role")
        rc.data["expr"] = role
        rc.data["who"] = who
        plan.conds = [rc] + plan.conds
        if not role_possible(index, store, role, lead_for or char):
            plan.notes.append("In the game %s never has this job." % ((lead_for or char).fname,))
    if role or named or alias:
        pass
    elif (subj.startswith(("l_", "ll_")) or re.match(r"^\w+\[", subj)) and subj not in owner_params \
            and not re.match(r"^l_\w+\.\w+$", subj):
        # e.g. a contest: the game picks who takes part while it runs.
        if random_pick(index, plan.marker.owner, subj):
            plan.pick = subj  # the guide makes the draw pick her
        elif kind in STATEMENT_KINDS:
            # Arranged with whoever won the contest: the guide can do it for her.
            plan.statement = True
            plan.drawn = True
            plan.target_idx = best["target_idx"]
            _fill_location(plan, meta, char, store)
            return plan
        else:
            plan.reason = ("The game picks who takes part while the scene runs, "
                           "so the guide cannot make sure it is %s." % (char.fname if char is not None else "her"))
            _fill_location(plan, meta, char, store)
            return plan
    t = plan.target_idx = best["target_idx"]
    plan.preset = best.get("preset", {})
    # "event_char2.id == amy.id" on the way: the game sets event_char2 = amy
    # where it starts the event; the guide does the same.
    keep = []
    for c in plan.conds:
        m = SECOND_RE.match(norm(c.src))
        if m and not c.negated and store is not None and _is_char_obj(getattr(store, m.group(2), None)):
            plan.preset.setdefault(m.group(1), m.group(2))
            continue
        keep.append(c)
    plan.conds = keep
    for _i in range(3):
        # The choice that sets a flag can sit behind another flag.
        expand_flags(index, plan, global_ns)
    plan.argfix = best.get("argfix", {})
    plan.pick_values = best.get("pick_values", [])
    if t >= 2 and plan.hops[t].edge is not None:
        plan.background = list(getattr(plan.hops[t].edge, "scenes", []) or [])
    for hop in plan.hops:
        for pname, default in index.params.get(hop.label, []):
            if default is not None:
                plan.defaults.setdefault(pname, default)
    _fill_location(plan, meta, char, store)

    if t == 0:
        args = _direct_args(index, plan.target_label, plan.argfix)
        if args is None:
            plan.reason = args_reason(index, plan.target_label)
            return plan
        plan.call_args = args
        plan.launchable = True
        if not index.callers.get(plan.target_label):
            plan.notes.append("The game starts this from Python code; the guide calls it directly.")
        return plan

    edge = plan.hops[t].edge
    plan.call_args = [_split_kw(a) for a in edge.args]
    if edge.how in ("fall", "python"):
        # The label is reached by running on from its parent, or from
        # Python code: call it directly, its variables come from the chain.
        plan.call_args = [(None, "__char__")] if index.params.get(plan.target_label) else []
    plan.launchable = True
    return plan


# Things that come from someone else (a message from the reception).
SENDER_KINDS = ("message",)
# Things the guide can do with the game's own statement when no route leads there.
STATEMENT_KINDS = ("schedule", "message", "sexting", "websearch")


def fixed_sender(marker, store):
    """reception.create_message(4, ...): sent by one fixed character."""
    subj = marker.subject.strip().split("=", 1)[-1].strip()
    if store is None or not re.match(r"^[a-z]\w*$", subj) or subj in CHAR_NAMES:
        return False
    return _is_char_obj(getattr(store, subj, None))


def _subject_arg(index, label, pos, arg):
    """Does this argument decide who the called label is about? (i_char3=jennifer
    next to her does not.) Unknown labels: every argument counts."""
    params = [p for p, _d in index.params.get(label, [])]
    if not params or params[0] not in CHAR_NAMES:
        return True
    return _arg_names_subject(index, label, pos, _split_kw(arg)[0])


def _arg_names_subject(index, label, pos, kw):
    """Is this argument the character the called label is about (its char1)?"""
    params = [p for p, _d in index.params.get(label, [])]
    if not params or params[0] not in CHAR_NAMES:
        return False
    return kw == params[0] if kw else pos == 0


def _rename_vars(src, rename):
    return re.sub(r"\b(\w+)\b", lambda m: rename.get(m.group(1), m.group(1)) if m.start() == 0 or src[m.start() - 1] != "." else m.group(1), src)


def _trigger_conds(index, plan, char, store, global_ns, local_ns):
    """
    For an event the main loop starts through action_event == "x": the
    conditions where the game sets action_event = "x" (quest steps, days,
    time...). Returns a list, [] when there is nothing to add, or False when
    every place that starts it does so for another character.
    """
    if plan.entry != "main" or not plan.entry_return:
        return []
    edge = plan.hops[1].edge if len(plan.hops) > 1 else None
    if edge is None or not any("action_event" in src for src, _n in _edge_conditions(edge)):
        return []
    triggers = index.markers_for("trigger", plan.entry_return)
    if not triggers:
        return []
    # A scene that names its girl (daniela.add_event_seen(...)) can be
    # started with someone else as event_char (Joy tells you about it).
    subj = plan.marker.subject.strip().split("=", 1)[-1].strip() if plan.marker else ""
    obj = getattr(store, subj, None) if (store is not None and subj) else None
    fixed_subject = _is_char_obj(obj) and (getattr(obj, "fname", "") or "").lower() == subj.lower() and obj is char
    best = None
    for tr in triggers:
        ec = getattr(tr, "event_char", None)
        if (ec and not fixed_subject and "." not in ec and not is_char_var(ec, char, store)
                and not ec.startswith(("l_", "i_"))):
            continue
        # The label's parameters as the main loop passes them
        # (event_check(ap, ...) is called with actions_left).
        rename = {}
        for e in index.callers.get(tr.owner, []):
            if e.caller == MAIN_LOOP_LABEL and e.how == "call":
                params = [p for p, _d in index.params.get(tr.owner, [])]
                for pname, arg in zip(params, e.args):
                    kw, src = _split_kw(arg)
                    if re.match(r"^\w+$", src.strip()):
                        rename[pname] = src.strip()
                break
        raw = path_conds(tr.path)
        if rename:
            raw = [_carry(Cond(_rename_vars(c.src, rename), c.negated, c.kind if c.kind == "choice" else None,
                               step=c.step), c) for c in raw]
        conds = refine_identity(raw, global_ns, local_ns)
        if conds is None:
            continue
        if best is None or len(conds) < len(best):
            best = conds
    if best is None:
        return False
    out = [c for c in best if c.kind not in ("dispatch", "choice")]
    if any("chars_invited[" in c.src for c in out):
        # The game goes through the invited girls one by one.
        out = [c for c in out if "chars_invited" not in c.src and not re.search(r"\bcounter\b", c.src)]
        out.append(Cond("hisg_invited_arrived(char1)", kind="invited"))
    return out


def _candidate(index, mk, chain, mk_steps, char, global_ns, local_ns, store=None, also=None):
    # Gate: the lowest edge whose path contains a random roll. The guide
    # starts below it, skipping the random trigger.
    per_hop = []
    for i, hop in enumerate(chain):
        if hop.edge is None or hop.edge.caller == MAIN_LOOP_LABEL:
            per_hop.append([])
        else:
            per_hop.append(path_conds(hop.edge.path))
    target_idx = 0
    if chain[0].label == MAIN_LOOP_LABEL and len(chain) > 1:
        target_idx = 1
    for i in range(1, len(chain)):
        if any(c.kind in ("chance", "skill") for c in per_hop[i]) and chain[i].edge.how != "fall":
            target_idx = max(target_idx, i)
    # Nested labels depend on variables set by their parent: start at the
    # closest top level label instead.
    while target_idx > 0 and chain[target_idx].label not in index.top:
        target_idx -= 1
    # A label that reads what its caller set (l_dress = ...) can't be
    # started on its own either.
    while target_idx > 1 and _reads_caller_locals(index, chain, target_idx):
        target_idx -= 1
    if target_idx == 0 and chain[0].label == MAIN_LOOP_LABEL and len(chain) > 1:
        target_idx = 1

    # call beach_bar_event_amy(amy): above that call char1 is someone else
    # (the girl at the bar), so "char1.id == ..." up there is not about her.
    me = (getattr(char, "fname", "") or "").lower()
    named = 0
    for i in range(1, len(chain)):
        if me and chain[i].edge is not None and me in [_split_kw(a)[1].strip() for a in chain[i].edge.args]:
            named = i
    if named:
        other_ns = dict((n, _UNKNOWN) for n in CHAR_NAMES)
        for i in range(1, named + 1):
            per_hop[i] = refine_identity(per_hop[i], global_ns, other_ns) or []

    steps, conds = [], []
    carried = ()  # lust changes in the labels above, before they go on
    for i in range(target_idx + 1, len(chain)):
        steps.extend(chain[i].edge.path)
        for c in per_hop[i]:
            c.lust_before = carried + _step_lust(index, c)
        conds.extend(per_hop[i])
        carried = carried + getattr(chain[i].edge, "lust", ())
    steps.extend(mk_steps)
    for c in path_conds(mk_steps):
        c.lust_before = carried + _step_lust(index, c)
        conds.append(c)

    skipped = []
    for i in range(1, target_idx + 1):
        skipped.extend(per_hop[i])
    skipped = refine_identity(skipped, global_ns, local_ns)
    if skipped is None:
        return None

    # Labels below the target that are handed a character by an expression
    # such as jobs.doctor: that has to be her (e.g. the nurse on duty).
    roles = []
    for i in range(1, len(chain)):
        for j, arg in enumerate(chain[i].edge.args):
            kw, src = _split_kw(arg)
            local = re.match(r"^l_\w+$", src.strip())
            if local:
                # call play_poker(l_bartender): l_bartender = jobs.bartender
                role = role_local(index, index.top_of.get(chain[i].edge.caller, chain[i].edge.caller), src.strip())
                if role and _arg_names_subject(index, chain[i].label, j, kw):
                    rc = Cond(u"%s.id == char1.id" % role, kind="role")
                    rc.data["expr"] = role
                    roles.append(rc)
                continue
            if i <= target_idx:
                continue
            if "." not in src or "(" in src or not re.match(r"^[\w.]+$", src):
                continue
            v, reason = safe_value(src, global_ns, {})
            if not reason and _is_char_obj(v):
                rc = Cond(u"%s.id == char1.id" % src, kind="role")
                rc.data["expr"] = src
                roles.append(rc)

    lns_lit = dict(local_ns)
    lns_lit.update(_chain_literals(index, chain, target_idx))
    conds = drop_unreachable_guards(conds, global_ns, lns_lit)
    conds = refine_identity(conds, global_ns, local_ns)
    if conds is None:
        return None
    # "event_char = miriam" before calling a label about event_char: the
    # scene is about someone else.
    subj = mk.subject.strip().split("=", 1)[-1].strip()
    setter = None
    for i in range(1, len(chain)):
        if subj in chain[i].edge.charvars:
            setter = chain[i].edge.charvars[subj]
    if setter is not None and re.match(r"^[a-z]+$", setter):
        # Only a named girl (event_char = miriam); char1 = event_char is her.
        v, reason = safe_value(setter, global_ns, {})
        if not reason and _is_char_obj(v) and (v.fname or "").lower() == setter and v is not char:
            return None
    preset = {}
    if chain[target_idx].edge is not None:
        for var, src in chain[target_idx].edge.charvars.items():
            v, reason = safe_value(src, global_ns, {})
            if not reason and _is_char_obj(v):
                preset[var] = src
    named_other = any(other_char_label(h.label, char, store) for h in chain[1:])

    entry_return = ""
    entry = "direct"
    if chain[0].label == MAIN_LOOP_LABEL and len(chain) > 1:
        entry = "main"
        for src, negated in _edge_conditions(chain[1].edge):
            if negated:
                continue
            m = re.search(r'(?:_return|action_event)\s*==\s*["\'](\w+)["\']', src)
            if m:
                entry_return = m.group(1)

    # "Yvette blue underwear" given to her, or Yvette's lingerie quest asked
    # about her: a route meant for another girl.
    for c in conds:
        if not c.negated and _names_other_girl(c.src, char, store, also):
            return None

    # Fixed values handed to the target label (play_poker(..., i_appointment=True)):
    # a route that needs them to be different is impossible.
    literal = _chain_literals(index, chain, target_idx)
    if literal:
        lns = dict(local_ns)
        lns.update(literal)
        for c in conds:
            names = set(re.findall(r"\b[A-Za-z_]\w*\b", c.src))
            if names and names <= set(literal) | {"True", "False", "None", "not", "and", "or"}:
                v, _r = safe_eval(c.expr, {}, lns)
                if v is False:
                    return None

    score = len(chain) * 3 + len(conds) + 2 * len([c for c in conds if c.kind == "choice"])
    for c in conds:
        # Needs a scene the game never shows her: a dead end in the game.
        if c.kind == "seen" and c.data.get("want") and is_char_var(c.data.get("who"), char, store) \
                and not can_mark(index, c.data["what"], c.data["name"], char, store):
            score += 300
    for c in conds:
        # "seen this one before": a repeat of the scene; prefer the first time.
        if c.kind == "seen" and c.data.get("name") == mk.name and c.data.get("want"):
            v, _r = safe_eval(c.expr, global_ns, local_ns)
            if v is False:
                score += 500
    # A roll on the way is worse than a choice you make, an unlikely one more so.
    for c in conds:
        if c.kind == "chance":
            p = roll_p(c, global_ns, local_ns)
            score += 3 + (int(round(10 * (1.0 - p))) if p is not None else 3)
    for c in conds:
        # Prefer routes that are possible now (not "the girl from the plane
        # on day 1-2" when it is day 20).
        if re.search(r"\b(char[2-9]|event_char\d)\b", c.src):
            # char2: the guide starts it with nobody else picked (char2 is her)
            alone = dict(local_ns)
            alone.update(("char%d" % k, local_ns.get("char1")) for k in range(2, 10))
            v, _r = safe_eval(c.expr, global_ns, alone)
            if v is False:
                score += 12
        elif c.kind not in ("choice", "dispatch"):
            v, _r = safe_eval(c.expr, global_ns, local_ns)
            if v is None and c.kind == "skill":
                p = skill_pass(c, global_ns, local_ns)
                v = False if p == 0.0 else v
            if v is False:
                score += 12
    me = (getattr(char, "fname", "") or "").lower()
    if me and any(me in text(h.label).lower().split("_") for h in chain[1:]):
        # Her own version (new_arrival_event_miriam_mercedes).
        score -= 100
    if named_other:
        # Labels are usually named after their character; prefer a route
        # that does not go through another character's label.
        score += 200
    if entry == "main":
        score -= 100
        if entry_return:
            score -= 50
    argfix, pick_values = {}, []
    if mk.dyn:
        dyn = _dyn_constraints(index, mk, chain, target_idx)
        if dyn is None:
            return None
        argfix, pick_values = dyn
    for hop in chain[target_idx + 1:]:
        if hop.edge is not None and hop.edge.pick_value:
            pick_values.append(hop.edge.pick_value)  # renpy.call(l_call) drawn from a list
    for rc in roles:
        if not role_possible(index, store, rc.data["expr"], char):
            score += 300  # she never has that job in the game
    conds = roles + conds
    return {"score": score, "marker": mk, "chain": chain, "steps": steps, "conds": conds,
            "skipped": skipped, "entry": entry, "entry_return": entry_return,
            "target_label": chain[target_idx].label, "target_idx": target_idx,
            "preset": preset, "argfix": argfix, "pick_values": pick_values}


RANDOM_SRC_RE = re.compile(r"renpy\.random\.(choice|randint)\(|\.get_\w+\(\s*\)")


def _typed(value):
    return int(value) if re.match(r"^-?\d+$", value) else value


def _label_reads(index, label):
    """l_ variables a label reads (in its code and its conditions)."""
    cache = index.__dict__.setdefault("_reads_cache", {})
    if label not in cache:
        names = set()
        for s in _label_sources(index, label):
            names |= set(re.findall(r"\bl_\w+", s))
        node = index.labels.get(label)
        for st in _all_nodes(node.block if node is not None else []):
            if cls_name(st) == "If":
                for c, _b in st.entries:
                    names |= set(re.findall(r"\bl_\w+", text(c)))
            for attr in ("what", "line"):
                names |= set(re.findall(r"\[(l_\w+)\]", text(getattr(st, attr, "") or "")))
        cache[label] = names
    return cache[label]


def _reads_caller_locals(index, chain, t):
    label = chain[t].label
    own = index.label_locals.get(label, set()) | set(p for p, _d in index.params.get(label, []))
    caller = chain[t - 1].label
    if caller == MAIN_LOOP_LABEL:
        return False
    return bool((_label_reads(index, label) - own) & index.label_locals.get(caller, set()))


def _dyn_constraints(index, mk, chain, target_idx):
    """
    A name put together while the game runs (Clothes1_show_posing): which
    values its parts must have. Returns (argfix, picks) - parameters of the
    target label and values a random draw must give - or None when the
    route hands a different value (a call with 2 for Clothes1).
    """
    argfix, picks = {}, []
    for var, value in sorted(mk.dyn.items()):
        want = _typed(value)
        j = None
        for k in range(len(chain) - 1, -1, -1):
            if chain[k].label == mk.owner:
                j = k
                break
        name, handled = var, False
        while j is not None:
            params = index.params.get(chain[j].label, [])
            names = [p for p, _d in params]
            if name not in names:
                break
            if j <= target_idx:
                argfix[name] = want  # the guide hands it over itself
                handled = True
                break
            edge = chain[j].edge
            if edge is None or edge.how not in ("call", "python"):
                handled = True  # can't tell
                break
            pos = [a for a in edge.args if _split_kw(a)[0] is None]
            kws = dict(_split_kw(a) for a in edge.args if _split_kw(a)[0])
            i = names.index(name)
            src = kws.get(name) or (pos[i] if i < len(pos) else params[i][1])
            src = (src or "").strip()
            if re.match(r"""^(-?\d+|"[^"]*"|'[^']*')$""", src):
                if text(safe_value(src, {}, {})[0]) != value:
                    return None
                handled = True
                break
            if not re.match(r"^\w+$", src):
                handled = True
                break
            name, j = src, j - 1
        src = mk.dyn_src.get(var)
        if not handled and src is None:
            # Set by the label that calls this one (l_dress = char1.get_office_clothes()).
            rx = re.compile(r"^\s*%s\s*=(?!=)\s*(.+?)\s*$" % re.escape(var), re.M)
            for hop in chain:
                for s in _label_sources(index, hop.label):
                    for m in rx.finditer(s):
                        if RANDOM_SRC_RE.search(m.group(1)):
                            src = m.group(1)
        if not handled and RANDOM_SRC_RE.search(src or ""):
            picks.append(want)
    return argfix, picks


def _step_lust(index, cond):
    if cond.step is None:
        return ()
    return index.node_lust.get(id(cond.step[1]), ())


def lust_gain(cond, global_ns, local_ns):
    """
    Player lust gained in the scene before this condition is checked.
    Returns (gain, exact) - exact is False when some change is unknown.
    """
    gain, exact = 0, True
    for src in getattr(cond, "lust_before", ()):
        v, reason = safe_value(src, global_ns, local_ns)
        try:
            gain += int(v)
        except Exception:
            exact = False
    return gain, exact


def lust_steps(cond, global_ns, local_ns):
    """The single lust changes before the check (unknown ones left out)."""
    out, exact = [], True
    for src in getattr(cond, "lust_before", ()):
        v, reason = safe_value(src, global_ns, local_ns)
        try:
            out.append(int(v))
        except Exception:
            exact = False
    return out, exact


def erection_odds(lust, has_erection, steps, overdose=False):
    """
    Chance to have an erection when the scene checks, following the game:
    each lust gain that ends at 60 or more rolls lust // 3 against 1..80,
    a drop below 90 takes the erection away.
    Returns (probability, lust at the check).
    """
    p = 1.0 if has_erection else 0.0
    level = lust
    for g in steps:
        level = max(0, min(100, level + g))
        if g < 0 and level < 90:
            p = 0.0
        elif g > 0 and level >= 60 and not overdose:
            hit = max(0, level // 3 - 1) / 80.0
            p = p + (1.0 - p) * hit
    return p, level


def _identity_term(node):
    """Is this a comparison like char1.id == ivy.id / char1.fname == "Ivy"?"""
    if cls_name(node) == "UnaryOp" and cls_name(node.op) == "Not":
        node = node.operand
    if cls_name(node) == "Call" and _dotted(node.func) in ("renpy.has_label", "renpy.loadable") \
            and any(n in unparse(node) for n in CHAR_NAMES):
        return True  # her own version of a label or picture
    if cls_name(node) != "Compare" or len(node.ops) != 1:
        return False
    if cls_name(node.ops[0]) not in ("Eq", "NotEq", "Is", "IsNot", "In", "NotIn"):
        return False
    for side in (node.left, node.comparators[0]):
        if cls_name(side) == "Attribute" and side.attr in ("id", "fname") \
                and cls_name(side.value) == "Name" and side.value.id in CHAR_NAMES:
            return True
        if cls_name(side) == "Name" and side.id in CHAR_NAMES:
            return True
    return False


def _runtime_char(node):
    """char2, event_char2: set while the game runs, not known in advance."""
    return bool(re.search(r"\b(char[2-9]|event_char\d)\b", unparse(node)))


class _Unknown(object):
    """Someone the guide can't know in advance: every check on her is unknown."""

    def __getattr__(self, name):
        raise Unsafe("unknown character")


_UNKNOWN = _Unknown()


def _carry(new, old):
    new.lust_before = getattr(old, "lust_before", ())
    if getattr(old, "outer", None):
        new.outer = old.outer
    return new


def refine_identity(conds, global_ns, local_ns):
    """
    Separates "which character" checks from the rest of each condition.

    Returns the refined list, or None when a condition shows that the path
    belongs to another character.
    """
    out = []
    for c in conds:
        if c.kind == "choice":
            out.append(c)
            continue
        try:
            tree = pyast.parse(c.src.replace("<>", "!="), mode="eval").body
        except SyntaxError:
            out.append(c)
            continue
        if cls_name(tree) == "BoolOp" and cls_name(tree.op) == "Or" and not c.negated:
            # "char2 is someone else, or a roll": her own branches decide.
            alts = list(tree.values)
            hit, rest = False, []
            for x in alts:
                if _identity_term(x) and not _runtime_char(x):
                    v, _r = safe_eval(unparse(x), global_ns, local_ns)
                    if v is True:
                        hit = True
                    elif v is not False:
                        rest.append(x)
                else:
                    rest.append(x)
            if hit:
                continue
            if not rest:
                return None
            if len(rest) < len(alts):
                c = _carry(Cond(" or ".join(_paren(x, ("BoolOp",)) for x in rest), False, step=c.step), c)
            out.append(c)
            continue
        terms = list(tree.values) if (cls_name(tree) == "BoolOp" and cls_name(tree.op) == "And") else [tree]
        ids = [x for x in terms if _identity_term(x) and not _runtime_char(x)]
        if not ids:
            out.append(c)
            continue
        ids_ok, ids_known = True, True
        for x in ids:
            v, _r = safe_eval(unparse(x), global_ns, local_ns)
            if v is False:
                ids_ok = False
            elif v is not True:
                ids_known = False
        rest = [x for x in terms if not _identity_term(x)]
        if not c.negated:
            if not ids_ok:
                return None
            for x in rest:
                for a, neg in _atoms(x, False):
                    out.append(_carry(Cond(a, neg, step=c.step), c))
        else:
            if not ids_ok or not rest:
                if not rest and ids_ok and ids_known:
                    return None  # "not (this character)"
                continue
            if len(rest) == 1:
                for a, neg in _atoms(rest[0], True):
                    out.append(_carry(Cond(a, neg, step=c.step), c))
            else:
                out.append(_carry(Cond(" and ".join(_paren(x, ("BoolOp",)) for x in rest), True, step=c.step), c))
    return out


def _edge_conditions(edge):
    out = []
    for st in edge.path:
        out.extend(step_conditions(st))
    return out


def _direct_args(index, label, fixed=None):
    """Arguments for calling a label directly, or None if impossible."""
    out = []
    for i, (pname, default) in enumerate(index.params.get(label, [])):
        low = pname.lower()
        if fixed and pname in fixed:
            out.append((pname if default is not None else None, repr(fixed[pname])))
            continue
        if default is not None:
            continue
        charlike = "char" in low or "girl" in low or "opponent" in low
        if i == 0 or low in CHAR_NAMES:
            out.append((None, "__char__"))
        elif charlike and may_be_same(index, label, pname):
            out.append((None, "__char__"))  # char2 is her too when nobody else is around
        elif charlike:
            out.append((None, "__other_char__"))
        elif "location" in low:
            out.append((None, "location"))
        elif "actions_left" in low or low in ("ap", "actionpoints"):
            out.append((None, "actions_left"))
        elif "return" in low:
            out.append((None, "__return__"))
        else:
            return None
    return out


def may_be_same(index, label, pname):
    """Does the label handle char2 being char1 (if char1.id <> char2.id: ...)?"""
    p = re.escape(pname)
    rx = re.compile(r"\bchar1(\.id)?\s*(<>|!=|==|is)\s*%s\b|\b%s(\.id)?\s*(<>|!=|==|is)\s*char1\b" % (p, p))
    node = index.labels.get(label)
    if node is None:
        return False
    for st in _all_nodes(node.block):
        if cls_name(st) == "If" and any(rx.search(text(c)) for c, _b in st.entries):
            return True
    return any(rx.search(s) for s in _label_sources(index, label))


def args_reason(index, label):
    """Why a label cannot be started directly, in plain words."""
    missing = [p for p, d in index.params.get(label, []) if d is None]
    names = ", ".join(p.replace("l_", "").replace("_", " ") for p in missing[1:]) or "details"
    return ("The game starts this one in the middle of another scene and hands it "
            "details only that scene knows (%s), so it can't be started on its own. "
            "Play it the normal way in the game." % names)


def chars_in_label(label, char, store):
    """
    Girls named in a label, in order (lesbian_event_desire_jessica ->
    [desire, jessica]). Empty when the label names fewer than two.
    """
    if store is None or not label:
        return []
    found = []
    for tok in text(label).lower().split("_"):
        obj = getattr(store, tok, None)
        if _is_char_obj(obj) and obj not in found:
            found.append(obj)
    if len(found) < 2 or char not in found:
        return []
    return found


def needs_two_girls(index, label):
    return any(src == "__other_char__" for _k, src in (_direct_args(index, label) or []))


def is_char_var(name, char, store):
    """Does the variable name refer to `char` (char1, or e.g. alice)?"""
    if name in CHAR_NAMES:
        return True
    if store is None or char is None:
        return False
    return getattr(store, name, None) is char


def _fill_location(plan, meta, char, store=None):
    loc = ""
    if meta is not None:
        loc = getattr(meta, "location", "") or ""
    if loc == "Girl_room" and char is not None:
        loc = char.fname + "_room"
    if not loc and plan.entry_return:
        loc = location_from_return(plan.entry_return)
    if not loc and char is not None and plan.index is not None:
        # visit_girls_room_main: location = char1.fname + "_room"
        for hop in plan.hops[1:]:
            if any(ROOM_LOC_RE.search(s) for s in _label_sources(plan.index, hop.label)):
                loc = char.fname + "_room"
                break
    if not loc:
        for c in plan.conds:
            if c.kind == "location" and c.data.get("op") == "==":
                loc = c.data["location"]
            elif c.kind == "char_location" and c.data.get("op") == "==" \
                    and is_char_var(c.data.get("who"), char, store):
                loc = c.data["location"]
    plan.location = loc


def resolve_args(index, plan, char, store):
    """Values for calling plan.target_label (after the scene is set up)."""
    global_ns = store.__dict__
    ns = dict((n, char) for n in CHAR_NAMES)
    ret = "goto_%s" % (plan.location or "player_room")
    ns["_return"] = ret
    ns["i_return"] = ret
    if plan.target_idx >= 2:
        # Parameters of the label that calls the target.
        _v, _kw, ns = _evaluate_chain(index, plan.hops, plan.target_idx - 1, char,
                                      global_ns, ns, plan.location)
    values, kwvalues = [], {}
    girls = chars_in_label(plan.target_label, char, store)
    for kw, src in plan.call_args:
        if src == "__char__":
            v = girls[0] if girls else char
        elif src == "__other_char__" or (re.match(r"^\w*char\w*2$", src.strip()) and src.strip() not in CHAR_NAMES):
            others = [g for g in girls[1:]] if girls else []
            v = others.pop(0) if others else None
            girls = [girls[0]] + others if girls else girls
            params = index.params.get(plan.target_label, [])
            pname = kw or (params[len(values)][0] if len(values) < len(params) else "")
            if v is None and pname and may_be_same(index, plan.target_label, pname):
                v = char
            if v is None:
                # Someone else on the island (the other girl of a contest round).
                for other in getattr(store, "list_of_characters", []):
                    if other is not char and other not in values and other not in kwvalues.values():
                        v = other
                        break
        elif src == "__return__":
            v = ret
        else:
            v, reason = safe_value(src, global_ns, ns)
            if reason:
                v = _guess_value(src, char, plan.location)
            elif _is_char_obj(v) and v is not char and (
                    (_is_local_char_var(src) and src not in ns) or "." in src):
                # A leftover local variable, or a role like jobs.doctor:
                # the scene is about the chosen character.
                v = char
        if kw:
            kwvalues[kw] = v
        else:
            values.append(v)
    # Clothes1_show_posing: the 1 the label must be handed.
    for i, (pname, _d) in enumerate(index.params.get(plan.target_label, [])):
        if pname in plan.argfix:
            if i < len(values):
                values[i] = plan.argfix[pname]
            else:
                kwvalues[pname] = plan.argfix[pname]
    return values, kwvalues


def quest_step_markers(index, qname, state):
    """
    Markers that move quest `qname` on from `state`.

    Prefers statements guarded by get_quest_state(qname) == state.
    """
    exact, loose = [], []
    for mk in index.markers_for("quest", qname):
        if (state < 0) != (mk.op == "add"):
            continue
        guard = None
        for c in path_conds(mk.path):
            if c.kind == "quest" and c.data["quest"] == qname:
                guard = (c.data["op"], c.data["value"])
        if guard is None:
            loose.append(mk)
            continue
        op, v = guard
        ok = {"==": state == v, "!=": state != v, ">=": state >= v, "<=": state <= v,
              ">": state > v, "<": state < v}.get(op, False)
        if ok and op == "==":
            exact.append(mk)
        elif ok:
            loose.append(mk)
    return exact + loose


def index_params(plan, label):
    return plan.index.params.get(label, []) if plan.index is not None else []


def default_values(plan, store):
    """Values of the default parameters of the labels on the path."""
    out = {}
    for pname, src in plan.defaults.items():
        v, reason = safe_value(src, store.__dict__ if store is not None else {}, {})
        if not reason:
            out[pname] = v
    # Plain values the labels below the target are handed on the way
    # (contest_round(..., i_cheat_probability=20)).
    for hop in plan.hops[plan.target_idx + 1:]:
        if hop.edge is None:
            continue
        params = [p for p, _d in index_params(plan, hop.label)]
        pos = 0
        for arg in hop.edge.args:
            kw, src = _split_kw(arg)
            name = kw or (params[pos] if pos < len(params) else None)
            if kw is None:
                pos += 1
            if name and LITERAL_RE.match(src.strip()):
                out[name] = safe_value(src, {}, {})[0]
    # Keyword arguments the guide passes (play_poker(..., i_appointment=True)).
    for kw, src in plan.call_args:
        if kw:
            v, reason = safe_value(src, store.__dict__ if store is not None else {}, {})
            if not reason:
                out[kw] = v
    return out


def step_values(index, cond, store):
    """Flags set by the label before the condition's statement."""
    out = {}
    if cond.step is None:
        return out
    for name, src in index.node_assigns.get(id(cond.step[1]), {}).items():
        v, reason = safe_value(src, store.__dict__ if store is not None else {}, {})
        if not reason:
            out[name] = v
    return out


LIST_COND_RE = re.compile(r"\blen\(|\bcounter\b|\blist_(?!of_characters\b|of_phone_characters\b)\w+|\w\[\w*\]\.")


def _builds_list(node, idx):
    try:
        return bool(LIST_COND_RE.search(text(node.entries[idx][0])))
    except Exception:
        return False


def forceable_steps(index, steps):
    """
    Steps Guided mode may force. An if that reads what the scene itself
    sets up (the list of contest girls, a counter) is left alone: forcing
    it would break the scene (drawing from an empty list).
    """
    out = []
    for st in steps:
        kind, node, i = st
        if kind in ("if", "guard"):
            try:
                src = " ".join(text(e[0]) for e in node.entries[:i + 1])
            except Exception:
                src = ""
        out.append(st)
    return out


def uses_label_locals(index, cond):
    """Does the condition read variables its own label sets while running?"""
    if cond.step is None:
        return False
    owner = index.node_owner.get(id(cond.step[1]))
    names = index.label_locals.get(owner)
    if not names:
        return False
    known = index.node_assigns.get(id(cond.step[1]), {})
    used = set(re.findall(r"\b([A-Za-z_]\w*)\b", cond.src))
    return bool((used & names) - set(known))


def auto_succeed_kwargs(index, plan):
    """Keyword arguments that make the target label skip its checks."""
    out = {}
    for pname, default in index.params.get(plan.target_label, []):
        if ("auto_succeed" in pname.lower() or "auto_success" in pname.lower()) and default is not None:
            out[pname] = True
    return out


def effect_wanted(cond):
    """For an effect condition: should the effect be active?"""
    op, v = cond.data["op"], cond.data["value"]
    return {"==": v > 0, "!=": v == 0, ">": True, ">=": v > 0,
            "<": False, "<=": v > 0}.get(op, True)


def roll_p(cond, global_ns, local_ns):
    """renpy.random.randint(1, 13) > x: the chance (0-1) it goes the needed way."""
    try:
        tree = pyast.parse(cond.src.replace("<>", "!="), mode="eval").body
    except SyntaxError:
        return None
    if cls_name(tree) != "Compare" or len(tree.ops) != 1:
        return None
    left, right, op = tree.left, tree.comparators[0], cls_name(tree.ops[0])
    if "randint(" not in unparse(left):
        left, right = right, left
        op = {"Lt": "Gt", "Gt": "Lt", "LtE": "GtE", "GtE": "LtE"}.get(op, op)
    if cls_name(left) != "Call" or "randint" not in unparse(left.func) or len(left.args) < 2:
        return None
    try:
        a, b = [int(safe_value(unparse(x), global_ns, local_ns)[0]) for x in left.args[:2]]
        v = safe_value(unparse(right), global_ns, local_ns)[0]
        test = {"Eq": lambda x: x == v, "NotEq": lambda x: x != v, "Lt": lambda x: x < v,
                "LtE": lambda x: x <= v, "Gt": lambda x: x > v, "GtE": lambda x: x >= v}[op]
        p = len([x for x in range(a, b + 1) if test(x)]) / float(b - a + 1)
    except Exception:
        return None
    return 1.0 - p if cond.negated else p


SKILL_GETTER = {"sneaking": "get_hacking"}


def skill_pass(cond, global_ns, local_ns):
    """Chance (0-1) that the player's skill check goes the needed way now."""
    m = re.search(r"player\.check_(\w+)\((.*?)(?:,|\)\s*(?:==|!=|\)|$))", cond.src)
    player = global_ns.get("player")
    if not m or player is None:
        return None
    skill = m.group(1)
    try:
        level = int(safe_value(m.group(2), global_ns, local_ns)[0])
        cur = getattr(player, SKILL_GETTER.get(skill, "get_" + skill))()
    except Exception:
        return None
    if skill == "endurance":
        p = 1.0 if cur >= level else 0.0
    else:
        p = 1.0 if cur > level else (0.5 if cur == level else (0.25 if cur == level - 1 else 0.0))
    return p if check_must_pass(cond) else 1.0 - p


def check_must_pass(cond):
    """For a stat check condition: must the check succeed?"""
    n = norm(cond.src)
    base = not (n.endswith("==False") or n.endswith("!=True") or n.startswith("not"))
    return base != cond.negated


ACTION_RETURN_RE = re.compile(r'Return\(\s*["\'](do_\w+)["\']')
ACTION_TEXT_RES = (re.compile(r'["\']0\d_([^"\']+)["\']'),
                   re.compile(r'Action\s*\(\s*["\']([^"\']+)["\']'))


def collect_action_texts(screen_asts):
    """
    Reads the game's screens for the text of each main loop action button,
    e.g. "do_others" -> "Talk to [selected_char.fname] about other topics."
    """
    out = {}

    def visit(node):
        kw = getattr(node, "keyword", None) or []
        action = tip = None
        for name, expr in kw:
            expr = text(expr)
            if name == "action":
                m = ACTION_RETURN_RE.search(expr)
                if m:
                    action = m.group(1)
            elif name in ("tooltip", "hovered"):
                for rx in ACTION_TEXT_RES:
                    m = rx.search(expr)
                    if m:
                        tip = m.group(1)
                        break
        if action and tip:
            tip = re.split(r"\{color|\\n", tip)[0].strip()
            if tip and len(tip) > len(out.get(action, "")):
                out[action] = tip
        for child in getattr(node, "children", None) or []:
            visit(child)
        for entry in getattr(node, "entries", None) or []:
            if isinstance(entry, tuple) and len(entry) == 2:
                visit(entry[1])
    for root in screen_asts:
        try:
            visit(root)
        except Exception:
            pass
    return out


def action_text_for(texts, name):
    """Button text for a main loop action or a cooldown name."""
    if not name:
        return ""
    name = name[3:] if name.startswith("do_") else name
    parts = name.split("_")
    candidates = []
    for i in range(len(parts)):
        for j in range(len(parts), i, -1):
            candidates.append("do_" + "_".join(parts[i:j]))
    for cand in candidates:
        if cand in texts:
            return texts[cand]
    return ""


def _python_source(node):
    code = getattr(node, "code", None)
    return text(getattr(code, "source", code))


def sexting_rules(index, label="check_create_sexting_message"):
    """
    Reads the game's own rules for the picture messages a girl sends
    (levels 100..400): the conditions checked first, the stat condition
    of each level and the range of message texts used for it.
    """
    out = {"guards": [], "levels": {}, "texts": {}}
    node = index.labels.get(label)
    if node is None:
        return out
    for st in node.block or []:
        c = cls_name(st)
        if c == "If":
            for cond, blk in st.entries:
                for sub in blk or []:
                    m = re.search(r"l_level\s*=\s*(\d+)", _python_source(sub)) \
                        if cls_name(sub) == "Python" else None
                    if m:
                        out["levels"][int(m.group(1))] = text(cond)
                if blk and Index._terminal(blk[-1]) and not out["levels"]:
                    out["guards"].append(text(cond))
    for st in _all_nodes(node.block):
        if cls_name(st) == "Python":
            for m in re.finditer(r"add_queued_sexting\(\s*l_sexting_image\.image\s*,\s*renpy\.random\.randint\(\s*(\d+)\s*,\s*(\d+)",
                                 _python_source(st)):
                a, b = int(m.group(1)), int(m.group(2))
                out["texts"].setdefault(a // 100 * 100, (a, b))
    return out


def _all_nodes(block):
    for node in block or []:
        yield node
        for sub in Index._sub_blocks(node):
            for x in _all_nodes(sub):
                yield x


def random_exit_steps(index, label):
    """Steps that skip the random "you find nothing" exits of a label."""
    out = []
    node = index.labels.get(label)
    if node is None:
        return out
    for st in _all_nodes(node.block):
        if cls_name(st) != "If":
            continue
        for i, (cond, blk) in enumerate(st.entries):
            if "random" in text(cond) and blk and Index._terminal(blk[-1]):
                out.append(("guard", st, i))
    return out


# ---------------------------------------------------------------------------
# Forcing a path (guided mode / replay)
# ---------------------------------------------------------------------------

class Patcher(object):
    """Temporarily rewrites conditions on a path so that it is taken."""

    def __init__(self):
        self.saved = []

    @staticmethod
    def _technical(node, idx):
        """Checks of the game's own files (renpy.has_label...) are never forced."""
        try:
            srcs = [text(e[0]) for e in node.entries[:idx + 1]]
        except Exception:
            return False
        # Poker: the guide wins it hand by hand instead (each undress scene).
        return any("renpy.has_label" in s or "renpy.loadable" in s or "g_poker_game" in s for s in srcs)

    @staticmethod
    def _soften(src):
        """
        "len(pool) > 0 and renpy.random.randint(1, 100) < 50" -> "len(pool) > 0 and True":
        the rolls are forced, the list the scene builds is left to the scene.
        Returns None when there is no roll to force.
        """
        try:
            tree = pyast.parse(text(src).replace("<>", "!="), mode="eval").body
        except SyntaxError:
            return None
        terms = list(tree.values) if (cls_name(tree) == "BoolOp" and cls_name(tree.op) == "And") else [tree]
        changed, out = False, []
        for x in terms:
            if "random" in unparse(x) and "no_char" not in unparse(x):
                out.append("True")
                changed = True
            else:
                out.append(unparse(x))
        return " and ".join("(%s)" % x if " or " in x else x for x in out) if changed else None

    def force(self, steps):
        for kind, node, idx in steps:
            if kind in ("if", "guard") and self._technical(node, idx):
                continue
            if kind in ("if", "guard") and (_builds_list(node, idx) or "no_char" in text(node.entries[idx][0])):
                soft = self._soften(node.entries[idx][0])
                if soft is None:
                    continue
                if kind == "if":
                    for j in range(idx):
                        self._set_entry(node, j, u"False")
                    self._set_entry(node, idx, soft)
                continue
            if kind == "if":
                for j in range(idx):
                    self._set_entry(node, j, u"False")
                self._set_entry(node, idx, u"True")
            elif kind == "guard":
                self._set_entry(node, idx, u"False")
            elif kind == "elseguard":
                for j in range(idx):
                    soft = self._soften(node.entries[j][0])
                    if soft is not None:
                        self._set_entry(node, j, soft)
            elif kind == "menu":
                item = node.items[idx]
                if text(item[1]).strip() != "True":
                    self.saved.append(("menu", node, idx, item))
                    node.items[idx] = (item[0], u"True", item[2])

    def _set_entry(self, node, j, value):
        entry = node.entries[j]
        if text(entry[0]).strip() == value:
            return
        self.saved.append(("if", node, j, entry))
        node.entries[j] = (value, entry[1])

    def restore(self):
        for kind, node, j, entry in reversed(self.saved):
            if kind == "if":
                node.entries[j] = entry
            else:
                node.items[j] = entry
        self.saved = []

    @property
    def active(self):
        return bool(self.saved)


# ---------------------------------------------------------------------------
# Runtime state (module level, so it is never written into save files)
# ---------------------------------------------------------------------------

RUNTIME = {
    "index": None,        # Index, built on first use
    "index_error": "",
    "patcher": Patcher(),
    "highlight": {},      # menu node name -> set of item indexes to highlight
    "run": None,          # dict while a scene started by the guide is running
    "plans": {},          # cache of plans
    "details": {},        # cache of detail panels
}
