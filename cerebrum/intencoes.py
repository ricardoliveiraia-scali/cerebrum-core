"""
Deteção de intenção — primeiro passo antes de classificar.

3 intenções:
- guardar: nota, ideia, reflexão → classificar e guardar
- pergunta: quer saber algo → consultar Supabase/vault e responder
- comando: quer fazer algo → executar skill
"""

import re
import json
import anthropic

INTENT_PROMPT = """Analisa a mensagem do Ricardo e classifica a INTENÇÃO.

MENSAGEM:
{input}

---

Tipos de intenção:
- "guardar": É uma nota, ideia, reflexão, resumo, briefing, algo que aconteceu, notícia — algo para GUARDAR
- "pergunta": É uma pergunta — quer SABER algo ("quanto faturei?", "quem é o cliente X?", "quantos projetos tenho?")
- "comando": É uma ordem/pedido — quer FAZER algo ("cria carrossel", "gera proposta", "agenda reunião")

Responde APENAS com JSON:
{{
  "intencao": "guardar|pergunta|comando",
  "confianca": "alta|media|baixa",
  "detalhe": "<1 frase sobre o que o Ricardo quer>",
  "skill": "<nome da skill se comando, senão null>"
}}
"""


def detetar_intencao(client: anthropic.Anthropic, texto: str) -> dict:
    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": INTENT_PROMPT.format(input=texto)}],
    )

    raw = resposta.content[0].text.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return {"intencao": "guardar", "confianca": "baixa", "detalhe": "fallback"}

    return json.loads(match.group())
