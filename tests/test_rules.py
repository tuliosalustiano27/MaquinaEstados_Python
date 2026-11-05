from enum import IntEnum
from types import SimpleNamespace

import pytest

from plcfsm import AND, NOT, OR, Rule, RuleSet, StateMachine, T, state


class S(IntEnum):
    DECIDE = 0
    X = 1
    Y = 2
    Z = 3


def ctx(**kw):
    base = dict(a=False, b=False, c=False, d=False)
    base.update(kw)
    return SimpleNamespace(**base)


A = T("a", lambda s: s.a)
B = T("b", lambda s: s.b)
C = T("c", lambda s: s.c)
D = T("d", lambda s: s.d)


def test_and_or_not_basicos():
    assert AND(A, B)(ctx(a=1, b=1)) is True
    assert AND(A, B)(ctx(a=1)) is False
    assert OR(A, B)(ctx(b=1)) is True
    assert OR()(ctx()) is False and AND()(ctx()) is True
    assert NOT(A)(ctx()) is True


def test_operadores_tem_a_mesma_precedencia_do_st():
    # NOT > AND > OR:  ~A & B | C  ==  ((NOT a) AND b) OR c
    cond = ~A & B | C
    assert cond(ctx(b=True)) is True
    assert cond(ctx(a=True, b=True)) is False
    assert cond(ctx(a=True, b=True, c=True)) is True


def test_lambda_puro_vira_condicao():
    cond = A & (lambda s: s.b)
    assert cond(ctx(a=True, b=True)) is True
    assert cond(ctx(a=True)) is False


def test_nao_condicao_levanta():
    with pytest.raises(TypeError):
        AND(A, 42)


def test_and_achata_and_sem_rotulo():
    cond = A & B & C
    assert len(cond.terms) == 3


def test_curto_circuito_so_quando_nao_full():
    visitados = []

    def spy(nome, valor):
        return T(nome, lambda s: visitados.append(nome) or valor)

    AND(spy("1", False), spy("2", True)).eval(None)
    assert visitados == ["1"]
    visitados.clear()
    AND(spy("1", False), spy("2", True)).eval(None, full=True)
    assert visitados == ["1", "2"]
    visitados.clear()
    OR(spy("1", True), spy("2", True)).eval(None)
    assert visitados == ["1"]


def test_bloqueios_apontam_os_termos_falsos():
    node = (A & B & ~C & (D | A)).eval(ctx(a=True, c=True), full=True)
    assert node.ok is False
    assert node.blockers() == ["b", "NOT c"]


def test_ruleset_primeira_verdadeira_vence():
    rs = RuleSet("rs", [
        Rule("r1", S.X, when=A),
        Rule("r2", S.Y, when=B),
        Rule("r3", S.Z, when=C),
    ])
    d = rs.evaluate(ctx(b=True, c=True))
    assert d.rule.name == "r2"
    assert [r.status for r in d.results] == ["false", "true", "skipped"]


def test_ruleset_regra_desabilitada_e_ignorada():
    rs = RuleSet("rs", [Rule("off", S.X, when=A, enabled=False), Rule("on", S.Y, when=A)])
    d = rs.evaluate(ctx(a=True))
    assert d.rule.name == "on" and d.results[0].status == "disabled"


def test_ruleset_nenhuma():
    rs = RuleSet("rs", [Rule("r1", S.X, when=A)])
    assert rs.evaluate(ctx()).rule is None


def test_ruleset_nomes_repetidos_falham():
    with pytest.raises(ValueError):
        RuleSet("rs", [Rule("r", S.X, when=A), Rule("r", S.Y, when=B)])


def test_explain_mostra_motivo_de_cada_regra():
    rs = RuleSet("rs", [
        Rule("r1", S.X, when=A & B),
        Rule("r2", S.Y, when=C),
        Rule("r3", S.Z, when=A, enabled=False),
    ])
    texto = rs.explain(ctx(a=True, c=True))
    assert "regra escolhida: r2" in texto
    assert "bloqueada por: b" in texto
    assert "[DESABILITADA]" in texto
    assert "ESCOLHIDA" in texto


def test_explain_verbose_traz_arvore():
    rs = RuleSet("rs", [Rule("r1", S.X, when=A & ~B)])
    texto = rs.explain(ctx(a=True, b=True), verbose=True)
    assert "[-] AND" in texto and "[+] a" in texto and "[-] NOT" in texto


class M(StateMachine):
    states = S
    initial = S.DECIDE
    idle_states = (S.X, S.Y, S.Z)

    RULES = RuleSet("decisor", [Rule("para_x", S.X, when=lambda s: s.a), Rule("para_y", S.Y, when=lambda s: s.b)])

    def __init__(self):
        super().__init__()
        self.a = self.b = False

    @state(S.DECIDE)
    def _decide(self):
        self.decide(self.RULES)


def test_fsm_decide_da_goto_e_guarda_motivo():
    m = M()
    m.b = True
    m.scan()
    assert m.state is S.Y
    assert m.history[-1].reason == "decisor.para_y"
    assert m.last_decision.rule.name == "para_y"
    assert "para_x" in m.explain(M.RULES)


def test_fsm_decide_sem_regra_nao_muda_estado():
    m = M()
    m.scan()
    assert m.state is S.DECIDE and m.last_decision.rule is None
