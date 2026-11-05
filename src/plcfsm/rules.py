"""Condições rotuladas e tabelas de decisão (o ``IF / ELSIF / ELSIF`` gigante do ramo decisor).

Por que existe: no CLP, um ELSIF com 15 termos que "não dispara" só se depura olhando
o ladder/ST online. Aqui cada termo tem um rótulo, e ``RuleSet.explain()`` diz quais
termos estão bloqueando cada regra.

    SEM_FALHA = ~T("xFalha",    lambda s: s.x_falha)
    SEM_PECA  =  T("xSemPeca",  lambda s: s.x_sem_peca)

    DECISOR = RuleSet("decisor", [
        Rule("carrega", E.CARREGANDO, when=SEM_FALHA & SEM_PECA),
        ...
    ])

Os operadores ``&  |  ~`` têm a mesma precedência de ``AND  OR  NOT`` do ST
(NOT > AND > OR). Em dúvida, use parênteses — igual no ST.

REQUISITO: as condições devem ser **puras** (só lêem). ``explain()`` avalia todas as regras.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence


# --------------------------------------------------------------------------- resultado
@dataclass
class Node:
    """Resultado da avaliação de uma condição (árvore, para explicar o porquê)."""

    ok: bool
    kind: str  # "term" | "and" | "or" | "not"
    label: Optional[str]
    children: list["Node"] = field(default_factory=list)

    def describe(self) -> str:
        if self.label:
            return self.label
        if self.kind == "term":
            return "<termo sem rótulo>"
        if self.kind == "not":
            return "NOT " + (self.children[0].describe() if self.children else "?")
        sep = " AND " if self.kind == "and" else " OR "
        return "(" + sep.join(c.describe() for c in self.children) + ")"

    def blockers(self) -> list[str]:
        """O que impede este nó de ser TRUE (vazio se já é TRUE)."""
        if self.ok:
            return []
        if self.kind == "and":
            out: list[str] = []
            for child in self.children:
                out.extend(child.blockers())
            return out
        return [self.describe()]  # term / not / or: o nó inteiro é o bloqueio

    def tree(self, indent: int = 0) -> str:
        mark = "[+]" if self.ok else "[-]"
        head = {"term": "", "and": "AND ", "or": "OR ", "not": "NOT "}[self.kind]
        text = f"{'  ' * indent}{mark} {head}{self.label or ''}".rstrip()
        lines = [text]
        for child in self.children:
            lines.append(child.tree(indent + 1))
        return "\n".join(lines)


# --------------------------------------------------------------------------- condições
class Cond:
    """Condição avaliável. Chame ``cond(ctx)`` para obter bool, ou ``cond.eval(ctx)`` para o Node."""

    label: Optional[str] = None

    def eval(self, ctx: Any, full: bool = False) -> Node:  # pragma: no cover - abstrato
        raise NotImplementedError

    def __call__(self, ctx: Any) -> bool:
        return self.eval(ctx).ok

    def __and__(self, other: Any) -> "AND":
        return AND(self, other)

    def __rand__(self, other: Any) -> "AND":
        return AND(other, self)

    def __or__(self, other: Any) -> "OR":
        return OR(self, other)

    def __ror__(self, other: Any) -> "OR":
        return OR(other, self)

    def __invert__(self) -> "NOT":
        return NOT(self)


class T(Cond):
    """Termo: um rótulo + uma função ``fn(ctx) -> bool`` (ctx = a máquina de estados)."""

    def __init__(self, label: Optional[str], fn: Callable[[Any], Any]) -> None:
        if not callable(fn):
            raise TypeError("T(label, fn): fn precisa ser chamável")
        self.label = label
        self.fn = fn

    def eval(self, ctx: Any, full: bool = False) -> Node:
        return Node(bool(self.fn(ctx)), "term", self.label)


def as_cond(x: Any) -> Cond:
    if isinstance(x, Cond):
        return x
    if callable(x):
        return T(None, x)
    raise TypeError(f"não é condição: {x!r} (use T('rótulo', lambda s: ...))")


class AND(Cond):
    """AND de todos os termos. Sem argumentos vale TRUE."""

    def __init__(self, *terms: Any, label: Optional[str] = None) -> None:
        flat: list[Cond] = []
        for term in terms:
            cond = as_cond(term)
            if type(cond) is AND and cond.label is None:
                flat.extend(cond.terms)
            else:
                flat.append(cond)
        self.terms = flat
        self.label = label

    def eval(self, ctx: Any, full: bool = False) -> Node:
        nodes: list[Node] = []
        ok = True
        for term in self.terms:
            node = term.eval(ctx, full)
            nodes.append(node)
            if not node.ok:
                ok = False
                if not full:
                    break
        return Node(ok, "and", self.label, nodes)


class OR(Cond):
    """OR de todos os termos. Sem argumentos vale FALSE."""

    def __init__(self, *terms: Any, label: Optional[str] = None) -> None:
        flat: list[Cond] = []
        for term in terms:
            cond = as_cond(term)
            if type(cond) is OR and cond.label is None:
                flat.extend(cond.terms)
            else:
                flat.append(cond)
        self.terms = flat
        self.label = label

    def eval(self, ctx: Any, full: bool = False) -> Node:
        nodes: list[Node] = []
        ok = False
        for term in self.terms:
            node = term.eval(ctx, full)
            nodes.append(node)
            if node.ok:
                ok = True
                if not full:
                    break
        return Node(ok, "or", self.label, nodes)


class NOT(Cond):
    def __init__(self, term: Any, label: Optional[str] = None) -> None:
        self.term = as_cond(term)
        self.label = label

    def eval(self, ctx: Any, full: bool = False) -> Node:
        node = self.term.eval(ctx, full)
        return Node(not node.ok, "not", self.label, [node])


# --------------------------------------------------------------------------- regras
@dataclass
class Rule:
    """Uma perna do ELSIF: se ``when`` for TRUE, vai para ``goto``.

    ``enabled=False`` equivale ao ``AND (FALSE)`` que se deixa no ST para desligar uma perna.
    """

    name: str
    goto: Enum
    when: Any
    doc: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        self.when = as_cond(self.when)


@dataclass
class RuleResult:
    rule: Rule
    status: str  # "disabled" | "skipped" | "true" | "false"
    node: Optional[Node] = None


@dataclass
class Decision:
    ruleset: str
    rule: Optional[Rule]
    results: list[RuleResult]

    def report(self, verbose: bool = False) -> str:
        chosen = self.rule.name if self.rule else "nenhuma"
        lines = [f"[{self.ruleset}] regra escolhida: {chosen}"]
        for i, res in enumerate(self.results, 1):
            head = f" {i:>2}. {res.rule.name} -> {res.rule.goto.name}"
            if res.status == "disabled":
                lines.append(f"{head}  [DESABILITADA]")
            elif res.status == "skipped":
                lines.append(f"{head}  [nao avaliada]")
            elif res.rule is self.rule:
                lines.append(f"{head}  [+] ESCOLHIDA")
            elif res.status == "true":
                lines.append(f"{head}  [+] verdadeira, mas perdeu por prioridade")
            else:
                blockers = res.node.blockers() if res.node else []
                lines.append(f"{head}  [-] bloqueada por: " + "; ".join(blockers))
                if verbose and res.node:
                    lines.append(res.node.tree(indent=3))
        return "\n".join(lines)


class RuleSet:
    """Lista de regras em ordem de prioridade — a primeira verdadeira vence (ELSIF)."""

    def __init__(self, name: str, rules: Sequence[Rule]) -> None:
        names = [r.name for r in rules]
        if len(set(names)) != len(names):
            dup = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"RuleSet {name!r}: nomes de regra repetidos: {dup}")
        self.name = name
        self.rules = list(rules)

    def evaluate(self, ctx: Any, full: bool = False) -> Decision:
        """Avalia como um ELSIF (para na primeira verdadeira). ``full=True`` avalia todas."""
        results: list[RuleResult] = []
        chosen: Optional[Rule] = None
        for rule in self.rules:
            if chosen is not None and not full:
                results.append(RuleResult(rule, "skipped"))
                continue
            if not rule.enabled:
                results.append(RuleResult(rule, "disabled"))
                continue
            node = rule.when.eval(ctx, full)
            results.append(RuleResult(rule, "true" if node.ok else "false", node))
            if node.ok and chosen is None:
                chosen = rule
        return Decision(self.name, chosen, results)

    def explain(self, ctx: Any, verbose: bool = False) -> str:
        """Texto com o motivo de cada regra não ter disparado (avalia todas, sem efeitos)."""
        return self.evaluate(ctx, full=True).report(verbose=verbose)
