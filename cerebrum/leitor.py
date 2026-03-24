"""
Leitor do vault — para outros sistemas consultarem o conteúdo do Cerebrum.
"""

import os
import re
from datetime import date
from .categorias import CATEGORIAS

VAULT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vault")


def listar(categoria: str = None, limite: int = 20) -> list[dict]:
    """
    Lista notas do vault.
    - categoria: filtrar por categoria (None = todas)
    - limite: número máximo de resultados
    """
    pastas = (
        [CATEGORIAS[categoria]["pasta"]] if categoria and categoria in CATEGORIAS
        else [v["pasta"] for v in CATEGORIAS.values()]
    )

    notas = []
    for pasta in pastas:
        caminho_pasta = os.path.join(VAULT_ROOT, pasta)
        if not os.path.exists(caminho_pasta):
            continue
        for nome in sorted(os.listdir(caminho_pasta), reverse=True):
            if nome.endswith(".md"):
                notas.append({
                    "categoria": pasta,
                    "ficheiro": nome,
                    "caminho": os.path.join(caminho_pasta, nome),
                    "data": nome[:10] if len(nome) >= 10 else None,
                })

    return notas[:limite]


def ler(caminho: str) -> str:
    """Lê o conteúdo de uma nota."""
    with open(caminho, "r", encoding="utf-8") as f:
        return f.read()


def buscar(categoria: str = None, tags: list[str] = None, texto: str = None, limite: int = 10) -> list[dict]:
    """
    Busca notas por categoria, tags ou texto livre.
    Retorna lista de dicts com metadata + conteúdo.
    """
    notas = listar(categoria=categoria, limite=200)
    resultados = []

    for nota in notas:
        conteudo = ler(nota["caminho"])

        if tags:
            if not any(tag in conteudo for tag in tags):
                continue

        if texto:
            if texto.lower() not in conteudo.lower():
                continue

        nota["conteudo"] = conteudo
        resultados.append(nota)

        if len(resultados) >= limite:
            break

    return resultados
