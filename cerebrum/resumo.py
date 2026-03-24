"""
Resumo diário — gera um resumo das notas capturadas no dia.
"""

import os
import json
import anthropic
from datetime import date
from .leitor import listar, ler
from .supabase_sync import get_supabase_client

RESUMO_PROMPT = """Gera um resumo conciso do dia do Ricardo com base nestas notas e dados.

DATA: {data}

NOTAS DO VAULT (hoje):
{notas}

DADOS DO SUPABASE (criados hoje):
{dados_supabase}

---

Formato do resumo (Markdown):
📊 *Resumo do dia — {data}*

*Notas capturadas:* X
*Categorias:* lista

Depois um parágrafo curto com os pontos principais do dia.

Se houve entradas no Agency OS (clientes, projetos, reuniões, orçamentos), menciona.

Termina com "Pendentes" se houver coisas por resolver.

Sê direto, informal, português europeu. Máximo 300 palavras.
"""


def gerar_resumo_diario() -> str:
    """Gera resumo das notas do dia atual."""
    hoje = date.today().isoformat()

    # Notas do vault de hoje
    todas = listar(limite=100)
    notas_hoje = [n for n in todas if n.get("data") == hoje]

    if not notas_hoje:
        return ""

    conteudos = []
    categorias = set()
    for nota in notas_hoje:
        conteudo = ler(nota["caminho"])
        conteudos.append(f"[{nota['categoria']}] {conteudo[:500]}")
        categorias.add(nota["categoria"])

    # Dados do Supabase de hoje
    dados_supabase = ""
    try:
        sb = get_supabase_client()
        for tabela in ["clients", "projects", "meetings", "quotes"]:
            try:
                resultado = sb.table(tabela).select("*").gte("created_at", f"{hoje}T00:00:00").execute()
                if resultado.data:
                    dados_supabase += f"\n{tabela}: {json.dumps(resultado.data, ensure_ascii=False)}\n"
            except Exception:
                pass
    except Exception:
        dados_supabase = "Supabase indisponível"

    if not dados_supabase:
        dados_supabase = "Sem entradas novas"

    # Gerar resumo com Claude
    client = anthropic.Anthropic()
    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": RESUMO_PROMPT.format(
            data=hoje,
            notas="\n---\n".join(conteudos),
            dados_supabase=dados_supabase,
        )}],
    )

    return resposta.content[0].text.strip()
