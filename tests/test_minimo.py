from examples.minimo import IO, Estado, Furadeira


def ciclo(m, clock, io, n=1, dt=0.1):
    for _ in range(n):
        clock.advance(dt)
        m.scan()


def test_ciclo_normal(clock):
    io = IO()
    m = Furadeira(io, clock=clock)
    ciclo(m, clock, io)
    assert m.state is Estado.PARADO and not m.qx_avancar

    io.ix_start = True
    ciclo(m, clock, io)
    io.ix_start = False
    assert m.state is Estado.AVANCANDO and m.qx_avancar and not m.qx_furar

    io.ix_cilindro_recuado, io.ix_cilindro_avancado = False, True
    ciclo(m, clock, io)
    assert m.state is Estado.FURANDO and m.qx_furar

    ciclo(m, clock, io, n=19)       # 1,9 s: ainda furando
    assert m.state is Estado.FURANDO
    ciclo(m, clock, io, n=2)        # passou de 2 s
    assert m.state is Estado.RECUANDO and not m.qx_furar

    io.ix_cilindro_recuado, io.ix_cilindro_avancado = True, False
    ciclo(m, clock, io)
    assert m.state is Estado.PARADO
    assert [t.dst.name for t in m.history] == ["AVANCANDO", "FURANDO", "RECUANDO", "PARADO"]


def test_start_com_cilindro_fora_da_posicao_e_ignorado(clock):
    io = IO(ix_cilindro_recuado=False)
    m = Furadeira(io, clock=clock)
    io.ix_start = True
    ciclo(m, clock, io, n=3)
    assert m.state is Estado.PARADO


def test_timeout_do_cilindro_leva_a_falha_e_desliga_saidas(clock):
    io = IO()
    m = Furadeira(io, clock=clock)
    io.ix_start = True
    ciclo(m, clock, io)
    io.ix_start = False
    io.ix_cilindro_recuado = False          # saiu da posição, mas nunca chega em "avançado"
    ciclo(m, clock, io, n=29)
    assert m.state is Estado.AVANCANDO and m.qx_avancar
    ciclo(m, clock, io, n=2)
    assert m.state is Estado.FALHA
    assert not m.qx_avancar and not m.qx_furar
    assert m.history[-1].reason == "cilindro não avançou a tempo"


def test_falha_so_sai_com_reset_e_cilindro_recuado(clock):
    io = IO()
    m = Furadeira(io, clock=clock)
    m.goto(Estado.FALHA)
    io.ix_reset = True
    io.ix_cilindro_recuado = False
    ciclo(m, clock, io, n=2)
    assert m.state is Estado.FALHA
    io.ix_cilindro_recuado = True
    ciclo(m, clock, io)
    assert m.state is Estado.PARADO


def test_timer_do_furo_zera_se_sair_de_furando(clock):
    io = IO()
    m = Furadeira(io, clock=clock)
    m.goto(Estado.FURANDO)
    ciclo(m, clock, io, n=15)               # 1,5 s de furo
    m.goto(Estado.RECUANDO)
    ciclo(m, clock, io)                     # TON recebe FALSE e zera
    m.goto(Estado.FURANDO)
    ciclo(m, clock, io, n=15)               # recomeça do zero: 1,5 s < 2 s
    assert m.state is Estado.FURANDO
