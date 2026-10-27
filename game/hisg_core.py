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

import re
import ast as pyast

try:
    string_types = (basestring,)  # noqa: F821 (Python 2)
except NameError:  # Python 3
    string_types = (str,)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARK_RE = re.compile(r'(\w+)\s*\.\s*add_(scene|event|appointment)_seen\(\s*["\']([^"\']+)["\']')
QUEST_RE = re.compile(r'player\s*\.\s*(inc_quest_state|set_quest_state|add_quest)\(([^()]*(?:\([^()]*\)[^()]*)*)\)')
PYCALL_RE = re.compile(r'renpy\s*\.\s*(call|jump)\(\s*["\']([\w\.]+)["\']')

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
SAFE_FUNCS = ("len", "int", "unicode", "str", "abs", "min", "max", "float", "bool")
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
    """Condition source without whitespace, '<>' written as '!='."""
    return re.sub(r"\s+", "", text(src)).replace("<>", "!=")


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
        return "%s %s %s" % (_paren(n.left, ("BoolOp", "Compare")), _BINOPS.get(cls_name(n.op), "?"),
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
            ctx = {"owner": name, "entry": name, "entry_path": ()}
            self._walk(labels[name].block, ctx, ())

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
        for node in block or []:
            self.statement_count += 1
            c = cls_name(node)
            if c == "If":
                for i, entry in enumerate(node.entries):
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
                    ctx["entry_path"] = path
                self._walk(node.block, ctx, path)
            elif c in ("Python", "EarlyPython"):
                self._scan_python(node, ctx, path)
            elif c == "Call":
                args = self._call_args(node)
                rel = self._rel(ctx, path)
                if getattr(node, "expression", False):
                    self.expr_edges.append(Edge(None, ctx["entry"], rel, args, expr=text(node.label), node=node))
                else:
                    self._add_edge(Edge(text(node.label), ctx["entry"], rel, args, node=node))
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
            if c not in ("Translate", "EndTranslate") and not (c == "Label" and text(node.name).startswith("_")):
                prev = node

    def _guards(self, node):
        out = []
        for i, (cond, blk) in enumerate(node.entries):
            if text(cond).strip() == "True":
                continue
            if blk and self._terminal(blk[-1]):
                out.append(("guard", node, i))
        return tuple(out)

    def _add_edge(self, edge):
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
        for m in MARK_RE.finditer(src):
            subj, kind, name = m.group(1), m.group(2), m.group(3)
            self.markers.setdefault((kind, name), []).append(
                Marker(kind, name, subj, owner, entry, path, rel, node))
        for m in QUEST_RE.finditer(src):
            func, args = m.group(1), split_args(m.group(2))
            if not args:
                continue
            qname = strip_quotes(args[0])
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
            self.markers.setdefault(("quest", qname), []).append(
                Marker("quest", qname, about, owner, entry, path, rel, node, value=value, op=op))
        for m in PYCALL_RE.finditer(src):
            # renpy.call("label", ...) inside Python: arguments are unknown.
            self._add_edge(Edge(m.group(2), entry, rel, [], how="python", node=node))

    # -- queries -------------------------------------------------------------

    def markers_for(self, kind, name):
        return list(self.markers.get((kind, name), []))


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

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
    return out


def path_conds(steps):
    conds = []
    for st in steps:
        for src, negated in step_conditions(st):
            if negated is None:
                conds.append(Cond(src, kind="choice", step=st))
                continue
            for a, neg in atoms(src, negated):
                conds.append(Cond(a, neg, step=st))
    return conds


OUTFIT_RE = re.compile(r'^(\w+)\.(swimwear|nightwear|dinerwear|receptionwear|doctorwear)(==|!=|>=|<=|>|<)(\d+)$')
ALONE_RE = re.compile(r'^len\(list_of_chars_display_3\)(==|<=|<|>|>=|!=)(\d+)$')
EFFECT_RE = re.compile(r'^player\.get_effect_state\(["\'](\w+)["\']\)(==|!=|>=|<=|>|<)(\d+)$')
CHARLOC_RE = re.compile(r'^(\w+)\.locations\[actions_left-1\](==|!=)["\'](\w+)["\']$')
PLOC_RE = re.compile(r'^(?:i_)?location\d*(==|!=)["\'](\w+)["\']$')
QUESTCOND_RE = re.compile(r'^player\.get_quest_state\(["\']([^"\']+)["\'],(\w+)\)(==|!=|>=|<=|>|<)(-?\d+)$')
SEEN_RE = re.compile(r'^(\w+)\.get_(scene|event|appointment)_seen\(["\']([^"\']+)["\']\)(?:(==|!=)(True|False))?$')
SEEN_TIMES_RE = re.compile(r'^(\w+)\.get_(scene|event|appointment)_seen_times\(["\']([^"\']+)["\'][^)]*\)(==|!=|>=|<=|>|<)(\d+)$')
ITEM_RE = re.compile(r'player\.has_item\(["\']([^"\']+)["\']')
IDENTITY_RE = re.compile(r'\b(char1|selected_char|event_char|i_char|l_char|char|i_girl)\s*(\.\s*(id|fname)\b|\s*(==|!=|<>|\bis\b|\bin\b))')
STAT_RE = re.compile(r'\.(check_affection|check_love|check_lust|check_tease_sexual|check_anger)\(')
SKILL_RE = re.compile(r'player\.(check_charm|check_strength|check_looks|check_hacking|check_sneaking|check_endurance)\(')
COOLDOWN_RE = re.compile(r'^(\w+)\.get_action_allowed\(["\']([^"\']+)["\']\)(?:(==|!=)(True|False))?$')
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
    m = CHARLOC_RE.match(n)
    if m:
        cond.kind = "char_location"
        d.update(who=m.group(1), op=CMP_FLIP[m.group(2)] if neg else m.group(2), location=m.group(3))
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
    m = ITEM_RE.search(n)
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
    if "_return" in n or "action_event" in n:
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
        self.launchable = False
        self.reason = ""
        self.notes = []

    def __repr__(self):
        return "<Plan %s %s via %s>" % (self.kind, self.name, self.target_label)


def _is_char_obj(obj):
    return obj is not None and hasattr(obj, "fname") and hasattr(obj, "locations")


def _arg_ok(arg, char, store):
    """False when the argument is a fixed character that is not `char`."""
    a = arg.split("=", 1)[1].strip() if re.match(r"^\w+\s*=[^=]", arg) else arg.strip()
    if not re.match(r"^\w+$", a) or store is None or char is None or a in CHAR_NAMES:
        return True
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
    if subj in params or subj in CHAR_NAMES:
        return True
    return _arg_ok(subj, char, store)


def find_chains(index, start, char, store, global_ns, local_ns, max_depth=9, max_chains=8):
    """
    Walks the call graph upwards from label `start`.

    Returns chains, each a list of Hop objects from the top label down to
    `start`. A chain stops at the main loop or at a label nobody calls.
    """
    results = []
    queue = [[Hop(start)]]
    expanded = 0
    while queue and len(results) < max_chains and expanded < 400:
        chain = queue.pop(0)
        expanded += 1
        top = chain[0].label
        seen = set(h.label for h in chain)
        edges = list(index.callers.get(top, []))
        for e in index.expr_edges:
            name, _r = safe_value(e.expr, global_ns, local_ns)
            if name == top:
                edges.append(Edge(top, e.caller, e.path, e.args, node=e.node))
        usable = [e for e in edges
                  if e.caller not in seen and all(_arg_ok(a, char, store) for a in e.args)]
        if top == MAIN_LOOP_LABEL or not usable or len(chain) > max_depth:
            results.append(chain)
            continue
        for e in usable:
            if e.caller == MAIN_LOOP_LABEL:
                results.append([Hop(MAIN_LOOP_LABEL), Hop(top, e)] + chain[1:])
        for e in usable:
            if e.caller != MAIN_LOOP_LABEL:
                queue.append([Hop(e.caller), Hop(top, e)] + chain[1:])
    return results


def location_from_return(value):
    v = value[3:] if value.startswith("do_") else value
    for loc in KNOWN_LOCATIONS:
        if v.startswith(loc + "_") or v == loc:
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
            if kw:
                kwvalues[kw] = v
            else:
                values.append(v)
        bound = _bind(index, hop.label, values, kwvalues)
        ns = dict(base_ns)
        ns.update(bound)
    return values, kwvalues, ns


def _guess_value(src, char, location):
    low = src.lower()
    if "return" in low:
        return "goto_%s" % (location or "player_room")
    if low in CHAR_NAMES:
        return char
    return None


def build_plan(index, kind, name, char, store, meta=None, marker=None):
    """
    Works out how to reach a target.

    `meta` is the game's own cl_image_with_desc entry (scenes_available...),
    used for the location, outfits and call_label it provides.
    """
    plan = Plan(kind, name)
    global_ns = store.__dict__ if store is not None else {}
    local_ns = dict((n, char) for n in CHAR_NAMES)

    markers = [marker] if marker is not None else index.markers_for(kind, name)
    markers = [m for m in markers if subject_ok(m, char, store, index)]

    candidates = []
    for mk in markers:
        for start, mk_steps in [(mk.entry, mk.relpath)]:
            for chain in find_chains(index, start, char, store, global_ns, local_ns):
                cand = _candidate(index, mk, chain, list(mk_steps), char, global_ns, local_ns, store)
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
                plan.reason = "The label needs arguments the guide cannot provide."
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
        plan.reason = "No route found in the game's script for this entry."
        _fill_location(plan, meta, char, store)
        return plan

    candidates.sort(key=lambda c: c["score"])
    best = candidates[0]
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
    env_kinds = ("outfit", "char_location", "location", "alone")
    plan.conds = [c for c in plan.skipped if c.kind in env_kinds] + plan.conds
    plan.skipped = [c for c in plan.skipped if c.kind not in env_kinds]
    t = plan.target_idx = best["target_idx"]
    for hop in plan.hops:
        for pname, default in index.params.get(hop.label, []):
            if default is not None:
                plan.defaults.setdefault(pname, default)
    _fill_location(plan, meta, char, store)

    if t == 0:
        args = _direct_args(index, plan.target_label)
        if args is None:
            plan.reason = "The label '%s' needs arguments the guide cannot provide." % plan.target_label
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


def _candidate(index, mk, chain, mk_steps, char, global_ns, local_ns, store=None):
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
    if target_idx == 0 and chain[0].label == MAIN_LOOP_LABEL and len(chain) > 1:
        target_idx = 1

    steps, conds = [], []
    for i in range(target_idx + 1, len(chain)):
        steps.extend(chain[i].edge.path)
        conds.extend(per_hop[i])
    steps.extend(mk_steps)
    conds.extend(path_conds(mk_steps))

    skipped = []
    for i in range(1, target_idx + 1):
        skipped.extend(per_hop[i])

    conds = refine_identity(conds, global_ns, local_ns)
    if conds is None:
        return None
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

    score = len(chain) * 3 + len(conds) + 2 * len([c for c in conds if c.kind == "choice"])
    if named_other:
        # Labels are usually named after their character; prefer a route
        # that does not go through another character's label.
        score += 200
    if entry == "main":
        score -= 100
        if entry_return:
            score -= 50
    return {"score": score, "marker": mk, "chain": chain, "steps": steps, "conds": conds,
            "skipped": skipped, "entry": entry, "entry_return": entry_return,
            "target_label": chain[target_idx].label, "target_idx": target_idx}


def _identity_term(node):
    """Is this a comparison like char1.id == ivy.id / char1.fname == "Ivy"?"""
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
        terms = list(tree.values) if (cls_name(tree) == "BoolOp" and cls_name(tree.op) == "And") else [tree]
        ids = [x for x in terms if _identity_term(x)]
        if not ids:
            out.append(c)
            continue
        ids_ok = True
        for x in ids:
            v, _r = safe_eval(unparse(x), global_ns, local_ns)
            if v is False:
                ids_ok = False
        rest = [x for x in terms if not _identity_term(x)]
        if not c.negated:
            if not ids_ok:
                return None
            for x in rest:
                for a, neg in _atoms(x, False):
                    out.append(Cond(a, neg, step=c.step))
        else:
            if not ids_ok or not rest:
                if not rest and ids_ok:
                    return None  # "not (this character)"
                continue
            if len(rest) == 1:
                for a, neg in _atoms(rest[0], True):
                    out.append(Cond(a, neg, step=c.step))
            else:
                out.append(Cond(" and ".join(unparse(x) for x in rest), True, step=c.step))
    return out


def _edge_conditions(edge):
    out = []
    for st in edge.path:
        out.extend(step_conditions(st))
    return out


def _direct_args(index, label):
    """Arguments for calling a label directly, or None if impossible."""
    out = []
    for i, (pname, default) in enumerate(index.params.get(label, [])):
        low = pname.lower()
        if default is not None:
            continue
        if i == 0 or low in CHAR_NAMES:
            out.append((None, "__char__"))
        elif "location" in low:
            out.append((None, "location"))
        elif "actions_left" in low or low in ("ap", "actionpoints"):
            out.append((None, "actions_left"))
        elif "return" in low:
            out.append((None, "__return__"))
        else:
            return None
    return out


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
    for kw, src in plan.call_args:
        if src == "__char__":
            v = char
        elif src == "__return__":
            v = ret
        else:
            v, reason = safe_value(src, global_ns, ns)
            if reason:
                v = _guess_value(src, char, plan.location)
        if kw:
            kwvalues[kw] = v
        else:
            values.append(v)
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


def default_values(plan, store):
    """Values of the default parameters of the labels on the path."""
    out = {}
    for pname, src in plan.defaults.items():
        v, reason = safe_value(src, store.__dict__ if store is not None else {}, {})
        if not reason:
            out[pname] = v
    return out


def auto_succeed_kwargs(index, plan):
    """Keyword arguments that make the target label skip its checks."""
    out = {}
    for pname, default in index.params.get(plan.target_label, []):
        if "auto_succeed" in pname.lower() and default is not None:
            out[pname] = True
    return out


def effect_wanted(cond):
    """For an effect condition: should the effect be active?"""
    op, v = cond.data["op"], cond.data["value"]
    return {"==": v > 0, "!=": v == 0, ">": True, ">=": v > 0,
            "<": False, "<=": v > 0}.get(op, True)


def check_must_pass(cond):
    """For a stat check condition: must the check succeed?"""
    n = norm(cond.src)
    base = not (n.endswith("==False") or n.endswith("!=True") or n.startswith("not"))
    return base != cond.negated


# ---------------------------------------------------------------------------
# Forcing a path (guided mode / replay)
# ---------------------------------------------------------------------------

class Patcher(object):
    """Temporarily rewrites conditions on a path so that it is taken."""

    def __init__(self):
        self.saved = []

    def force(self, steps):
        for kind, node, idx in steps:
            if kind == "if":
                for j in range(idx):
                    self._set_entry(node, j, u"False")
                self._set_entry(node, idx, u"True")
            elif kind == "guard":
                self._set_entry(node, idx, u"False")
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
