"""plcfsm — máquinas de estados em Python no estilo CLP (ciclo de varredura, CASE, R_TRIG, timers).

    from plcfsm import StateMachine, state, on_entry, on_exit
    from plcfsm import RTrig, FTrig, SR, RS, TON, TOF, TP, Handshake
    from plcfsm import T, AND, OR, NOT, Rule, RuleSet
    from plcfsm import run

Comparação ST x Python lado a lado: docs/index.html
"""
from .blocks import FTrig, Handshake, RS, RTrig, SR, TOF, TON, TP
from .core import ConfigError, PlcFsmError, RunStats, StateMachine, Transition, on_entry, on_exit, run, state
from .graph import Analysis, Edge, analyze, collect_edges, to_mermaid
from .rules import AND, NOT, OR, Cond, Decision, Node, Rule, RuleSet, T

__version__ = "0.1.0"

__all__ = [
    "StateMachine", "state", "on_entry", "on_exit", "run", "Transition", "RunStats",
    "PlcFsmError", "ConfigError",
    "RTrig", "FTrig", "SR", "RS", "TON", "TOF", "TP", "Handshake",
    "T", "AND", "OR", "NOT", "Cond", "Rule", "RuleSet", "Decision", "Node",
    "analyze", "collect_edges", "to_mermaid", "Analysis", "Edge",
]
