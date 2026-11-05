from enum import IntEnum

from plcfsm import Rule, RuleSet, StateMachine, analyze, state, to_mermaid
from plcfsm.graph import collect_edges


class S(IntEnum):
    INI = 0
    A = 1
    B = 2
    FIM = 3
    ORFAO = 4
    ERRO = 5
    DESLIGADO = 6


E = S   # alias de módulo: o grafo resolve pelo objeto, não pelo nome

RULES = RuleSet("dec", [
    Rule("vai_b", E.B, when=lambda s: True),
    Rule("vai_desl", E.DESLIGADO, when=lambda s: False, enabled=False),
])


class M(StateMachine):
    states = S
    initial = S.INI
    idle_states = (S.FIM, S.ERRO, S.ORFAO, S.DESLIGADO)

    @state(E.INI)
    def _ini(self):
        self.goto(E.A)

    @state(E.A)
    def _a(self):
        self.decide(RULES)

    @state(E.B)
    def _b(self):
        if True:
            self.goto(E.FIM)

    def after_case(self):
        if False:
            self.goto(E.ERRO, "falha")


def pares(cls):
    # `is not None`, nunca `if e.src`: IntEnum com valor 0 é FALSO (armadilha de quem vem do CLP)
    return {(e.src.name if e.src is not None else None, e.dst.name) for e in collect_edges(cls)}


def test_arestas_vem_do_codigo_sem_declarar_duas_vezes():
    p = pares(M)
    assert ("INI", "A") in p
    assert ("A", "B") in p                     # veio da RuleSet usada no ramo
    assert ("B", "FIM") in p
    assert (None, "ERRO") in p                 # override global em after_case


def test_decorador_nao_vira_aresta():
    assert ("INI", "INI") not in pares(M)
    assert not any(src == dst for src, dst in pares(M) if src)


def test_inalcancaveis_ignoram_regras_desabilitadas():
    a = analyze(M)
    nomes = {s.name for s in a.unreachable}
    assert nomes == {"ORFAO", "DESLIGADO"}


def test_terminais_sao_estados_sem_saida_propria():
    a = analyze(M)
    assert {s.name for s in a.terminals} >= {"FIM", "ERRO", "ORFAO"}
    assert "INI" not in {s.name for s in a.terminals}


def test_mermaid():
    texto = to_mermaid(M)
    assert texto.startswith("stateDiagram-v2")
    assert "[*] --> INI" in texto
    assert "INI --> A" in texto
    assert "A --> B : dec.vai_b" in texto
    assert "A --> DESLIGADO : dec.vai_desl [desabilitada]" in texto
    assert 'state "GLOBAL (before/after_case)" as GLOBAL' in texto
    assert "GLOBAL --> ERRO : after_case" in texto


def test_summary():
    assert "inalcançáveis (2)" in analyze(M).summary()
