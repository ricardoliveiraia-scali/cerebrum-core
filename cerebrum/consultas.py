"""
Consultas — responde a perguntas do Ricardo usando dados do Supabase e vault.
"""

import os
import json
import anthropic

QUERY_PROMPT = """O Ricardo fez uma pergunta. Tens os seguintes dados disponíveis.
Responde de forma direta, clara, em português europeu, como se estivesses a falar com ele.

PERGUNTA: {pergunta}

DADOS DO SUPABASE:
{dados_supabase}

NOTAS DO VAULT:
{dados_vault}

Se não tens dados suficientes, diz honestamente. Nunca inventes.
"""


def responder_pergunta(client: anthropic.Anthropic, pergunta: str) -> str:
    dados_supabase = "Supabase não configurado"
    dados_vault = ""

    # Tenta Supabase
    try:
        from .supabase_sync import get_supabase_client
        sb = get_supabase_client()

        tabelas = ["clients", "projects", "meetings", "quotes"]
        for tabela in tabelas:
            try:
                resultado = sb.table(tabela).select("*").limit(50).execute()
                if resultado.data:
                    dados_supabase = json.dumps(resultado.data, ensure_ascii=False, indent=2)
            except Exception:
                pass
    except Exception:
        pass

    # Tenta vault
    try:
        from .leitor import buscar
        notas = buscar(texto=pergunta.split()[0] if pergunta else None, limite=5)
        if notas:
            dados_vault = "\n---\n".join([n.get("conteudo", "") for n in notas])
    except Exception:
        pass

    resposta = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": QUERY_PROMPT.format(
            pergunta=pergunta,
            dados_supabase=dados_supabase,
            dados_vault=dados_vault,
        )}],
    )

    return resposta.content[0].text.strip()
