# plcfsm — CLP em Python, lado a lado

Escreva em Python o `CASE eEstado OF` do seu CODESYS (Structured Text, IEC 61131-3) **com a mesma lógica de varredura**:
`eEstado := X`, `R_TRIG`, `TON`, `SR`, pedido/eco e `IF/ELSIF` por prioridade se comportam como no CLP.
Em troca, você ganha o que o CLP não dá: o **motivo** de cada transição, `explain()` de "por que essa regra não disparou"
e diagrama gerado do próprio código.

**▶ [Veja a comparação ST × Python lado a lado](https://tuliosalustiano27.github.io/MaquinaEstados_Python/)**
(fonte: [`docs/index.html`](docs/index.html))

## Em 20 segundos

ST:

```
E_ESTADO.AVANCANDO:
    IF ixCilindroAvancado THEN
        eEstado := E_ESTADO.FURANDO;
    ELSIF tmrEstado.ET >= TIMEOUT_CILINDRO THEN
        eEstado := E_ESTADO.FALHA;
    END_IF
```

Python:

```python
@state(Estado.AVANCANDO)
def _avancando(self):
    if self.io.ix_cilindro_avancado:
        self.goto(Estado.FURANDO)
    elif self.timed_out(self.TIMEOUT_CILINDRO):
        self.goto(Estado.FALHA, "cilindro não avançou a tempo")
```

## Instalar

```
pip install git+https://github.com/tuliosalustiano27/MaquinaEstados_Python.git
```

Python 3.10 ou mais novo. Sem dependências.

## Rodar os exemplos e os testes

```
git clone https://github.com/tuliosalustiano27/MaquinaEstados_Python.git
cd MaquinaEstados_Python
pip install -e . pytest
python -m pytest -q
python -m plcfsm examples.minimo:Furadeira              # estados inalcançáveis / sem saída
python -m plcfsm examples.minimo:Furadeira --mermaid    # diagrama stateDiagram-v2
```

Sem instalar, aponte o caminho: `PYTHONPATH=src:.` (Linux/macOS) ou `$env:PYTHONPATH="src;."` (PowerShell).

## O que tem

```
src/plcfsm/   core.py (StateMachine, @state, run)       blocks.py (R_TRIG, TON, SR, Handshake...)
              rules.py (T, AND/OR/NOT, Rule, RuleSet)   graph.py (analyze, to_mermaid)
examples/     minimo.py   estação de furação completa (~100 linhas)
              padroes.py  on_entry, latch SR, pedido/eco, tabela de decisão, override global
tests/        uma suíte por módulo; test_docs_html.py garante que a página não mente
docs/         index.html  a comparação ST x Python (abre offline no navegador)
```

`tests/test_docs_html.py` confere que todo código Python da página é o código real de `examples/`, que o ST da máquina
completa descreve a mesma máquina (enum, constantes, entradas e transições) e que toda saída mostrada é a saída real.

## Limites

Python **não é tempo real determinístico** e esta biblioteca **não** serve de intertravamento de segurança.
Use para supervisão, coordenação, simulação, gêmeo digital e ferramentas de teste.
