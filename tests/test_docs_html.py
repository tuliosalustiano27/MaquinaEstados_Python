"""Guardas de docs/index.html: a página compara ST x Python, então ela não pode mentir.

- estrutura válida, autocontida, âncoras e arquivos citados existem;
- toda API citada existe em ``plcfsm``;
- todo código Python mostrado é o código real de ``examples/`` (comparado por AST, sem anotações de tipo);
- o ST da máquina completa descreve a MESMA máquina que o Python (enum, constantes, entradas, transições);
- todo ST está balanceado (IF/END_IF, CASE/END_CASE, VAR/END_VAR, TYPE/END_TYPE);
- toda saída mostrada na página é a saída real do código mostrado.
"""
import ast
import contextlib
import inspect
import io
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

import plcfsm
from examples import minimo, padroes
from examples.minimo import Estado, Furadeira
from plcfsm import StateMachine, analyze

RAIZ = Path(__file__).resolve().parent.parent
PAGINA = (RAIZ / "docs" / "index.html").read_text(encoding="utf-8")
SEM_SCRIPT = re.sub(r"<script.*?</script>", "", PAGINA, flags=re.S)
REPO = "https://github.com/tuliosalustiano27/MaquinaEstados_Python"
VOID = {"meta", "link", "br", "hr", "img", "input", "col", "area", "base", "source", "wbr"}


