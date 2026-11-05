"""Os demais padrões, rodando: on_entry, latch SR, handshake pedido/eco, tabela de decisão, override global.

Máquina fictícia: uma dosadora que pede material a um alimentador, dosa, e entra em falha
se o nível ficar baixo. Cada trecho da página docs/index.html vem daqui.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from plcfsm import SR, Handshake, RTrig, Rule, RuleSet, StateMachine, T, on_entry, state


class Estado(IntEnum):
    PARADO = 0
    PEDINDO_MATERIAL = 1
    DOSANDO = 2
    FALHA = 3
    EMERGENCIA = 4


class Pedido(IntEnum):
    NENHUM = 0
    ALIMENTAR = 1


@dataclass
class IO:
    ix_start: bool = False
    ix_reset: bool = False
    ix_emergencia: bool = False
    ix_nivel_baixo: bool = False
    ix_dose_pronta: bool = False
    e_eco_pedido: Pedido = Pedido.NENHUM   # o alimentador devolve aqui o pedido que aceitou


FALHA_ATIVA = T("srFalha.Q", lambda s: s.sr_falha.q)
START = T("rtrigStart.Q", lambda s: s.rtrig_start.q)

DECISOR = RuleSet("decisor", [
    Rule("falha", Estado.FALHA, when=FALHA_ATIVA),
    Rule("inicia", Estado.PEDINDO_MATERIAL, when=START & ~FALHA_ATIVA),
])


class Dosadora(StateMachine):
    states = Estado
    initial = Estado.PARADO

    def __init__(self, io: IO, **kw) -> None:
        super().__init__(**kw)
        self.io = io
        self.rtrig_start = RTrig()
        self.rtrig_reset = RTrig()
        self.sr_falha = SR()
        self.req_pedido = Handshake(Pedido.NENHUM)
        self.doses = 0

    def read_inputs(self) -> None:
        self.rtrig_start(self.io.ix_start)
        self.rtrig_reset(self.io.ix_reset)
        self.sr_falha(self.io.ix_nivel_baixo, self.rtrig_reset.q)

    @on_entry(Estado.DOSANDO)
    def _entra_dosando(self) -> None:
        self.doses += 1

    @state(Estado.PARADO)
    def _parado(self) -> None:
        self.decide(DECISOR)

    @state(Estado.PEDINDO_MATERIAL)
    def _pedindo(self) -> None:
        if self.req_pedido.request(Pedido.ALIMENTAR, ack=self.io.e_eco_pedido):
            self.goto(Estado.DOSANDO, "alimentador confirmou")
        elif self.timed_out(5.0):
            self.req_pedido.release()
            self.goto(Estado.FALHA, "alimentador não respondeu")

    @state(Estado.DOSANDO)
    def _dosando(self) -> None:
        if self.io.ix_dose_pronta:
            self.goto(Estado.PARADO, "dose concluída")

    @state(Estado.FALHA)
    def _falha(self) -> None:
        if not self.sr_falha.q:
            self.goto(Estado.PARADO, "falha reconhecida")

    @state(Estado.EMERGENCIA)
    def _emergencia(self) -> None:
        if not self.io.ix_emergencia:
            self.goto(Estado.PARADO, "emergência liberada")

    def after_case(self) -> None:
        if self.io.ix_emergencia:
            self.req_pedido.release()
            self.goto(Estado.EMERGENCIA, "botão de emergência")
