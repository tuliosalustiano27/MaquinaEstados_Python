"""Núcleo: ``StateMachine`` com o ciclo de varredura do CLP.

Uma subclasse de ``StateMachine`` = um Function Block com um ``CASE eEstado OF``:

    class Furadeira(StateMachine):
        states  = Estado                      # o ENUM (use IntEnum com os MESMOS números do CLP)
        initial = Estado.PARADO

        @state(Estado.PARADO)                 # um ramo do CASE
        def _parado(self):
            if self.io.ix_start:
                self.goto(Estado.FURANDO)

Cada ``scan()`` executa as fases abaixo, sempre na mesma ordem (como a task do CLP):

    1. read_inputs()     copiar/ler entradas, atualizar R_TRIG/timers
    2. detecção de troca de estado  ->  on_exit / on_state_change / on_entry
       (é o ``IF eEstado <> eEstadoAnt THEN ... eEstadoAnt := eEstado``)
    3. before_case()     lógica antes do CASE
    4. o ramo do estado ATUAL  (@state) — só UM ramo por varredura
    5. after_case()      lógica depois do CASE (overrides globais; o último ``goto`` vence)
    6. write_outputs()   escrever saídas

Semântica igual à atribuição ``eEstado := X`` do ST:
  * ``goto()`` muda ``self.state`` na hora, mas NÃO encerra o ramo atual (sem return implícito)
    e NÃO re-despacha o CASE: o novo estado só executa na PRÓXIMA varredura.
  * on_entry/on_exit rodam no início da varredura seguinte à troca, antes do ramo do novo estado.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, ClassVar, Deque, Optional

from .rules import Decision, Rule, RuleSet


class PlcFsmError(Exception):
    """Erro base da biblioteca."""


class ConfigError(PlcFsmError):
    """Máquina de estados mal montada (ramo faltando, estado de outro enum, ...)."""


# --------------------------------------------------------------------------- decoradores
def _mark(role: str, members: tuple[Enum, ...]) -> Callable[[Callable], Callable]:
    if not members:
        raise ConfigError(f"@{role}() precisa de pelo menos um estado")

    def deco(fn: Callable) -> Callable:
        roles = list(getattr(fn, "_plcfsm_roles", ()))
        roles.append((role, members))
        fn._plcfsm_roles = tuple(roles)  # type: ignore[attr-defined]
        return fn

    return deco


def state(*members: Enum) -> Callable[[Callable], Callable]:
    """Marca o método como o ramo do ``CASE`` desses estados."""
    return _mark("state", members)


def on_entry(*members: Enum) -> Callable[[Callable], Callable]:
    """Roda uma vez, na primeira varredura depois de entrar no estado (antes do ramo)."""
    return _mark("entry", members)


def on_exit(*members: Enum) -> Callable[[Callable], Callable]:
    """Roda uma vez, na primeira varredura depois de sair do estado (``self.state`` já é o novo)."""
    return _mark("exit", members)


# --------------------------------------------------------------------------- dados
@dataclass(frozen=True)
class Transition:
    """Um ``goto`` registrado no histórico."""

    scan: int
    t: float
    src: Enum
    dst: Enum
    reason: str


@dataclass
class RunStats:
    scans: int = 0
    overruns: int = 0
    max_scan_time: float = 0.0


# --------------------------------------------------------------------------- StateMachine
class StateMachine:
    """Base de todas as máquinas de estados. Veja o docstring do módulo."""

    states: ClassVar[Optional[type[Enum]]] = None
    initial: ClassVar[Optional[Enum]] = None
    #: estados SEM ramo no CASE de propósito (ex.: estado de erro terminal)
    idle_states: ClassVar[tuple[Enum, ...]] = ()

    _handlers: ClassVar[dict[Enum, Callable]] = {}
    _entry_hooks: ClassVar[dict[Enum, list[Callable]]] = {}
    _exit_hooks: ClassVar[dict[Enum, list[Callable]]] = {}

    # ---- montagem da classe (equivale ao "compilar" do CLP)
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        handlers = dict(cls._handlers)
        entry = {k: list(v) for k, v in cls._entry_hooks.items()}
        exit_ = {k: list(v) for k, v in cls._exit_hooks.items()}
        own: dict[Enum, str] = {}
        for attr, fn in cls.__dict__.items():
            roles = getattr(fn, "_plcfsm_roles", None)
            if not roles:
                continue
            for role, members in roles:
                for member in members:
                    if cls.states is None or not isinstance(member, cls.states):
                        raise ConfigError(
                            f"{cls.__name__}.{attr}: {member!r} não é membro de states={cls.states!r}"
                        )
                    if role == "state":
                        if member in own and own[member] != attr:
                            raise ConfigError(
                                f"{cls.__name__}: estado {member.name} tem dois ramos "
                                f"({own[member]} e {attr})"
                            )
                        own[member] = attr
                        handlers[member] = fn
                    elif role == "entry":
                        entry.setdefault(member, []).append(fn)
                    else:
                        exit_.setdefault(member, []).append(fn)
        cls._handlers = handlers
        cls._entry_hooks = entry
        cls._exit_hooks = exit_

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        history_size: int = 200,
        fire_initial_entry: bool = False,
    ) -> None:
        cls = type(self)
        if cls.states is None or cls.initial is None:
            raise ConfigError(f"{cls.__name__}: defina os atributos de classe 'states' e 'initial'")
        if not isinstance(cls.initial, cls.states):
            raise ConfigError(f"{cls.__name__}: initial={cls.initial!r} não pertence a {cls.states!r}")
        missing = [m.name for m in cls.states if m not in cls._handlers and m not in cls.idle_states]
        if missing:
            raise ConfigError(
                f"{cls.__name__}: estados sem @state (declare o ramo ou liste em idle_states): {missing}"
            )
        self.clock = clock
        self.state: Enum = cls.initial
        # ST: eEstadoAnt começa igual a eEstado -> sem "entrada" na 1ª varredura.
        self.prev_state: Optional[Enum] = None if fire_initial_entry else cls.initial
        self.scan_count = 0
        self.state_scans = 0
        self._entered_at = clock()
        self.history: Deque[Transition] = deque(maxlen=history_size)
        self.scan_transitions: list[Transition] = []
        self.last_decision: Optional[Decision] = None
        self.last_scan_time = 0.0
        self.max_scan_time = 0.0

    # ---- ganchos (sobrescreva o que precisar)
    def read_inputs(self) -> None:
        """Fase 1: ler tags/sensores e atualizar R_TRIG, timers."""

    def on_state_change(self, old: Optional[Enum], new: Enum) -> None:
        """Genérico: qualquer troca de estado (o ``IF eEstado <> eEstadoAnt``)."""

    def before_case(self) -> None:
        """Fase 3: antes do ramo do estado."""

    def after_case(self) -> None:
        """Fase 5: depois do ramo (overrides globais, emergência, ...)."""

    def write_outputs(self) -> None:
        """Fase 6: escrever saídas."""

    # ---- transições
    def goto(self, new: Enum, reason: str = "") -> None:
        """``eEstado := new``. Registra no histórico. Não encerra o ramo atual."""
        if not isinstance(new, type(self).states):  # type: ignore[arg-type]
            raise TypeError(
                f"{type(self).__name__}.goto({new!r}): precisa ser membro de {type(self).states.__name__}"  # type: ignore[union-attr]
            )
        old = self.state
        if new is old:
            return
        self.state = new
        tr = Transition(self.scan_count, self.clock(), old, new, reason)
        self.history.append(tr)
        self.scan_transitions.append(tr)

    def decide(self, ruleset: RuleSet) -> Optional[Rule]:
        """Avalia uma tabela de regras (ELSIF por prioridade) e dá ``goto`` na vencedora."""
        decision = ruleset.evaluate(self)
        self.last_decision = decision
        if decision.rule is not None:
            self.goto(decision.rule.goto, f"{ruleset.name}.{decision.rule.name}")
        return decision.rule

    def explain(self, ruleset: RuleSet, verbose: bool = False) -> str:
        """Por que cada regra do ``ruleset`` está (ou não) disparando agora."""
        return ruleset.explain(self, verbose=verbose)

    # ---- tempo no estado
    @property
    def state_time(self) -> float:
        """Segundos desde a entrada no estado atual."""
        return self.clock() - self._entered_at

    def timed_out(self, seconds: float) -> bool:
        """Watchdog de passo: o estado atual dura há pelo menos ``seconds``?"""
        return self.state_time >= seconds

    # ---- varredura
    def _detect_entry(self) -> None:
        if self.state is self.prev_state:
            return
        old, new = self.prev_state, self.state
        self.prev_state = new
        self._entered_at = self.clock()
        self.state_scans = 0
        if old is not None:
            for fn in type(self)._exit_hooks.get(old, ()):
                fn(self)
        self.on_state_change(old, new)
        for fn in type(self)._entry_hooks.get(new, ()):
            fn(self)

    def scan(self) -> None:
        """Uma varredura completa (chame em ciclo fixo)."""
        t0 = self.clock()
        self.scan_count += 1
        self.scan_transitions = []
        try:
            self.read_inputs()
            self._detect_entry()
            self.state_scans += 1
            self.before_case()
            handler = type(self)._handlers.get(self.state)
            if handler is not None:
                handler(self)
            self.after_case()
            self.write_outputs()
        except Exception as exc:
            if hasattr(exc, "add_note"):
                exc.add_note(
                    f"plcfsm: {type(self).__name__} varredura={self.scan_count} "
                    f"estado={self.state.name} anterior={getattr(self.prev_state, 'name', None)}"
                )
            raise
        self.last_scan_time = self.clock() - t0
        self.max_scan_time = max(self.max_scan_time, self.last_scan_time)

    def reset(self) -> None:
        """Volta ao estado inicial como numa partida a frio (não mexe nos seus atributos)."""
        self.state = type(self).initial  # type: ignore[assignment]
        self.prev_state = self.state
        self._entered_at = self.clock()
        self.state_scans = 0
        self.history.clear()
        self.scan_transitions = []

    # ---- observação (HMI / telemetria)
    def snapshot(self) -> dict[str, Any]:
        last = self.history[-1] if self.history else None
        value = self.state.value
        return {
            "machine": type(self).__name__,
            "state": self.state.name,
            "state_value": value if isinstance(value, int) else None,
            "prev_state": getattr(self.prev_state, "name", None),
            "state_time": round(self.state_time, 3),
            "state_scans": self.state_scans,
            "scan_count": self.scan_count,
            "last_scan_time": self.last_scan_time,
            "max_scan_time": self.max_scan_time,
            "last_transition": None
            if last is None
            else {"scan": last.scan, "from": last.src.name, "to": last.dst.name, "reason": last.reason},
        }


# --------------------------------------------------------------------------- execução cíclica
def run(
    *machines: StateMachine,
    period: float = 0.05,
    until: Optional[Callable[[], bool]] = None,
    max_scans: Optional[int] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RunStats:
    """Task cíclica: varre as máquinas, em ordem, a cada ``period`` segundos.

    Se uma varredura estourar o período, conta em ``overruns`` e ressincroniza (o
    "watchdog de scan" do CLP). Python NÃO é tempo real determinístico: use para
    supervisão/coordenação, nunca como intertravamento de segurança.
    """
    if not machines:
        raise ValueError("run(): passe pelo menos uma máquina")
    stats = RunStats()
    next_t = clock()
    while True:
        started = clock()
        for machine in machines:
            machine.scan()
        stats.scans += 1
        stats.max_scan_time = max(stats.max_scan_time, clock() - started)
        if (max_scans is not None and stats.scans >= max_scans) or (until is not None and until()):
            return stats
        next_t += period
        wait = next_t - clock()
        if wait > 0:
            sleep(wait)
        else:
            stats.overruns += 1
            next_t = clock()
