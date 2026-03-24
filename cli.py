#!/usr/bin/env python3
"""
Cerebrum CLI — entrada de texto ou ficheiro.

Uso:
    python cli.py                    # cola texto manualmente
    python cli.py nota.txt           # processa ficheiro
    python cli.py "texto direto"     # texto como argumento
"""

import sys
import os
from cerebrum.agente import processar


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Erro: define ANTHROPIC_API_KEY.", file=sys.stderr)
        sys.exit(1)

    # Texto como argumento direto
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if os.path.exists(arg):
            with open(arg, "r", encoding="utf-8") as f:
                texto = f.read()
        else:
            texto = " ".join(sys.argv[1:])
    else:
        # Input manual
        print("Cerebrum — cola o teu texto ou transcrição.")
        print("Ctrl+D para processar:")
        print("-" * 50)
        texto = sys.stdin.read()

    if not texto.strip():
        print("Erro: input vazio.", file=sys.stderr)
        sys.exit(1)

    print()
    processar(texto, verbose=True)


if __name__ == "__main__":
    main()
