from examples.padroes import DECISOR, IO, Dosadora, Estado, Pedido


def ciclo(m, clock, n=1, dt=0.1):
    for _ in range(n):
        clock.advance(dt)
        m.scan()


def pulso(m, clock, io, campo):
    setattr(io, campo, True)
    ciclo(m, clock)
    setattr(io, campo, False)


def test_ciclo_feliz_com_handshake_e_on_entry(clock):
    io = IO()
    m = Dosadora(io, clock=clock)
    pulso(m, clock, io, "ix_start")
    assert m.state is Estado.PEDINDO_MATERIAL
    ciclo(m, clock, n=3)
    assert m.req_pedido.value is Pedido.ALIMENTAR and m.req_pedido.active   # pedido fica ligado
    io.e_eco_pedido = Pedido.ALIMENTAR                                      # o alimentador aceita
    ciclo(m, clock)
    assert m.state is Estado.DOSANDO and not m.req_pedido.active
    assert m.doses == 0                                                     # on_entry roda na varredura seguinte
    ciclo(m, clock)
    assert m.doses == 1
    ciclo(m, clock, n=5)
    assert m.doses == 1                                                     # só uma vez por entrada
    pulso(m, clock, io, "ix_dose_pronta")
    assert m.state is Estado.PARADO
    assert [t.reason for t in m.history] == ["decisor.inicia", "alimentador confirmou", "dose concluída"]


def test_alimentador_que_nao_responde_leva_a_falha_e_cancela_o_pedido(clock):
    io = IO()
    m = Dosadora(io, clock=clock)
    pulso(m, clock, io, "ix_start")
    ciclo(m, clock, n=49)
    assert m.state is Estado.PEDINDO_MATERIAL
    ciclo(m, clock, n=2)
    assert m.state is Estado.FALHA and not m.req_pedido.active
    assert m.history[-1].reason == "alimentador não respondeu"


def test_latch_sr_tem_set_dominante_e_so_solta_com_reset_sem_set(clock):
    io = IO(ix_nivel_baixo=True)
    m = Dosadora(io, clock=clock)
    ciclo(m, clock)
    assert m.sr_falha.q
    pulso(m, clock, io, "ix_reset")
    assert m.sr_falha.q                       # nível ainda baixo: o SET vence o RESET
    io.ix_nivel_baixo = False
    ciclo(m, clock)
    assert m.sr_falha.q                       # SET sumiu, mas o latch guarda
    pulso(m, clock, io, "ix_reset")
    assert not m.sr_falha.q


def test_decisor_por_prioridade_e_explain(clock):
    io = IO(ix_nivel_baixo=True)
    m = Dosadora(io, clock=clock)
    ciclo(m, clock)                           # latch de falha ligado: o decisor manda para FALHA
    assert m.state is Estado.FALHA
    m.goto(Estado.PARADO)
    m.rtrig_start.q = True                    # simula a borda de subida deste ciclo
    assert m.explain(DECISOR) == (
        "[decisor] regra escolhida: falha\n"
        "  1. falha -> FALHA  [+] ESCOLHIDA\n"
        "  2. inicia -> PEDINDO_MATERIAL  [-] bloqueada por: NOT srFalha.Q"
    )


def test_override_global_vence_o_ramo_e_cancela_o_pedido(clock):
    io = IO()
    m = Dosadora(io, clock=clock)
    pulso(m, clock, io, "ix_start")
    ciclo(m, clock)
    assert m.req_pedido.active
    io.ix_emergencia = True
    ciclo(m, clock)
    assert m.state is Estado.EMERGENCIA and not m.req_pedido.active
    io.ix_emergencia = False
    ciclo(m, clock)
    assert m.state is Estado.PARADO
