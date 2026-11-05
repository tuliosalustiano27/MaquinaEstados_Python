"""python -m plcfsm modulo:Classe [--mermaid]  -> análise do grafo de uma máquina de estados."""
from __future__ import annotations

import importlib
import os
import sys

from .graph import analyze, to_mermaid


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or ":" not in args[0]:
        print("uso: python -m plcfsm modulo:Classe [--mermaid]", file=sys.stderr)
        return 2
    sys.path.insert(0, os.getcwd())
    module_name, class_name = args[0].split(":", 1)
    cls = getattr(importlib.import_module(module_name), class_name)
    if "--mermaid" in argv:
        print(to_mermaid(cls))
    else:
        print(analyze(cls).summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
