"""Exemplo mínimo: estação de furação (cilindro + broca) com timeout de passo.

É o "primeiro FB" de docs/index.html — cabe numa tela e usa os 5 recursos que
você mais vai usar: IntEnum, @state, R_TRIG, TON e watchdog de passo (timed_out).

ST equivalente (resumo):

    CASE eEstado OF
      PARADO:    IF rtrigStart.Q AND ixCilindroRecuado THEN eEstado := AVANCANDO; END_IF
      AVANCANDO: IF ixCilindroAvancado THEN eEstado := FURANDO;
                 ELSIF tEstado >= T#3s  THEN eEstado := FALHA; END_IF
      FURANDO:   IF tmrFuro.Q THEN eEstado := RECUANDO; END_IF
      RECUANDO:  IF ixCilindroRecuado THEN eEstado := PARADO;
                 ELSIF tEstado >= T#3s THEN eEstado := FALHA; END_IF
      FALHA:     IF ixReset AND ixCilindroRecuado THEN eEstado := PARADO; END_IF
    END_CASE
    qxAvancar := eEstado = AVANCANDO OR eEstado = FURANDO;   (* saídas derivadas do estado *)
    qxFurar   := eEstado = FURANDO;
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from plcfsm import TON, RTrig, StateMachine, state


class Estado(IntEnum):
    PARADO = 0
    AVANCANDO = 1
    FURANDO = 2
    RECUANDO = 3
    FALHA = 4


@dataclass
class IO:
    """Os endereços físicos (em CLP real: as variáveis %IX / %QX)."""

    ix_start: bool = False
    ix_reset: bool = False
    ix_cilindro_avancado: bool = False
    ix_cilindro_recuado: bool = True


class Furadeira(StateMachine):
    states = Estado
    initial = Estado.PARADO

    TEMPO_FURO = 2.0   # s
    TIMEOUT_CILINDRO = 3.0   # s

    def __init__(self, io: IO, **kw) -> None:
        super().__init__(**kw)
        self.io = io
        self.rtrig_start = RTrig()
        self.tmr_furo = TON(self.TEMPO_FURO, clock=self.clock)
        self.qx_avancar = False
        self.qx_furar = False

    # --- fases da varredura
    def read_inputs(self) -> None:
        self.rtrig_start(self.io.ix_start)
        self.tmr_furo(self.state is Estado.FURANDO)   # o timer só corre enquanto está furando

    # --- o CASE
    @state(Estado.PARADO)
    def _parado(self) -> None:
        if self.rtrig_start.q and self.io.ix_cilindro_recuado:
            self.goto(Estado.AVANCANDO, "start")

    @state(Estado.AVANCANDO)
    def _avancando(self) -> None:
        if self.io.ix_cilindro_avancado:
            self.goto(Estado.FURANDO)
        elif self.timed_out(self.TIMEOUT_CILINDRO):
            self.goto(Estado.FALHA, "cilindro não avançou a tempo")

    @state(Estado.FURANDO)
    def _furando(self) -> None:
        if self.tmr_furo.q:
            self.goto(Estado.RECUANDO)

    @state(Estado.RECUANDO)
    def _recuando(self) -> None:
        if self.io.ix_cilindro_recuado:
            self.goto(Estado.PARADO, "ciclo concluído")
        elif self.timed_out(self.TIMEOUT_CILINDRO):
            self.goto(Estado.FALHA, "cilindro não recuou a tempo")

    @state(Estado.FALHA)
    def _falha(self) -> None:
        if self.io.ix_reset and self.io.ix_cilindro_recuado:
            self.goto(Estado.PARADO, "reset")

    # --- saídas (depois do CASE)
    def write_outputs(self) -> None:
        # Saídas DERIVADAS do estado: se um override jogar a máquina em FALHA, a broca desliga sozinha.
        self.qx_avancar = self.state in (Estado.AVANCANDO, Estado.FURANDO)
        self.qx_furar = self.state is Estado.FURANDO
