"""
Consultas — responde a perguntas do Ricardo usando dados do Supabase e vault.
"""

import os
import json
import logging
import anthropic

log = logging.getLogger(__name__)

QUERY_PROMPT = """O Ricardo fez uma pergunta. Tens os seguintes dados disponíveis.
Responde de forma direta, clara, em português europeu, como se estivesses a falar com ele.

{contexto_sessao}

PERGUNTA: {pergunta}

DADOS DO SUPABASE:
{dados_supabase}

NOTAS DO VAULT:
{dados_vault}

Se não tens dados suficientes, diz honestamente. Nunca inventes.
"""


def responder_pergunta(client: anthropic.Anthropic, pergunta: str, contexto: str = "") -> str:
    dados_supabase = ""
    dados_vault = ""
    erros = []

    # Tenta Supabase
    try:
        from .supabase_sync import get_supabase_client
        sb = get_supabase_client()
        log.info("Supabase conectado com sucesso")

        resultados_sb = []
        tabelas = ["clients", "projects", "meetings", "quotes"]
        for tabela in tabelas:
            try:
                resultado = sb.table(tabela).select("*").limit(50).execute()
                count = len(resultado.data) if resultado.data else 0
                log.info(f"Tabela {tabela}: {count} registos")
                if resultado.data:
                    for row in resultado.data:
                        row["_tabela"] = tabela
                    resultados_sb.extend(resultado.data)
            except Exception as e:
                log.warning(f"Erro ao consultar {tabela}: {e}")
                erros.append(f"{tabela}: {e}")

        if resultados_sb:
            dados_supabase = json.dumps(resultados_sb, ensure_ascii=False, indent=2)
        else:
            dados_supabase = "Supabase ligado mas sem dados nas tabelas (clients, projects, meetings, quotes)."

    except Exception as e:
        log.error(f"Erro ao ligar ao Supabase: {e}")
        dados_supabase = f"Erro de ligação ao Supabase: {e}"

    # Tenta pesquisa semântica (embeddings)
    try:
        from .embeddings import pesquisar_semantico
        resultados_sem = pesquisar_semantico(pergunta, limite=5)
        if resultados_sem:
            dados_vault = "\n---\n".join([
                f"[{r.get('categoria', '?')}] {r.get('conteudo', '')[:500]}"
                for r in resultados_sem
            ])
    except Exception:
        pass

    # Fallback: pesquisa por texto no vault
    if not dados_vault:
        try:
            from .leitor import buscar
            palavras = [p for p in pergunta.split() if len(p) > 3]
            for palavra in palavras[:3]:
                notas = buscar(texto=palavra, limite=5)
                if notas:
                    dados_vault = "\n---\n".join([n.get("conteudo", "")[:500] for n in notas])
                    break
        except Exception:
            pass

    if not dados_vault:
        dados_vault = "Sem notas encontradas no vault."

    contexto_sessao = ""
    if contexto:
        contexto_sessao = f"CONTEXTO DA CONVERSA:\n{contexto}\n"

    resposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": QUERY_PROMPT.format(
            pergunta=pergunta,
            dados_supabase=dados_supabase,
            dados_vault=dados_vault,
            contexto_sessao=contexto_sessao,
        )}],
    )

    return resposta.content[0].text.strip()
