"""
Categorias do Cerebrum.

Dois destinos:
- MARCA PESSOAL → vault local (ficheiros .md)
- AGENCY OS     → Supabase (sync automático)
"""

# =========================================================================
# MARCA PESSOAL — Ricardo Oliveira (vault local)
# =========================================================================

MARCA_PESSOAL = {
    "pessoal": {
        "pasta": "marca-pessoal/pessoal",
        "destino": "vault",
        "descricao": "Pensamentos do dia, coisas que aconteceram, reflexões, emoções, vida pessoal",
        "template": """---
tipo: pessoal
data: {data}
tags: [pessoal]
---

# {titulo}

## O que aconteceu / O que pensei

{conteudo}

## Para reter

""",
    },
    "empreendedor": {
        "pasta": "marca-pessoal/empreendedor",
        "destino": "vault",
        "descricao": "Jornada de empreendedor, desafios, crescimento, mindset, lições, vitórias e derrotas",
        "template": """---
tipo: empreendedor
data: {data}
tags: [empreendedor, jornada]
---

# {titulo}

## O que aconteceu

{conteudo}

## O que aprendi com isto

## Próximo passo

""",
    },
    "ia": {
        "pasta": "marca-pessoal/ia",
        "destino": "vault",
        "descricao": "Notícias sobre IA, ferramentas novas, aprendizagens, prompts, tendências",
        "template": """---
tipo: ia
data: {data}
tags: [ia]
---

# {titulo}

## O que é / O que aprendi

{conteudo}

## Como posso usar isto

""",
    },
    "instagram": {
        "pasta": "marca-pessoal/instagram",
        "destino": "vault",
        "descricao": "Ideias para posts de Instagram, hooks, carrosséis, reels, legendas, conteúdo",
        "template": """---
tipo: instagram
formato: post/carrossel/reel
estado: ideia
data: {data}
tags: [instagram, conteudo]
---

# {titulo}

## Hook

## Desenvolvimento

{conteudo}

## CTA

""",
    },
    "youtube": {
        "pasta": "marca-pessoal/youtube",
        "destino": "vault",
        "descricao": "Ideias para vídeos YouTube, títulos, guiões, ângulos, thumbnails",
        "template": """---
tipo: youtube
formato: video/short
estado: ideia
data: {data}
tags: [youtube, conteudo]
---

# {titulo}

## Ângulo / Por que é que vai resultar

## Estrutura do vídeo

{conteudo}

## Thumbnail / Título SEO

""",
    },
}

# =========================================================================
# AGENCY OS — Operacional (→ Supabase)
# =========================================================================

AGENCY_OS = {
    "cliente": {
        "pasta": "agency-os/clientes",
        "destino": "supabase",
        "tabela": "clients",
        "descricao": "Novo cliente, lead, contacto comercial, proposta",
        "template": """---
tipo: cliente
data: {data}
sync: supabase
tags: [cliente, agency-os]
---

# {titulo}

## Empresa / Pessoa

## Contacto

## Contexto / Como chegou

{conteudo}

## Próximo passo

""",
    },
    "projeto": {
        "pasta": "agency-os/projetos",
        "destino": "supabase",
        "tabela": "projects",
        "descricao": "Projeto novo, briefing, entrega, trabalho para cliente",
        "template": """---
tipo: projeto
data: {data}
sync: supabase
tags: [projeto, agency-os]
---

# {titulo}

## Briefing

{conteudo}

## Entregáveis

## Prazo

""",
    },
    "reuniao": {
        "pasta": "agency-os/reunioes",
        "destino": "supabase",
        "tabela": "meetings",
        "descricao": "Reunião com cliente, call, meeting, resumo de call (inclui calls da Maia)",
        "template": """---
tipo: reuniao
data: {data}
sync: supabase
tags: [reuniao, agency-os]
---

# {titulo}

## Participantes

## O que foi discutido

{conteudo}

## Decisões

## Próximos passos

""",
    },
    "financeiro": {
        "pasta": "agency-os/financeiro",
        "destino": "supabase",
        "tabela": "quotes",
        "descricao": "Orçamento, fatura, valor, pagamento, despesa",
        "template": """---
tipo: financeiro
data: {data}
sync: supabase
tags: [financeiro, agency-os]
---

# {titulo}

## Detalhes

{conteudo}

## Valor

## Estado

""",
    },
}

# =========================================================================
# INBOX — fallback
# =========================================================================

INBOX = {
    "inbox": {
        "pasta": "inbox",
        "destino": "vault",
        "descricao": "Tudo o que não encaixa noutra categoria — processar depois",
        "template": """---
tipo: inbox
data: {data}
processado: false
tags: [inbox]
---

# {titulo}

{conteudo}
""",
    },
}

# Todas as categorias juntas (para o agente de classificação)
CATEGORIAS = {**MARCA_PESSOAL, **AGENCY_OS, **INBOX}
