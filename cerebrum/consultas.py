"""
Consultas — responde a perguntas do Ricardo usando dados do Supabase e vault.
"""

import logging
import anthropic

log = logging.getLogger(__name__)

QUERY_PROMPT = """O Ricardo fez uma pergunta. Tens os seguintes dados disponíveis.
Responde de forma direta, clara, em português europeu, como se estivesses a falar com ele.

{contexto_sessao}

PERGUNTA: {pergunta}

NOTAS RELEVANTES:
{dados_vault}

Se não tens dados suficientes, diz honestamente. Nunca inventes.
"""


def responder_pergunta(client: anthropic.Anthropic, pergunta: str, contexto: str = "") -> str:
    dados_vault = ""

    # 1. Pesquisa semântica (principal)
    try:
        from .embeddings import pesquisar_semantico
        resultados_sem = pesquisar_semantico(pergunta, limite=8)
        if resultados_sem:
            dados_vault = "\n---\n".join([
                f"[{r.get('categoria', '?')}] {r.get('conteudo', '')[:800]}"
                for r in resultados_sem
            ])
            log.info(f"Pesquisa semântica: {len(resultados_sem)} resultados")
    except Exception as e:
        log.warning(f"Pesquisa semântica: {e}")

    # 2. Fallback: text search em vault_notes (se semântica vazia)
    if not dados_vault:
        try:
            from .supabase_sync import get_supabase_client
            sb = get_supabase_client()
            palavras = [p for p in pergunta.split() if len(p) > 3]
            resultados_sb = []
            for palavra in palavras[:3]:
                r = sb.table("vault_notes").select("categoria,titulo,conteudo").ilike(
                    "conteudo", f"%{palavra}%"
                ).limit(5).execute()
                if r.data:
                    resultados_sb.extend(r.data)
            if resultados_sb:
                dados_vault = "\n---\n".join([
                    f"[{r.get('categoria', '?')}] {r.get('conteudo', '')[:800]}"
                    for r in resultados_sb
                ])
                log.info(f"Fallback vault_notes: {len(resultados_sb)} resultados")
        except Exception as e:
            log.warning(f"Fallback vault_notes: {e}")

    if not dados_vault:
        dados_vault = "Sem notas encontradas."

    contexto_sessao = ""
    if contexto:
        contexto_sessao = f"CONTEXTO DA CONVERSA:\n{contexto}\n"

    resposta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": QUERY_PROMPT.format(
            pergunta=pergunta,
            dados_vault=dados_vault,
            contexto_sessao=contexto_sessao,
        )}],
    )

    return resposta.content[0].text.strip()
