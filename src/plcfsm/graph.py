"""Análise estática: grafo de transições, estados inalcançáveis e diagrama Mermaid.

Sem declarar nada duas vezes: o grafo sai do próprio código, lendo (via ``ast``) cada
ramo ``@state``. Toda referência ``Enum.MEMBRO`` do enum de estados dentro de um ramo
conta como um destino possível (``self.goto(E.X)``, ``self.requisita(R.Y, E.X)``, ...);
toda ``RuleSet`` usada no ramo contribui com os destinos das suas regras.

Limites (honestos): é uma análise do *texto*. Um destino calculado em tempo de execução
(``self.goto(tabela[i])``) não aparece. Referências em comparações
(``if self.state == E.X``) aparecem como destino — releia o grafo com isso em mente.

CLI:  python -m plcfsm modulo:Classe [--mermaid]
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .core import StateMachine
from .rules import RuleSet


@dataclass(frozen=True)
class Edge:
    src: Optional[Enum]  # None = global (before_case / after_case)
    dst: Enum
    label: str = ""
    enabled: bool = True


@dataclass
class Analysis:
    machine: str
    edges: list[Edge]
    unreachable: list[Enum] = field(default_factory=list)
    terminals: list[Enum] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"{self.machine}: {len(self.edges)} transições"]
        lines.append(
            "inalcançáveis ({}): {}".format(len(self.unreachable), ", ".join(s.name for s in self.unreachable) or "-")
        )
        lines.append(
            "sem saída própria ({}): {}".format(len(self.terminals), ", ".join(s.name for s in self.terminals) or "-")
        )
        return "\n".join(lines)


def _scan_function(fn: Any, cls: type[StateMachine]) -> tuple[list[Enum], list[RuleSet]]:
    """Destinos (membros do enum) e RuleSets referenciados no corpo de ``fn``."""
    try:
        source = textwrap.dedent(inspect.getsource(fn))
        tree = ast.parse(source)
    except (OSError, TypeError, SyntaxError):
        return [], []
    for node in ast.walk(tree):  # tira os decoradores (@state(E.X) não é transição)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.decorator_list = []
    namespace = getattr(fn, "__globals__", {})
    targets: list[Enum] = []
    rulesets: list[RuleSet] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = node.value.id
            if base == "self":
                obj = getattr(cls, node.attr, None)
                if isinstance(obj, RuleSet):
                    rulesets.append(obj)
            else:
                obj = namespace.get(base)
                if obj is cls.states and node.attr in cls.states.__members__:  # type: ignore[union-attr]
                    targets.append(cls.states[node.attr])  # type: ignore[index]
        elif isinstance(node, ast.Name):
            obj = namespace.get(node.id)
            if isinstance(obj, RuleSet):
                rulesets.append(obj)
    return targets, rulesets


def collect_edges(cls: type[StateMachine]) -> list[Edge]:
    if cls.states is None:
        raise ValueError(f"{cls.__name__} não define states")
    edges: dict[tuple[Any, Enum, str, bool], Edge] = {}

    def add(src: Optional[Enum], dst: Enum, label: str = "", enabled: bool = True) -> None:
        if src is not None and src is dst:
            return
        edges.setdefault((src, dst, label, enabled), Edge(src, dst, label, enabled))

    for src_state, fn in cls._handlers.items():
        targets, rulesets = _scan_function(fn, cls)
        for dst in targets:
            add(src_state, dst)
        for rs in rulesets:
            for rule in rs.rules:
                add(src_state, rule.goto, f"{rs.name}.{rule.name}", rule.enabled)

    for hook_name in ("before_case", "after_case"):
        if getattr(cls, hook_name) is not getattr(StateMachine, hook_name):
            targets, rulesets = _scan_function(getattr(cls, hook_name), cls)
            for dst in targets:
                add(None, dst, hook_name)
            for rs in rulesets:
                for rule in rs.rules:
                    add(None, rule.goto, f"{rs.name}.{rule.name}", rule.enabled)
    return list(edges.values())


def analyze(cls: type[StateMachine]) -> Analysis:
    edges = collect_edges(cls)
    live = [e for e in edges if e.enabled]
    reached = {cls.initial} | {e.dst for e in live if e.src is None}
    frontier = list(reached)
    while frontier:
        current = frontier.pop()
        for e in live:
            if e.src is current and e.dst not in reached:
                reached.add(e.dst)
                frontier.append(e.dst)
    members = list(cls.states)  # type: ignore[arg-type]
    unreachable = [m for m in members if m not in reached]
    with_exit = {e.src for e in live if e.src is not None}
    terminals = [m for m in members if m not in with_exit]
    return Analysis(cls.__name__, edges, unreachable, terminals)


def to_mermaid(cls: type[StateMachine]) -> str:
    """Diagrama ``stateDiagram-v2`` (cole em https://mermaid.live ou num .md do GitHub)."""
    edges = collect_edges(cls)
    lines = ["stateDiagram-v2", f"    [*] --> {cls.initial.name}"]  # type: ignore[union-attr]
    if any(e.src is None for e in edges):
        lines.append('    state "GLOBAL (before/after_case)" as GLOBAL')
    for e in edges:
        src = "GLOBAL" if e.src is None else e.src.name
        label = e.label + (" [desabilitada]" if not e.enabled else "")
        lines.append(f"    {src} --> {e.dst.name}" + (f" : {label}" if label else ""))
    return "\n".join(lines)
