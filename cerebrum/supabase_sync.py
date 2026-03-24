"""
Supabase Sync — envia dados estruturados para o Agency OS (Supabase).
"""

import os
import re
import json
import anthropic
from datetime import date
from supabase import create_client, Client

TABLE_SCHEMAS = {
    "clients": {
        "prompt": "Extrai: name (nome da pessoa/empresa), email, phone, context (como chegou/contexto), notes (notas extra)",
    },
    "projects": {
        "prompt": "Extrai: name (nome do projeto), description (briefing), status (default: planning)",
    },
    "meetings": {
        "prompt": "Extrai: title, notes (o que foi discutido), action_items (próximos passos)",
    },
    "quotes": {
        "prompt": "Extrai: description, amount (valor numérico se mencionado), status (default: draft)",
    },
}

EXTRACTION_PROMPT = """Extrai campos estruturados deste conteúdo para guardar na base de dados.

CONTEÚDO:
{conteudo}

{campos_prompt}

Responde APENAS com JSON válido. Campos sem info = null. Valores numéricos sem texto.
"""


def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL e SUPABASE_KEY não definidos.")
    return create_client(url, key)


def extrair_campos(client: anthropic.Anthropic, conteudo: str, tabela: str) -> dict:
    schema = TABLE_SCHEMAS.get(tabela)
    if not schema:
        return {}

    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(
            conteudo=conteudo,
            campos_prompt=schema["prompt"],
        )}],
    )

    raw = resposta.content[0].text.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return {}

    campos = json.loads(match.group())
    # Remove campos None
    return {k: v for k, v in campos.items() if v is not None}


def sync_para_supabase(client_anthropic: anthropic.Anthropic, conteudo_md: str, tabela: str) -> dict:
    """Extrai campos e insere no Supabase. Retorna os dados inseridos."""
    campos = extrair_campos(client_anthropic, conteudo_md, tabela)

    if not campos:
        return {}

    sb = get_supabase_client()
    result = sb.table(tabela).insert(campos).execute()
    return result.data[0] if result.data else {}