# ----------------------------------------------------------------------------- leitura da página
class _Pagina(HTMLParser):
    """Estrutura (tags balanceadas, ids, âncoras) e blocos <pre class="code">."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pilha, self.erros, self.ids, self.ancoras = [], [], [], []
        self.blocos = []          # dicts: lang, check, expect, texto
        self._bloco = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if "id" in d:
            self.ids.append(d["id"])
        if tag == "a" and d.get("href", "").startswith("#"):
            self.ancoras.append(d["href"][1:])
        if tag == "pre" and "code" in d.get("class", "").split():
            self._bloco = {"lang": d.get("data-lang"), "check": d.get("data-check", "exemplo"),
                           "expect": d.get("data-expect"), "texto": ""}
        if tag not in VOID:
            self.pilha.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if tag == "pre" and self._bloco is not None:
            self.blocos.append(self._bloco)
            self._bloco = None
        if not self.pilha or self.pilha[-1] != tag:
            self.erros.append(f"</{tag}> inesperado em {self.getpos()}")
            if tag in self.pilha:
                while self.pilha and self.pilha.pop() != tag:
                    pass
        else:
            self.pilha.pop()

    def handle_data(self, data):
        if self._bloco is not None:
            self._bloco["texto"] += data


_P = _Pagina()
_P.feed(PAGINA)
_P.close()


def _blocos(lang):
    return [b["texto"] for b in _P.blocos if b["lang"] == lang]


# ----------------------------------------------------------------------------- estrutura
def test_estrutura_balanceada_ids_unicos_e_ancoras_validas():
    assert not _P.erros and not _P.pilha, (_P.erros[:3], _P.pilha[:3])
    assert len(_P.ids) == len(set(_P.ids)), {i for i in _P.ids if _P.ids.count(i) > 1}
    assert [a for a in _P.ancoras if a not in _P.ids] == []
    assert len(_P.ancoras) >= 14


def test_pagina_e_autocontida():
    recursos = re.findall(r"<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)=\"(?:https?:)?//", PAGINA)
    assert recursos == [], "a página não pode depender de CDN, fonte ou imagem externa"
    assert "url(http" not in PAGINA
    assert PAGINA.count("<script") == 1
    assert len(PAGINA.encode("utf-8")) < 300_000


def test_arquivos_e_links_citados_existem():
    for caminho in set(re.findall(rf'href="{re.escape(REPO)}/blob/main/([^"]+)"', PAGINA)):
        assert (RAIZ / caminho).is_file(), f"link para {caminho}, que não existe no repo"
    citados = set(re.findall(r"<code>((?:examples|tests|docs|src)/[\w./]+)</code>", SEM_SCRIPT))
    assert {"examples/minimo.py", "examples/padroes.py"} <= citados
    assert sorted(c for c in citados if not (RAIZ / c).exists()) == []
    assert REPO in PAGINA
    assert f"pip install git+{REPO}.git" in PAGINA


# ----------------------------------------------------------------------------- API citada
def test_toda_api_citada_existe():
    texto = SEM_SCRIPT
    nomes_modulo = ["StateMachine", "state", "on_entry", "on_exit", "run", "RTrig", "FTrig", "SR", "RS", "TON", "TOF",
                    "TP", "Handshake", "T", "AND", "OR", "NOT", "Rule", "RuleSet", "analyze", "to_mermaid"]
    da_classe = ["goto", "scan", "reset", "state_time", "timed_out", "snapshot", "decide", "explain", "read_inputs",
                 "on_state_change", "before_case", "after_case", "write_outputs", "idle_states", "states", "initial"]
    da_instancia = ["history", "scan_transitions", "state_scans"]
    for n in nomes_modulo:
        assert hasattr(plcfsm, n), f"plcfsm.{n} não existe"
        assert re.search(rf"\b{re.escape(n)}\b", texto), f"{n} deveria estar citado na página"
    for n in da_classe:
        assert hasattr(StateMachine, n), f"StateMachine.{n} não existe"
        assert n in texto, f"{n} deveria estar citado na página"
    m = Furadeira(minimo.IO(), clock=lambda: 0.0)
    for n in da_instancia:
        assert hasattr(m, n), f"instância sem {n}"
        assert n in texto, f"{n} deveria estar citado na página"
    h = plcfsm.Handshake(0)
    for n in ("request", "release", "value", "active"):
        assert hasattr(h, n) and n in texto
    assert "fire_initial_entry" in texto
    assert "fire_initial_entry" in inspect.signature(StateMachine.__init__).parameters
    assert {"name", "goto", "when", "doc", "enabled"} <= set(plcfsm.Rule.__dataclass_fields__)
    assert "enabled=False" in texto


# ----------------------------------------------------------------------------- Python mostrado == examples/
class _Norm(ast.NodeTransformer):
    """Tira docstrings e anotações de função: a página mostra os métodos sem tipos."""

    @staticmethod
    def _sem_doc(corpo):
        if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], "value", None), ast.Constant) \
                and isinstance(corpo[0].value.value, str):
            return corpo[1:] or [ast.Pass()]
        return corpo

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        node.returns = None
        a = node.args
        for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
            arg.annotation = None
        node.body = self._sem_doc(node.body)
        return node

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        node.body = self._sem_doc(node.body)
        return node


def _linha_limpa(linha):
    return re.sub(r"\s+#.*$", "", linha).strip()


def _reais():
    funcoes, classes, linhas = {}, {}, set()
    for mod in (minimo, padroes):
        fonte = inspect.getsource(mod)
        arvore = _Norm().visit(ast.parse(fonte))
        for n in ast.walk(arvore):
            if isinstance(n, ast.FunctionDef):
                funcoes.setdefault(n.name, set()).add(ast.dump(n))
            elif isinstance(n, ast.ClassDef):
                classes.setdefault(n.name, set()).add(ast.dump(n))
        linhas |= {_linha_limpa(l) for l in fonte.splitlines() if _linha_limpa(l) and not l.strip().startswith("#")}
    return funcoes, classes, linhas


def test_todo_python_mostrado_e_o_codigo_real_dos_exemplos():
    funcoes, classes, linhas = _reais()
    blocos = [b for b in _P.blocos if b["lang"] == "py"]
    assert len(blocos) >= 12
    conferidos = 0
    for i, b in enumerate(blocos, 1):
        codigo = b["texto"]
        try:
            arvore = ast.parse(codigo)
        except SyntaxError as exc:
            raise AssertionError(f"bloco python #{i} não compila: {exc}\n{codigo[:200]}") from exc
        if b["check"] != "exemplo":
            continue
        arvore = _Norm().visit(arvore)
        for no in arvore.body:
            if isinstance(no, ast.FunctionDef):
                assert ast.dump(no) in funcoes.get(no.name, set()), f"bloco #{i}: {no.name}() difere dos exemplos"
            elif isinstance(no, ast.ClassDef):
                assert ast.dump(no) in classes.get(no.name, set()), f"bloco #{i}: class {no.name} difere dos exemplos"
            else:
                for linha in codigo.splitlines()[no.lineno - 1:no.end_lineno]:
                    if _linha_limpa(linha):
                        assert _linha_limpa(linha) in linhas, f"bloco #{i}: linha fora dos exemplos: {linha!r}"
            conferidos += 1
    assert conferidos >= 20


# ----------------------------------------------------------------------------- ST balanceado e == Python
def _sem_comentario_st(texto):
    return re.sub(r"\(\*.*?\*\)", "", texto, flags=re.S)


def test_todo_st_esta_balanceado():
    blocos = _blocos("st")
    assert len(blocos) >= 10
    pares = [(r"\bIF\b", r"\bEND_IF\b"), (r"\bCASE\b", r"\bEND_CASE\b"), (r"\bTYPE\b", r"\bEND_TYPE\b"),
             (r"\bVAR(?:_INPUT|_OUTPUT)?\b", r"\bEND_VAR\b")]
    for i, b in enumerate(blocos, 1):
        s = _sem_comentario_st(b)
        for abre, fecha in pares:
            assert len(re.findall(abre, s)) == len(re.findall(fecha, s)), f"ST #{i}: {abre} x {fecha} desbalanceado\n{b[:160]}"
        assert s.count("(") == s.count(")"), f"ST #{i}: parênteses desbalanceados"


def _st_maquina_completa():
    achados = [b for b in _blocos("st") if "FUNCTION_BLOCK FB_Furadeira" in b]
    assert len(achados) == 1
    return achados[0]


def _snake(nome):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", nome).lower()


def test_st_da_maquina_completa_descreve_a_mesma_maquina_que_o_python():
    st = _sem_comentario_st(_st_maquina_completa())

    # enum: mesmos nomes e MESMOS números
    corpo_enum = re.search(r"TYPE E_ESTADO\s*:\s*\((.*?)\);\s*END_TYPE", st, re.S).group(1)
    assert {n: int(v) for n, v in re.findall(r"(\w+)\s*:=\s*(\d+)", corpo_enum)} == {m.name: m.value for m in Estado}

    # constantes de tempo (T#2S == 2.0 s)
    consts = {n: float(v) for n, v in re.findall(r"(\w+)\s*:\s*TIME\s*:=\s*T#(\d+)S", st)}
    assert consts == {"TEMPO_FURO": Furadeira.TEMPO_FURO, "TIMEOUT_CILINDRO": Furadeira.TIMEOUT_CILINDRO}

    # entradas e saídas
    def nomes(secao):
        bloco = re.search(rf"{secao}\s(.*?)END_VAR", st, re.S).group(1)
        return {_snake(n.strip()) for ln in bloco.splitlines() if ":" in ln for n in ln.split(":")[0].split(",")}
    assert nomes("VAR_INPUT") == set(minimo.IO.__dataclass_fields__)
    m = Furadeira(minimo.IO(), clock=lambda: 0.0)
    assert all(hasattr(m, s) for s in nomes("VAR_OUTPUT"))

    # grafo de transições: ST (CASE) x Python (@state), via análise estática
    corpo = st[st.index("CASE eEstado OF"):st.index("END_CASE")]
    st_grafo, atual = {}, None
    for linha in corpo.splitlines():
        rot = re.match(r"\s*E_ESTADO\.(\w+):\s*$", linha)
        if rot:
            atual = rot.group(1)
            st_grafo[atual] = set()
        elif atual:
            for destino in re.findall(r":=\s*E_ESTADO\.(\w+)", linha):
                st_grafo[atual].add(destino)
    py_grafo = {s.name: set() for s in Estado}
    for e in analyze(Furadeira).edges:
        py_grafo[e.src.name].add(e.dst.name)
    assert st_grafo == py_grafo


# ----------------------------------------------------------------------------- saídas mostradas == saídas reais
def _esperado(nome):
    achados = [b["texto"].strip() for b in _P.blocos if b["expect"] == nome]
    assert len(achados) == 1, f"deveria haver 1 bloco de saída '{nome}'"
    return achados[0]


def _executa(codigo):
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        exec(compile(codigo, "<pagina>", "exec"), {"__name__": "__main__"})
    return saida.getvalue().strip()


@pytest.mark.parametrize("nome", ["run", "fakeclock"])
def test_blocos_executaveis_da_pagina_produzem_a_saida_mostrada(nome):
    codigo = [b["texto"] for b in _P.blocos if b["check"] == nome]
    assert len(codigo) == 1
    assert _executa(codigo[0]) == _esperado(nome)


def test_saida_do_explain_e_a_real():
    class Rel:
        t = 0.0

        def __call__(self):
            return self.t

    m = padroes.Dosadora(padroes.IO(ix_nivel_baixo=True), clock=Rel())
    m.scan()                                   # latch ligado
    m.goto(padroes.Estado.PARADO)
    m.rtrig_start.q = True                     # start deste ciclo
    assert m.explain(padroes.DECISOR) == _esperado("explain")


def test_saida_da_cli_e_a_real():
    from plcfsm.__main__ import main

    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        assert main(["examples.minimo:Furadeira"]) == 0
    assert saida.getvalue().strip() == _esperado("cli")
    assert "python -m plcfsm examples.minimo:Furadeira --mermaid" in PAGINA
