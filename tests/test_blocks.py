from enum import Enum

from plcfsm import FTrig, Handshake, RS, RTrig, SR, TOF, TON, TP


def test_rtrig_pulso_de_uma_varredura():
    r = RTrig()
    assert [r(x) for x in (0, 1, 1, 1, 0, 1)] == [False, True, False, False, False, True]


def test_rtrig_ja_ligado_na_primeira_chamada_e_borda():
    assert RTrig()(True) is True


def test_ftrig_pulso_na_descida():
    f = FTrig()
    assert [f(x) for x in (0, 1, 1, 0, 0, 1, 0)] == [False, False, False, True, False, False, True]


def test_sr_set_dominante():
    sr = SR()
    assert sr(True, False) is True
    assert sr(False, False) is True      # mantém
    assert sr(False, True) is False      # reset
    assert sr(True, True) is True        # set vence


def test_rs_reset_dominante():
    rs = RS()
    assert rs(True, False) is True
    assert rs(False, False) is True
    assert rs(True, True) is False       # reset vence
    assert rs(False, True) is False


def test_ton(clock):
    t = TON(2.0, clock)
    assert t(True) is False
    clock.advance(1.9)
    assert t(True) is False and 1.8 < t.et < 2.0
    clock.advance(0.2)
    assert t(True) is True and t.et == 2.0
    assert t(False) is False and t.et == 0.0   # cai na hora
    clock.advance(5)
    assert t(True) is False                     # reinicia a contagem


def test_ton_reinicia_se_entrada_cai(clock):
    t = TON(2.0, clock)
    t(True)
    clock.advance(1.5)
    t(False)
    clock.advance(1.0)
    assert t(True) is False
    clock.advance(1.9)
    assert t(True) is False


def test_tof(clock):
    t = TOF(2.0, clock)
    assert t(True) is True
    assert t(False) is True                     # começa a contar a queda
    clock.advance(1.9)
    assert t(False) is True
    clock.advance(0.2)
    assert t(False) is False
    assert t(True) is True                      # sobe de novo na hora


def test_tof_reenergizar_durante_a_contagem(clock):
    t = TOF(2.0, clock)
    t(True)
    t(False)
    clock.advance(1.0)
    assert t(True) is True
    assert t(False) is True
    clock.advance(1.9)
    assert t(False) is True                     # contagem recomeçou do zero


def test_tp_pulso_nao_redisparavel(clock):
    t = TP(1.0, clock)
    assert t(True) is True
    clock.advance(0.5)
    assert t(False) is True                     # pulso segue mesmo com in_ em 0
    assert t(True) is True                      # nova borda no meio do pulso é ignorada
    clock.advance(0.6)
    assert t(True) is False                     # pulso acabou (in_ ainda em 1: sem novo pulso)
    clock.advance(1.0)
    assert t(True) is False
    t(False)
    assert t(True) is True                      # nova borda -> novo pulso


class Rotina(Enum):
    NENHUMA = 0
    IR = 1


def test_handshake_mantem_pedido_ate_confirmar():
    h = Handshake(Rotina.NENHUMA)
    assert h.request(Rotina.IR, ack=Rotina.NENHUMA) is False
    assert h.value is Rotina.IR and h.active
    assert h.request(Rotina.IR, ack=Rotina.NENHUMA) is False
    assert h.request(Rotina.IR, ack=Rotina.IR) is True
    assert h.value is Rotina.NENHUMA and not h.active


def test_handshake_release():
    h = Handshake(Rotina.NENHUMA)
    h.request(Rotina.IR, ack=Rotina.NENHUMA)
    h.release()
    assert h.value is Rotina.NENHUMA
