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
from cerebrum.agente import processar_com_intencao


def backfill_embeddings():
    """Gera embeddings para todas as notas existentes no vault."""
    from cerebrum.leitor import listar, ler
    from cerebrum.embeddings import guardar_embedding

    notas = listar(limite=500)
    total = len(notas)
    sucesso = 0
    falha = 0

    print(f"Backfill: {total} notas encontradas no vault.")

    for i, nota in enumerate(notas, 1):
        try:
            conteudo = ler(nota["caminho"])
            guardar_embedding(nota["caminho"], nota["categoria"], conteudo)
            sucesso += 1
            print(f"  [{i}/{total}] ✓ {nota['ficheiro']}")
        except Exception as e:
            falha += 1
            print(f"  [{i}/{total}] ✗ {nota['ficheiro']}: {e}")

    print(f"\nBackfill completo: {sucesso} ok, {falha} erros.")


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Erro: define ANTHROPIC_API_KEY.", file=sys.stderr)
        sys.exit(1)

    # Backfill embeddings
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        if not os.environ.get("OPENAI_API_KEY"):
            print("Erro: define OPENAI_API_KEY para gerar embeddings.", file=sys.stderr)
            sys.exit(1)
        backfill_embeddings()
        return

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
    resultado = processar_com_intencao(texto, verbose=True)
    tipo = resultado["tipo"]

    if tipo == "guardar":
        for r in resultado["resultado"]:
            print(f"✓ {r['caminho']}")
            if r.get("supabase_synced"):
                print("  ↗ Supabase")
            if r.get("lyra_synced"):
                print("  ↗ Lyra")
    elif tipo == "pergunta":
        print(f"\n{resultado['resultado']}")
    elif tipo == "comando":
        print(f"\n{resultado['resultado']}")


if __name__ == "__main__":
    main()
