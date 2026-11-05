"""Blocos de função padrão IEC 61131-3 (R_TRIG, F_TRIG, SR, RS, TON, TOF, TP) + Handshake.

Regra de ouro (igual ao CLP): cada instância é chamada **uma vez por varredura**.
Chame no ``read_inputs()`` da máquina de estados e leia ``.q`` onde precisar —
exatamente como ``rtrigX.Q`` no Structured Text.

    ST:      rtrigPecaPresa(CLK := xSensorPeca);   IF rtrigPecaPresa.Q THEN ...
    Python:  self.rtrig_peca_presa(self.x_sensor_peca);   if self.rtrig_peca_presa.q: ...

Os timers recebem um ``clock`` (função que devolve segundos). O padrão é
``time.monotonic``; nos testes passe um relógio falso para controlar o tempo.
"""
from __future__ import annotations

import time
from typing import Any, Callable

Clock = Callable[[], float]


class RTrig:
    """R_TRIG — ``q`` fica TRUE durante UMA varredura na borda de subida de ``clk``.

    Como no CLP, a memória começa em FALSE: se ``clk`` já estiver TRUE na primeira
    chamada, isso conta como borda de subida.
    """

    __slots__ = ("q", "_mem")

    def __init__(self) -> None:
        self.q = False
        self._mem = False

    def __call__(self, clk: Any) -> bool:
        clk = bool(clk)
        self.q = clk and not self._mem
        self._mem = clk
        return self.q

    def __repr__(self) -> str:
        return f"RTrig(q={self.q})"


class FTrig:
    """F_TRIG — ``q`` fica TRUE durante UMA varredura na borda de descida de ``clk``."""

    __slots__ = ("q", "_mem")

    def __init__(self) -> None:
        self.q = False
        self._mem = False

    def __call__(self, clk: Any) -> bool:
        clk = bool(clk)
        self.q = (not clk) and self._mem
        self._mem = clk
        return self.q

    def __repr__(self) -> str:
        return f"FTrig(q={self.q})"


class SR:
    """SR — latch com SET dominante: ``q = set1 OR (q AND NOT reset)``."""

    __slots__ = ("q",)

    def __init__(self, q: bool = False) -> None:
        self.q = bool(q)

    def __call__(self, set1: Any, reset: Any) -> bool:
        self.q = bool(set1) or (self.q and not reset)
        return self.q

    def __repr__(self) -> str:
        return f"SR(q={self.q})"


class RS:
    """RS — latch com RESET dominante: ``q = NOT reset AND (set OR q)``."""

    __slots__ = ("q",)

    def __init__(self, q: bool = False) -> None:
        self.q = bool(q)

    def __call__(self, set_: Any, reset1: Any) -> bool:
        self.q = (not reset1) and (bool(set_) or self.q)
        return self.q

    def __repr__(self) -> str:
        return f"RS(q={self.q})"


class TON:
    """TON — atraso na energização. ``q`` sobe quando ``in_`` ficou TRUE por ``pt`` segundos."""

    def __init__(self, pt: float, clock: Clock = time.monotonic) -> None:
        self.pt = float(pt)
        self.clock = clock
        self.q = False
        self.et = 0.0
        self._t0: float | None = None

    def __call__(self, in_: Any) -> bool:
        if in_:
            now = self.clock()
            if self._t0 is None:
                self._t0 = now
            self.et = min(now - self._t0, self.pt)
            self.q = self.et >= self.pt
        else:
            self._t0 = None
            self.et = 0.0
            self.q = False
        return self.q

    def __repr__(self) -> str:
        return f"TON(pt={self.pt}, et={self.et:.3f}, q={self.q})"


class TOF:
    """TOF — atraso na desenergização. ``q`` sobe com ``in_`` e cai ``pt`` s depois de ``in_`` cair."""

    def __init__(self, pt: float, clock: Clock = time.monotonic) -> None:
        self.pt = float(pt)
        self.clock = clock
        self.q = False
        self.et = 0.0
        self._t0: float | None = None

    def __call__(self, in_: Any) -> bool:
        if in_:
            self.q = True
            self._t0 = None
            self.et = 0.0
        elif self.q:
            now = self.clock()
            if self._t0 is None:
                self._t0 = now
            self.et = min(now - self._t0, self.pt)
            if self.et >= self.pt:
                self.q = False
        else:
            self._t0 = None
            self.et = 0.0
        return self.q

    def __repr__(self) -> str:
        return f"TOF(pt={self.pt}, et={self.et:.3f}, q={self.q})"


class TP:
    """TP — pulso de largura ``pt`` segundos na borda de subida de ``in_`` (não re-disparável)."""

    def __init__(self, pt: float, clock: Clock = time.monotonic) -> None:
        self.pt = float(pt)
        self.clock = clock
        self.q = False
        self.et = 0.0
        self._t0 = 0.0
        self._running = False
        self._prev = False

    def __call__(self, in_: Any) -> bool:
        in_ = bool(in_)
        now = self.clock()
        if self._running:
            self.et = min(now - self._t0, self.pt)
            if self.et >= self.pt:
                self._running = False
                self.q = False
        elif in_ and not self._prev:
            self._running = True
            self._t0 = now
            self.et = 0.0
            self.q = True
        if not in_ and not self._running:
            self.et = 0.0
        self._prev = in_
        return self.q

    def __repr__(self) -> str:
        return f"TP(pt={self.pt}, et={self.et:.3f}, q={self.q})"


class Handshake:
    """Pedido com confirmação — o par ``REQ_x`` → ``x_ING`` do CLP.

    No ST::

        eReqPedido := E_PEDIDO.ALIMENTAR;
        IF (eReqPedido = eEcoPedido) THEN
            eReqPedido := E_PEDIDO.NENHUM;
            eEstado := E_ESTADO.DOSANDO;
        END_IF

    Em Python::

        if self.req_pedido.request(Pedido.ALIMENTAR, ack=self.io.e_eco_pedido):
            self.goto(Estado.DOSANDO)

    ``value`` é o que vai para o outro lado (a variável ``eReqPedido``): o pedido fica
    ligado a cada varredura até o ``ack`` ecoar de volta; então volta para ``idle``.
    """

    def __init__(self, idle: Any) -> None:
        self.idle = idle
        self.value = idle

    @property
    def active(self) -> bool:
        return self.value != self.idle

    def request(self, value: Any, ack: Any) -> bool:
        """Mantém o pedido ligado. Devolve TRUE (uma vez) quando ``ack`` confirmar."""
        self.value = value
        if value == ack:
            self.value = self.idle
            return True
        return False

    def release(self) -> None:
        """Cancela o pedido (``eReqPedido := NENHUM``)."""
        self.value = self.idle

    def __repr__(self) -> str:
        return f"Handshake(value={self.value!r})"
