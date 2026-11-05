from enum import IntEnum

import pytest

from plcfsm import ConfigError, StateMachine, on_entry, on_exit, run, state


class S(IntEnum):
    A = 0
    B = 1
    C = 2
    ERRO = 3


class Outro(IntEnum):
    X = 0


class M(StateMachine):
    states = S
    initial = S.A
    idle_states = (S.ERRO,)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.log = []
        self.avancar = False
        self.override = False

    def read_inputs(self):
        self.log.append("in")

    def before_case(self):
        self.log.append("before")

    def after_case(self):
        self.log.append("after")
        if self.override:
            self.goto(S.ERRO, "override")

    def write_outputs(self):
        self.log.append("out")

    def on_state_change(self, old, new):
        self.log.append(f"chg:{getattr(old, 'name', None)}>{new.name}")

    @state(S.A)
    def _a(self):
        self.log.append("A")
        if self.avancar:
            self.goto(S.B, "avancou")
            self.log.append("A-depois-do-goto")   # goto NÃO encerra o ramo

    @state(S.B)
    def _b(self):
        self.log.append("B")
        self.goto(S.C)

    @state(S.C)
    def _c(self):
        self.log.append("C")

    @on_entry(S.B)
    def _entra_b(self):
        self.log.append("entry-B")

    @on_exit(S.A)
    def _sai_a(self):
        self.log.append("exit-A")


def test_ordem_das_fases_numa_varredura():
    m = M()
    m.scan()
    assert m.log == ["in", "before", "A", "after", "out"]


def test_goto_nao_encerra_ramo_nem_redespacha():
    m = M()
    m.avancar = True
    m.scan()
    # o ramo A terminou inteiro; B só roda na PRÓXIMA varredura
    assert m.log == ["in", "before", "A", "A-depois-do-goto", "after", "out"]
    assert m.state is S.B
    m.log.clear()
    m.scan()
    assert m.log[:5] == ["in", "exit-A", "chg:A>B", "entry-B", "before"]
    assert "B" in m.log


def test_entrada_so_na_primeira_varredura_depois_da_troca():
    m = M()
    m.avancar = True
    m.scan()
    m.scan()          # detecta A>B, roda B, B faz goto(C)
    m.scan()          # detecta B>C
    assert m.log.count("entry-B") == 1
    assert [l for l in m.log if l.startswith("chg:")] == ["chg:A>B", "chg:B>C"]


def test_primeira_varredura_nao_dispara_entrada_por_padrao():
    m = M()
    m.scan()
    assert not any(l.startswith("chg:") for l in m.log)


def test_fire_initial_entry():
    m = M(fire_initial_entry=True)
    m.scan()
    assert "chg:None>A" in m.log


def test_override_em_after_case_vence_e_estado_intermediario_e_invisivel():
    m = M()
    m.avancar = True
    m.override = True
    m.scan()
    assert m.state is S.ERRO
    assert [(t.src.name, t.dst.name, t.reason) for t in m.scan_transitions] == [
        ("A", "B", "avancou"),
        ("B", "ERRO", "override"),
    ]
    m.log.clear()
    m.scan()
    # a detecção de troca vê só A -> ERRO (prev_state ainda era A)
    assert "chg:A>ERRO" in m.log and "entry-B" not in m.log


def test_estado_idle_sem_ramo_nao_quebra():
    m = M()
    m.override = True
    m.scan()
    m.override = False
    m.scan()
    assert m.state is S.ERRO


def test_goto_para_o_mesmo_estado_nao_registra():
    m = M()
    m.goto(S.A)
    assert not m.history


def test_goto_com_enum_de_outro_tipo_falha():
    m = M()
    with pytest.raises(TypeError):
        m.goto(Outro.X)


def test_estado_sem_ramo_e_erro_de_configuracao():
    class Ruim(StateMachine):
        states = S
        initial = S.A

        @state(S.A, S.B, S.C)
        def _x(self):
            pass

    with pytest.raises(ConfigError, match="ERRO"):
        Ruim()


