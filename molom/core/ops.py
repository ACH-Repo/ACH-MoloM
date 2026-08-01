"""Operator registry — the backbone of the F3 search (Blender-style).

Every user-facing action registers here once, with an `enabled` predicate
evaluated against the live app context, so the search can sieve smartly
(e.g. "Cycle bond" only lights up with exactly two atoms of one molecule
selected). docs/OPERATORS.md is the human-readable log of this list — keep
the two in sync when adding operators.

UI-free: `ctx` is duck-typed (the app window), predicates/callbacks are
plain callables, so the registry is testable with a stub context.
"""

from typing import Callable, List, Optional, Tuple


class Operator:
    def __init__(self, op_id, label, run, enabled=None, category="General",
                 shortcut="", aliases=()):
        # type: (str, str, Callable, Optional[Callable], str, str, tuple) -> None
        self.id = op_id
        self.label = label
        self.run = run
        self._enabled = enabled
        self.category = category
        self.shortcut = shortcut
        # Extra words the search should match — the same action goes by
        # different names in different programs ("re-perceive" vs
        # "recalculate" bonds), and a palette that only knows one of them
        # looks empty to everyone who learned the other.
        self.aliases = tuple(aliases)

    def enabled(self, ctx):
        # type: (object) -> bool
        if self._enabled is None:
            return True
        try:
            return bool(self._enabled(ctx))
        except Exception:
            return False

    def __repr__(self):
        return "Operator({!r})".format(self.id)


class OperatorRegistry:
    def __init__(self):
        self._ops = []          # type: List[Operator]
        self._by_id = {}

    def register(self, op_id, label, run, enabled=None, category="General",
                 shortcut="", aliases=()):
        # type: (str, str, Callable, Optional[Callable], str, str, tuple) -> Operator
        if op_id in self._by_id:
            raise ValueError("duplicate operator id: {}".format(op_id))
        op = Operator(op_id, label, run, enabled, category, shortcut, aliases)
        self._ops.append(op)
        self._by_id[op_id] = op
        return op

    def get(self, op_id):
        # type: (str) -> Optional[Operator]
        return self._by_id.get(op_id)

    def all(self):
        # type: () -> List[Operator]
        return list(self._ops)

    def search(self, text, ctx):
        # type: (str, object) -> List[Tuple[Operator, bool]]
        """Filter + rank for the F3 dialog. Returns (op, enabled) pairs:
        substring match on label/category/id (case-insensitive, all words
        must match), enabled ops first, then label-prefix matches, then
        registration order."""
        words = [w for w in (text or "").lower().split() if w]
        out = []
        for k, op in enumerate(self._ops):
            hay = " ".join((op.label, op.category, op.id)
                           + op.aliases).lower()
            if all(w in hay for w in words):
                en = op.enabled(ctx)
                prefix = op.label.lower().startswith(words[0]) if words else False
                out.append((not en, not prefix, k, op, en))
        out.sort(key=lambda t: t[:3])
        return [(op, en) for _e, _p, _k, op, en in out]
