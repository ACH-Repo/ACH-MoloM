"""Safe arithmetic evaluator for the N-panel value fields (Blender-style:
typing `3+5*1.3` into a coordinate box just works). AST-walk with a strict
whitelist — no names, no calls, no attribute access, nothing but numbers and
+ - * / // % ** and parentheses."""

import ast
import operator as _op

_BINOPS = {
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
    ast.Div: _op.truediv, ast.FloorDiv: _op.floordiv,
    ast.Mod: _op.mod, ast.Pow: _op.pow,
}
_UNARY = {ast.UAdd: _op.pos, ast.USub: _op.neg}


def evaluate(text):
    # type: (str) -> float
    """Evaluate an arithmetic expression to a float. Raises ValueError on
    anything that isn't plain arithmetic (including bare '', 'x', '1+')."""
    text = (text or "").strip().replace(",", ".")   # tolerate decimal commas
    if not text:
        raise ValueError("empty expression")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise ValueError("not a valid expression: {!r}".format(text))
    return float(_eval(tree.body))


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        try:
            return _BINOPS[type(node.op)](_eval(node.left), _eval(node.right))
        except ZeroDivisionError:
            raise ValueError("division by zero")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise ValueError("only plain arithmetic is allowed")