def test_membro_de_outro_enum_no_decorator_falha_na_definicao():
    with pytest.raises(ConfigError):
        class Ruim(StateMachine):
            states = S
            initial = S.A

            @state(Outro.X)
            def _x(self):
                pass


def test_dois_ramos_para_o_mesmo_estado_falha():
    with pytest.raises(ConfigError, match="dois ramos"):
        class Ruim(StateMachine):
            states = S
            initial = S.A

            @state(S.A)
            def _x(self):
                pass

            @state(S.A)
            def _y(self):
                pass


def test_sem_states_ou_initial_falha():
    class Vazia(StateMachine):
        pass

    with pytest.raises(ConfigError):
        Vazia()


def test_heranca_reaproveita_e_sobrescreve_ramos():
    class Filha(M):
        @state(S.C)
        def _c2(self):
            self.log.append("C-filha")

    f = Filha()
    f.goto(S.C)
    f.scan()
    assert "C-filha" in f.log and "C" not in f.log
    g = M()   # a mãe não é afetada
    g.goto(S.C)
    g.scan()
    assert "C" in g.log


def test_tempo_no_estado_e_watchdog(clock):
    m = M(clock=clock)
    m.scan()
    clock.advance(3)
    assert m.state_time == 3 and m.timed_out(3) and not m.timed_out(3.1)
    m.goto(S.B)
    m.scan()                       # entra em B: zera
    assert m.state_time == 0 and m.state_scans == 1
    m.scan()
    assert m.state_scans == 1 or m.state_scans == 2   # B já saiu para C; contador reinicia na troca


def test_state_scans_conta_varreduras_no_estado():
    m = M()
    for _ in range(3):
        m.scan()
    assert m.state_scans == 3


def test_excecao_no_ramo_ganha_contexto():
    class Quebra(StateMachine):
        states = S
        initial = S.A
        idle_states = (S.B, S.C, S.ERRO)

        @state(S.A)
        def _a(self):
            raise RuntimeError("boom")

    q = Quebra()
    with pytest.raises(RuntimeError) as info:
        q.scan()
    notes = getattr(info.value, "__notes__", [])
    assert any("estado=A" in n for n in notes)


def test_snapshot():
    m = M()
    m.avancar = True
    m.scan()
    snap = m.snapshot()
    assert snap["state"] == "B" and snap["state_value"] == 1
    assert snap["last_transition"]["from"] == "A" and snap["last_transition"]["reason"] == "avancou"


def test_reset_volta_ao_inicial():
    m = M()
    m.goto(S.C)
    m.reset()
    assert m.state is S.A and not m.history


def test_historico_tem_limite():
    m = M(history_size=3)
    for i in range(10):
        m.goto(S.B if i % 2 == 0 else S.A)
    assert len(m.history) == 3


def test_run_executa_n_varreduras_com_periodo():
    a, b = M(), M()
    sleeps = []

    class Rel:
        t = 0.0

        def __call__(self):
            return self.t

    rel = Rel()
    stats = run(a, b, period=0.1, max_scans=5, clock=rel, sleep=lambda s: (sleeps.append(round(s, 3)), setattr(rel, "t", rel.t + s)))
    assert stats.scans == 5 and a.scan_count == 5 and b.scan_count == 5
    assert stats.overruns == 0 and sleeps == [0.1] * 4


def test_run_conta_estouro_de_periodo():
    class Lenta(M):
        def read_inputs(self):
            rel.t += 0.5

    class Rel:
        t = 0.0

        def __call__(self):
            return self.t

    rel = Rel()
    stats = run(Lenta(), period=0.1, max_scans=3, clock=rel, sleep=lambda s: None)
    assert stats.overruns == 2 and stats.max_scan_time >= 0.5


def test_run_until():
    m = M()
    stats = run(m, period=0, until=lambda: m.scan_count >= 2, sleep=lambda s: None)
    assert stats.scans == 2


def test_run_sem_maquinas_falha():
    with pytest.raises(ValueError):
        run()
