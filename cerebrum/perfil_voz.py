"""
Perfil de Voz — aprende o tom e estilo do Ricardo ao longo do tempo.
Persistido no Supabase (tabela voice_profile).

SQL necessário no Supabase:
    CREATE TABLE IF NOT EXISTS voice_profile (
        id INT DEFAULT 1 PRIMARY KEY,
        perfil JSONB NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
"""

import re
import json
import logging
import anthropic
from datetime import date

log = logging.getLogger(__name__)

PERFIL_DEFAULT = {
    "ultima_atualizacao": None,
    "total_notas_analisadas": 0,
    "expressoes_frequentes": [],
    "vocabulario_preferido": [],
    "tom": "",
    "padrao_frases": "",
    "exemplos_reais": [],
}

EXTRACTION_PROMPT = """Analisa este texto falado pelo Ricardo e extrai padrões de linguagem.

TEXTO:
{texto}

PERFIL ATUAL (já recolhido de notas anteriores):
{perfil_atual}

---

Extrai:
1. Expressões ou palavras naturais dele (ex: "tipo", "na boa", "bora", "foda-se")
2. Tom geral (direto? informal? técnico? motivacional?)
3. Padrões de frase (curtas? longas? usa perguntas retóricas?)
4. Uma frase-exemplo que capture bem a voz dele NESTE texto

Responde com JSON:
{{
  "novas_expressoes": ["..."],
  "tom_observado": "...",
  "padrao_frases": "...",
  "exemplo_frase": "..."
}}
"""


def carregar_perfil() -> dict:
    try:
        from .supabase_sync import get_supabase_client
        sb = get_supabase_client()
        resultado = sb.table("voice_profile").select("perfil").eq("id", 1).limit(1).execute()
        if resultado.data:
            return resultado.data[0]["perfil"]
    except Exception as e:
        log.warning(f"voice_profile load: {e}")
    return PERFIL_DEFAULT.copy()


def guardar_perfil(perfil: dict):
    try:
        from .supabase_sync import get_supabase_client
        sb = get_supabase_client()
        sb.table("voice_profile").upsert(
            {"id": 1, "perfil": perfil},
            on_conflict="id",
        ).execute()
    except Exception as e:
        log.warning(f"voice_profile save: {e}")


def atualizar_perfil(client: anthropic.Anthropic, texto_original: str):
    """Analisa o texto bruto e atualiza o perfil de voz."""
    if len(texto_original.strip()) < 30:
        return  # Textos curtos não têm padrões úteis

    perfil = carregar_perfil()

    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(
            texto=texto_original,
            perfil_atual=json.dumps(perfil, ensure_ascii=False),
        )}],
    )

    raw = resposta.content[0].text.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return

    dados = json.loads(match.group())

    # Merge novas expressões (sem duplicados)
    existentes = set(perfil.get("expressoes_frequentes", []))
    for expr in dados.get("novas_expressoes", []):
        existentes.add(expr.lower().strip())
    perfil["expressoes_frequentes"] = sorted(existentes)[:50]

    # Atualiza tom e padrão
    if dados.get("tom_observado"):
        perfil["tom"] = dados["tom_observado"]
    if dados.get("padrao_frases"):
        perfil["padrao_frases"] = dados["padrao_frases"]

    # Guarda exemplo (max 10, roda os antigos)
    if dados.get("exemplo_frase"):
        exemplos = perfil.get("exemplos_reais", [])
        exemplos.append(dados["exemplo_frase"])
        perfil["exemplos_reais"] = exemplos[-10:]

    perfil["total_notas_analisadas"] = perfil.get("total_notas_analisadas", 0) + 1
    perfil["ultima_atualizacao"] = date.today().isoformat()

    guardar_perfil(perfil)


def obter_prompt_tom() -> str:
    """Retorna uma secção de prompt com o perfil de voz do Ricardo."""
    perfil = carregar_perfil()
    if not perfil.get("expressoes_frequentes"):
        return ""

    return f"""
PERFIL DE VOZ DO RICARDO (aprendido de {perfil['total_notas_analisadas']} notas):
- Expressões: {', '.join(perfil['expressoes_frequentes'][:20])}
- Tom: {perfil.get('tom', 'direto e informal')}
- Frases: {perfil.get('padrao_frases', '')}
- Exemplos reais: {json.dumps(perfil['exemplos_reais'][-5:], ensure_ascii=False)}

USA este perfil para que o conteúdo soe autêntico — como o Ricardo fala de verdade.
"""
