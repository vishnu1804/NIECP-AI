"""
Deterministic rule engine (spec §1, §7, §52).

This module is the only component permitted to decide whether a regulatory
requirement *may apply* to a project. A language model may explain, summarise or
prioritise — it may never change an applicability result produced here.

SAFETY
------
Rules are stored as data (see knowledge/data/approval_data.py) and evaluated by a
hand-written recursive-descent parser over a deliberately small grammar. There is
no `eval`, no `exec`, no attribute access, no import, and no call into arbitrary
callables: only the whitelisted helper functions below can be invoked. A rule that
fails to parse raises RuleSyntaxError, which the catalogue loader surfaces at
startup rather than silently treating as "not applicable".

GRAMMAR
-------
    expr      := or_expr
    or_expr   := and_expr ( 'or' and_expr )*
    and_expr  := not_expr ( 'and' not_expr )*
    not_expr  := 'not' not_expr | comparison
    comparison:= additive ( ('=='|'!='|'>='|'<='|'>'|'<'|'in'|'not in') additive )?
    additive  := term ( ('+'|'-') term )*
    term      := unary ( ('*'|'/'|'%') unary )*
    unary     := '-' unary | primary
    primary   := NUMBER | STRING | BOOL | NONE | NAME | call | '(' expr ')'
    call      := NAME '(' [expr (',' expr)*] ')'

Every comparison against a fact that does not exist yields `None` semantics: the
engine records the fact as MISSING and the caller degrades the result to UNKNOWN /
CONDITIONAL instead of silently evaluating to False.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

log = logging.getLogger("niecp.rules")


class RuleSyntaxError(ValueError):
    """A stored rule is not valid under the engine grammar."""


class RuleEvaluationError(RuntimeError):
    """A syntactically valid rule could not be evaluated against a context."""


# ══════════════════════════════════════════════════════════════ LEXER ══
TOKEN_RE = re.compile(
    r"""
    \s*(?:
        (?P<NUMBER>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
      | (?P<STRING>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
      | (?P<OP>==|!=|>=|<=|\|\||&&|\(|\)|,|\+|-|\*|/|%|\[|\]|>|<)
      | (?P<NAME>[A-Za-z_][A-Za-z0-9_]*)
    )
    """,
    re.VERBOSE,
)

KEYWORDS = {"and", "or", "not", "in", "True", "False", "None", "true", "false", "null"}


@dataclass
class Token:
    kind: str
    value: Any
    pos: int

    def __repr__(self) -> str:  # pragma: no cover
        return f"Token({self.kind},{self.value!r})"


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    n = len(src)
    while pos < n:
        if src[pos].isspace():
            pos += 1
            continue
        m = TOKEN_RE.match(src, pos)
        if not m or m.end() == pos:
            raise RuleSyntaxError(f"unexpected character {src[pos]!r} at offset {pos} in rule: {src!r}")
        pos = m.end()
        if m.lastgroup == "NUMBER":
            raw = m.group("NUMBER")
            tokens.append(Token("NUMBER", float(raw) if ("." in raw or "e" in raw.lower()) else int(raw), m.start()))
        elif m.lastgroup == "STRING":
            raw = m.group("STRING")[1:-1]
            tokens.append(Token("STRING", raw.replace("\\'", "'").replace('\\"', '"'), m.start()))
        elif m.lastgroup == "OP":
            tokens.append(Token("OP", m.group("OP"), m.start()))
        else:
            word = m.group("NAME")
            if word in ("and", "or", "not", "in"):
                tokens.append(Token("KEY", word, m.start()))
            elif word in ("True", "true"):
                tokens.append(Token("BOOL", True, m.start()))
            elif word in ("False", "false"):
                tokens.append(Token("BOOL", False, m.start()))
            elif word in ("None", "null"):
                tokens.append(Token("NONE", None, m.start()))
            else:
                tokens.append(Token("NAME", word, m.start()))
    tokens.append(Token("EOF", None, pos))
    return tokens


# ═════════════════════════════════════════════════════════════ PARSER ══
class _Parser:
    def __init__(self, tokens: list[Token], src: str) -> None:
        self.toks = tokens
        self.i = 0
        self.src = src

    # -- helpers
    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    def advance(self) -> Token:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect_op(self, value: str) -> Token:
        tok = self.cur
        if tok.kind != "OP" or tok.value != value:
            raise RuleSyntaxError(f"expected {value!r} at offset {tok.pos} in rule: {self.src!r}")
        return self.advance()

    def at_op(self, *values: str) -> bool:
        return self.cur.kind == "OP" and self.cur.value in values

    def at_key(self, *values: str) -> bool:
        return self.cur.kind == "KEY" and self.cur.value in values

    # -- grammar
    def parse(self) -> tuple[str, list[Any]]:
        node = self.parse_or()
        if self.cur.kind != "EOF":
            raise RuleSyntaxError(f"trailing input at offset {self.cur.pos} in rule: {self.src!r}")
        return node

    def parse_or(self) -> tuple[str, list[Any]]:
        node = self.parse_and()
        while self.at_key("or") or self.at_op("||"):
            self.advance()
            node = ("or", [node, self.parse_and()])
        return node

    def parse_and(self) -> tuple[str, list[Any]]:
        node = self.parse_not()
        while self.at_key("and") or self.at_op("&&"):
            self.advance()
            node = ("and", [node, self.parse_not()])
        return node

    def parse_not(self) -> tuple[str, list[Any]]:
        if self.at_key("not"):
            # Prefix `not`. (Infix `X not in Y` is handled inside
            # parse_comparison after the left operand is consumed.)
            self.advance()
            return ("not", [self.parse_not()])
        return self.parse_comparison()

    def parse_comparison(self) -> tuple[str, list[Any]]:
        left = self.parse_additive()
        if self.cur.kind == "OP" and self.cur.value in ("==", "!=", ">=", "<=", ">", "<"):
            op = self.advance().value
            return ("cmp", [op, left, self.parse_additive()])
        if self.at_key("in"):
            self.advance()
            return ("in", [left, self.parse_additive()])
        if self.at_key("not"):
            nxt = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else None
            if nxt is not None and nxt.kind == "KEY" and nxt.value == "in":
                self.advance()
                self.advance()
                return ("not_in", [left, self.parse_additive()])
        return left

    def parse_additive(self) -> tuple[str, list[Any]]:
        node = self.parse_term()
        while self.at_op("+", "-"):
            op = self.advance().value
            node = ("binop", [op, node, self.parse_term()])
        return node

    def parse_term(self) -> tuple[str, list[Any]]:
        node = self.parse_unary()
        while self.at_op("*", "/", "%"):
            op = self.advance().value
            node = ("binop", [op, node, self.parse_unary()])
        return node

    def parse_unary(self) -> tuple[str, list[Any]]:
        if self.at_op("-"):
            self.advance()
            return ("neg", [self.parse_unary()])
        return self.parse_primary()

    def parse_primary(self) -> tuple[str, list[Any]]:
        tok = self.cur
        if tok.kind == "NUMBER":
            self.advance()
            return ("num", [tok.value])
        if tok.kind == "STRING":
            self.advance()
            return ("str", [tok.value])
        if tok.kind == "BOOL":
            self.advance()
            return ("bool", [tok.value])
        if tok.kind == "NONE":
            self.advance()
            return ("none", [])
        if tok.kind == "OP" and tok.value == "(":
            self.advance()
            node = self.parse_or()
            self.expect_op(")")
            return node
        if tok.kind == "OP" and tok.value == "[":
            self.advance()
            items: list[Any] = []
            while not self.at_op("]"):
                items.append(self.parse_or())
                if self.at_op(","):
                    self.advance()
            self.expect_op("]")
            return ("list", items)
        if tok.kind == "NAME":
            self.advance()
            if self.at_op("("):
                # function call — only whitelisted helpers may be invoked
                if tok.value not in HELPERS:
                    raise RuleSyntaxError(
                        f"unknown function {tok.value!r} at offset {tok.pos} in rule: {self.src!r}"
                    )
                self.advance()
                args: list[Any] = []
                while not self.at_op(")"):
                    args.append(self.parse_or())
                    if self.at_op(","):
                        self.advance()
                self.expect_op(")")
                return ("call", [tok.value, args])
            return ("name", [tok.value])
        raise RuleSyntaxError(f"unexpected token {tok!r} at offset {tok.pos} in rule: {self.src!r}")


_AST_CACHE: dict[str, tuple[str, list[Any]]] = {}


def parse_rule(src: str) -> tuple[str, list[Any]]:
    cached = _AST_CACHE.get(src)
    if cached is not None:
        return cached
    ast = _Parser(tokenize(src), src).parse()
    _AST_CACHE[src] = ast
    return ast


# ═════════════════════════════════════════════════════════════ CONTEXT ══
_MISSING = object()


@dataclass
class RuleContext:
    """Facts available to rules, with explicit tracking of which were absent."""

    facts: dict[str, Any] = field(default_factory=dict)
    missing: set[str] = field(default_factory=set)
    accessed: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, facts: dict[str, Any]) -> "RuleContext":
        return cls(facts=dict(facts or {}))

    def get(self, name: str) -> Any:
        self.accessed.add(name)
        if name in self.facts:
            val = self.facts[name]
            if val is None or val == "" or val == []:
                self.missing.add(name)
                return None
            return val
        self.missing.add(name)
        return None

    def has(self, name: str) -> bool:
        val = self.get(name)
        return val is not None


def _to_number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = re.sub(r"[,\s]", "", str(value))
        cleaned = re.sub(r"(?i)^(rs\.?|inr|₹)", "", cleaned)
        if not cleaned:
            return default
        return float(cleaned)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"false", "no", "n", "0", "off", "none", "null"}:
            return False
        return len(v) > 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return bool(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        return [value]
    return [value]


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    return value


# Whitelisted helper functions available inside rule expressions.
HELPERS: dict[str, Callable[..., Any]] = {
    "has": lambda ctx, name: ctx.has(str(name)),
    "truthy": lambda ctx, name: (None if ctx.get(str(name)) is None else _truthy(ctx.get(str(name)))),
    "num": lambda ctx, name, default=0.0: _to_number(ctx.get(str(name)), _to_number(default)),
    "anyof": lambda ctx, name, values=None: bool(set(map(_norm, _as_list(ctx.get(str(name))))) & set(map(_norm, _as_list(values)))),
    "allof": lambda ctx, name, values=None: bool(_as_list(values)) and set(map(_norm, _as_list(values))) <= set(map(_norm, _as_list(ctx.get(str(name))))),
    "count": lambda ctx, name: len(_as_list(ctx.get(str(name)))),
    "state_in": lambda ctx, codes=None: str(ctx.get("state_code") or "").upper() in {str(c).upper() for c in _as_list(codes)},
    "industry_in": lambda ctx, codes=None: str(ctx.get("industry_code") or "").lower() in {str(c).lower() for c in _as_list(codes)},
    "industry_is_manufacturing": lambda ctx: bool(ctx.get("_is_manufacturing")),
    "project_type_in": lambda ctx, codes=None: str(ctx.get("project_type") or "").upper() in {str(c).upper() for c in _as_list(codes)},
    "org_type_in": lambda ctx, codes=None: str(ctx.get("organization_type") or "").upper() in {str(c).upper() for c in _as_list(codes)},
    "enterprise_class_is": lambda ctx, codes=None: str(ctx.get("enterprise_class") or "").upper() in {str(c).upper() for c in _as_list(codes)},
    "land_tenure_is": lambda ctx, codes=None: str(ctx.get("land_tenure") or "").upper() in {str(c).upper() for c in _as_list(codes)},
    "food_related": lambda ctx: bool(ctx.get("_food_related")),
    "information_required": lambda ctx, key: False if ctx.has(str(key)) else None,
    "min": lambda ctx, *vals: min(_to_number(v) for v in vals) if vals else 0.0,
    "max": lambda ctx, *vals: max(_to_number(v) for v in vals) if vals else 0.0,
}


class _Evaluator:
    def __init__(self, ctx: RuleContext, src: str) -> None:
        self.ctx = ctx
        self.src = src

    def run(self, node: tuple[str, list[Any]]) -> Any:
        kind, args = node

        if kind == "num":
            return args[0]
        if kind == "str":
            return args[0]
        if kind == "bool":
            return args[0]
        if kind == "none":
            return None
        if kind == "list":
            return [self.run(a) for a in args]
        if kind == "name":
            name = args[0]
            if name in HELPERS:  # bare helper name treated as identity
                return HELPERS[name]
            return self.ctx.get(name)
        if kind == "call":
            fname = args[0]
            fn = HELPERS.get(fname)
            if fn is None:
                raise RuleSyntaxError(f"unknown function {fname!r} in rule: {self.src!r}")
            evaluated = [self.run(a) for a in args[1]]
            return fn(self.ctx, *evaluated)
        if kind == "neg":
            return -_to_number(self.run(args[0]))
        if kind == "binop":
            op = args[0]
            left = _to_number(self.run(args[1]))
            right = _to_number(self.run(args[2]))
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                return left / right if right else 0.0
            if op == "%":
                return left % right if right else 0.0
            raise RuleSyntaxError(f"unknown operator {op!r}")
        if kind == "not":
            # Kleene logic: `not <unknown>` is unknown, not True.
            value_ = self.run(args[0])
            if value_ is None:
                return None
            return not _truthy(value_)
        if kind == "and":
            left = self.run(args[0])
            if left is not None and not _truthy(left):
                return False  # definitive False — skip right entirely
            right = self.run(args[1])
            if right is not None and not _truthy(right):
                return False
            if left is None or right is None:
                return None
            return True
        if kind == "or":
            left = self.run(args[0])
            if left is not None and _truthy(left):
                return True  # definitive True — skip right entirely
            right = self.run(args[1])
            if right is not None and _truthy(right):
                return True
            if left is None or right is None:
                return None
            return False
        if kind == "in":
            left = self.run(args[0])
            right = self.run(args[1])
            if left is None:
                return False
            haystack = _as_list(right)
            if isinstance(left, str):
                return any(_norm(left) == _norm(h) for h in haystack)
            return left in haystack
        if kind == "not_in":
            left = self.run(args[0])
            right = self.run(args[1])
            if left is None:
                return True
            haystack = _as_list(right)
            if isinstance(left, str):
                return not any(_norm(left) == _norm(h) for h in haystack)
            return left not in haystack
        if kind == "cmp":
            op = args[0]
            left = self.run(args[1])
            right = self.run(args[2])
            return self._compare(op, left, right)
        raise RuleSyntaxError(f"unknown node kind {kind!r}")

    def _compare(self, op: str, left: Any, right: Any) -> bool:
        if op in ("==", "!="):
            if left is None or right is None:
                eq = left is None and right is None
            elif isinstance(left, (int, float)) or isinstance(right, (int, float)):
                if isinstance(left, str) or isinstance(right, str):
                    eq = str(left).strip().lower() == str(right).strip().lower()
                else:
                    eq = float(left) == float(right)  # type: ignore[arg-type]
            elif isinstance(left, str) or isinstance(right, str):
                eq = str(left).strip().lower() == str(right).strip().lower()
            else:
                eq = left == right
            return eq if op == "==" else not eq

        # ordering comparisons need numbers
        if left is None or right is None:
            return False
        ln = _to_number(left, default=float("-inf"))
        rn = _to_number(right, default=float("-inf"))
        if op == ">":
            return ln > rn
        if op == ">=":
            return ln >= rn
        if op == "<":
            return ln < rn
        if op == "<=":
            return ln <= rn
        raise RuleSyntaxError(f"unknown comparison {op!r}")


@dataclass
class RuleResult:
    """Full, inspectable outcome of evaluating one rule."""

    rule_key: str
    expression: str
    matched: bool
    evaluated: bool
    facts_used: dict[str, Any]
    facts_missing: list[str]
    error: str | None = None
    produced: str = "APPLIES"  # APPLIES | NOT_APPLICABLE | UNKNOWN

    # canonical result states (spec improvement §15):
    #   APPLIES · CONDITIONAL · NOT_APPLICABLE · INFORMATION_REQUIRED · REQUIRES_VERIFICATION
    CANONICAL_RESULTS = ("APPLIES", "CONDITIONAL", "NOT_APPLICABLE", "INFORMATION_REQUIRED", "REQUIRES_VERIFICATION")

    def canonical_result(self) -> str:
        """Map the engine's internal `produced` to the honest result vocabulary.
        Missing facts NEVER degrade to NOT_APPLICABLE — they become
        INFORMATION_REQUIRED; a broken/unverifiable rule becomes
        REQUIRES_VERIFICATION; the approval layer may present
        INFORMATION_REQUIRED as CONDITIONAL where a partial answer exists."""
        if self.produced == "APPLIES":
            return "APPLIES"
        if self.produced == "NOT_APPLICABLE":
            return "NOT_APPLICABLE"
        if self.error:
            return "REQUIRES_VERIFICATION"
        return "INFORMATION_REQUIRED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_key,
            "rule_key": self.rule_key,
            "expression": self.expression,
            "matched": self.matched,
            "evaluated": self.evaluated,
            "result": self.canonical_result(),
            "produced": self.produced,  # backward-compatible internal state
            "matched_facts": self.facts_used,
            "missing_facts": self.facts_missing,
            "facts_used": self.facts_used,   # backward-compatible alias
            "facts_missing": self.facts_missing,
            "explanation": explain_rule(self, None),
            "error": self.error,
        }


def evaluate_rule(expression: str, ctx: RuleContext, rule_key: str = "") -> RuleResult:
    """Evaluate one rule expression. Never raises for data problems: an invalid
    expression is reported so the operator can fix the catalogue instead of the
    requirement silently disappearing."""
    try:
        ast = parse_rule(expression)
    except RuleSyntaxError as exc:
        log.error("rule syntax error [%s]: %s", rule_key or expression, exc)
        return RuleResult(rule_key, expression, False, False, {}, [], str(exc), "UNKNOWN")

    before_missing = set(ctx.missing)
    try:
        value = _Evaluator(ctx, expression).run(ast)
    except RuleEvaluationError as exc:
        return RuleResult(rule_key, expression, False, False, {}, sorted(ctx.missing - before_missing), str(exc), "UNKNOWN")
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("rule evaluation failed [%s]", rule_key or expression)
        return RuleResult(rule_key, expression, False, False, {}, sorted(ctx.missing - before_missing), str(exc), "UNKNOWN")

    newly_missing = sorted(ctx.missing - before_missing)
    matched = _truthy(value)

    # Honesty degradation:
    #   * explicit None (e.g. `information_required(...)`)  -> UNKNOWN
    #   * False but the rule touched facts we do not have   -> UNKNOWN
    #     (we cannot claim "not applicable" on missing data)
    #   * False with all facts known                        -> NOT_APPLICABLE
    #   * True                                              -> APPLIES
    if value is None:
        produced = "UNKNOWN"
    elif matched:
        produced = "APPLIES"
    elif newly_missing:
        produced = "UNKNOWN"
    else:
        produced = "NOT_APPLICABLE"

    facts_used = {k: ctx.facts.get(k) for k in sorted(ctx.accessed) if k in ctx.facts and ctx.facts.get(k) not in (None, "", [])}

    return RuleResult(rule_key, expression, matched, True, facts_used, newly_missing, None, produced)


def explain_rule(result: RuleResult, ctx: RuleContext, template: str | None = None) -> str:
    """Render a human-readable explanation of why a rule produced its result."""
    facts = result.facts_used
    fact_text = ", ".join(f"{k} = {_fmt(v)}" for k, v in list(facts.items())[:6]) or "no profile facts were available"
    if result.error:
        return f"This requirement could not be evaluated. Rule error: {result.error}"
    if result.produced == "APPLIES":
        base = f"Condition matched on your project data ({fact_text})."
    elif result.produced == "UNKNOWN":
        base = f"Not enough information to decide. Missing: {', '.join(result.facts_missing) or 'unspecified profile fields'}."
    else:
        base = f"Condition did not match your project data ({fact_text})."
    if template:
        return f"{template} {base}"
    return base


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value[:4]) + ("…]" if len(value) > 4 else "]")
    return str(value)


def missing_facts_for(expression: str, ctx: RuleContext) -> list[str]:
    """Which facts would this rule need that are not present? Used to build the
    CONDITIONAL applicability state and the dynamic questionnaire."""
    before = set(ctx.missing)
    evaluate_rule(expression, ctx)
    return sorted(ctx.missing - before)


def required_fact_names(expression: str) -> list[str]:
    """Static extraction of referenced profile field names (for questionnaire
    targeting) — does not require a context."""
    try:
        ast = parse_rule(expression)
    except RuleSyntaxError:
        return []
    names: list[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, tuple):
            return
        kind, args = node
        if kind == "name":
            names.append(str(args[0]))
        elif kind == "call":
            for a in args[1]:
                walk(a)
            # first arg of has/truthy/num/anyof is a field name literal
            if args[1] and isinstance(args[1][0], tuple) and args[1][0][0] == "str":
                names.append(str(args[1][0][1][0]))
        else:
            for a in args:
                walk(a)

    walk(ast)
    out: list[str] = []
    for n in names:
        if n in HELPERS:
            continue
        if n not in out:
            out.append(n)
    return out


def iter_expressions(src: str) -> Iterable[str]:
    yield src
