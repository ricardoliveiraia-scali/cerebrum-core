"""
Comandos — executa skills quando o Ricardo pede algo via Telegram.
"""

import os
import re
import json
import anthropic
from datetime import date
from .categorias import CATEGORIAS
from .agente import guardar

SKILLS_DISPONIVEIS = {
    "carrossel": {
        "descricao": "Gerar carrossel para Instagram",
        "estado": "ativo",
    },
    "guiao": {
        "descricao": "Gerar guião para vídeo YouTube",
        "estado": "ativo",
    },
    "proposta": {
        "descricao": "Gerar proposta/orçamento para cliente",
        "estado": "ativo",
    },
    "resumo": {
        "descricao": "Gerar resumo semanal/mensal",
        "estado": "ativo",
    },
}

# ---------------------------------------------------------------------------
# Prompts das skills
# ---------------------------------------------------------------------------

CARROSSEL_PROMPT = """Cria um carrossel de Instagram com base neste input do Ricardo.

INPUT: {input}

{contexto_notas}

---

Formato do carrossel (8-10 slides):

SLIDE 1 (CAPA):
🔥 Hook forte — uma frase que pare o scroll

SLIDES 2-8 (CONTEÚDO):
Cada slide com:
- Título curto (máx 8 palavras)
- 2-3 bullets ou frase impactante
- Mantém o tom do Ricardo — direto, sem filtros

SLIDE FINAL (CTA):
- Call to action claro (seguir, guardar, partilhar)

---

Responde em Markdown. Separa cada slide com "---".
Tom: direto, informal, português europeu, sem corporativês.
{perfil_voz}
"""

GUIAO_PROMPT = """Cria um guião de vídeo YouTube com base neste input.

INPUT: {input}

{contexto_notas}

---

Formato:
## Título (SEO-friendly, máx 60 chars)
## Thumbnail — ideia visual

## HOOK (0:00-0:30)
O que dizer nos primeiros 30 segundos para prender

## INTRO (0:30-1:00)
Contexto rápido

## DESENVOLVIMENTO
- Ponto 1
- Ponto 2
- Ponto 3
(com transições sugeridas)

## CONCLUSÃO + CTA
- Resumo em 1 frase
- CTA (subscrever, comentar, etc)

---

Tom: conversacional, como se estivesse a falar com um amigo. Português europeu.
{perfil_voz}
"""

PROPOSTA_PROMPT = """Gera uma proposta/orçamento profissional com base neste input.

INPUT: {input}

{contexto_notas}

---

Formato Markdown:
# Proposta — [Nome do Projeto]

**Cliente:** [extrair do input]
**Data:** {data}
**Validade:** 15 dias

## Âmbito do Projeto
[O que vai ser feito]

## Entregáveis
- Item 1
- Item 2
- Item 3

## Investimento
| Item | Valor |
|------|-------|
| ... | ... € |
| **Total** | **... €** |

## Condições
- 50% no arranque, 50% na entrega
- Prazo estimado: X semanas

## Próximos Passos
1. Aprovação da proposta
2. Kick-off meeting
3. Início do projeto

---

Tom: profissional mas acessível. Português europeu.
"""

RESUMO_SEMANAL_PROMPT = """Gera um resumo baseado nos dados disponíveis.

INPUT DO RICARDO: {input}

NOTAS RECENTES DO VAULT:
{notas}

DADOS DO SUPABASE:
{dados_supabase}

---

Formato:
📊 *Resumo*

Organiza por secções:
- **Marca Pessoal** — conteúdo, ideias, reflexões
- **Agency OS** — clientes, projetos, reuniões, financeiro
- **Pendentes** — o que ficou por resolver

Sê conciso, direto, português europeu. Máximo 500 palavras.
"""


def executar_comando(client: anthropic.Anthropic, texto: str, skill_detetada: str = None) -> str:
    """Executa um comando/skill."""

    skill = None
    if skill_detetada:
        for nome, info in SKILLS_DISPONIVEIS.items():
            if nome in skill_detetada.lower():
                skill = nome
                break

    if not skill:
        # Tenta detetar pelo texto
        texto_lower = texto.lower()
        for nome in SKILLS_DISPONIVEIS:
            if nome in texto_lower:
                skill = nome
                break

    if not skill:
        lista = "\n".join(
            f"• `{nome}` — {info['descricao']}"
            for nome, info in SKILLS_DISPONIVEIS.items()
        )
        return f"Não percebi o comando. Skills disponíveis:\n\n{lista}"

    # Executar skill
    if skill == "carrossel":
        return _skill_carrossel(client, texto)
    elif skill == "guiao":
        return _skill_guiao(client, texto)
    elif skill == "proposta":
        return _skill_proposta(client, texto)
    elif skill == "resumo":
        return _skill_resumo(client, texto)

    return f"Skill `{skill}` não implementada."


def _obter_perfil_voz() -> str:
    try:
        from .perfil_voz import obter_prompt_tom
        return obter_prompt_tom()
    except Exception:
        return ""


def _obter_contexto_relevante(texto: str, limite: int = 5) -> str:
    """Pesquisa notas relacionadas para enriquecer a geração de conteúdo."""
    notas = []

    # 1. Pesquisa semântica
    try:
        from .embeddings import pesquisar_semantico
        resultados = pesquisar_semantico(texto, limite=limite)
        if resultados:
            for r in resultados:
                categoria = r.get("categoria", "?")
                conteudo = r.get("conteudo", "")[:400]
                notas.append(f"[{categoria}] {conteudo}")
    except Exception:
        pass

    # 2. Fallback: pesquisa por texto no vault
    if not notas:
        try:
            from .leitor import buscar
            palavras = [p for p in texto.split() if len(p) > 3]
            for palavra in palavras[:3]:
                resultados = buscar(texto=palavra, limite=limite)
                if resultados:
                    for r in resultados:
                        categoria = r.get("categoria", "?")
                        conteudo = r.get("conteudo", "")[:400]
                        notas.append(f"[{categoria}] {conteudo}")
                    break
        except Exception:
            pass

    if not notas:
        return ""

    notas_unicas = list(dict.fromkeys(notas))[:limite]
    return "\n---\n".join(notas_unicas)


def _formatar_contexto(contexto_raw: str) -> str:
    """Formata contexto de notas para injeção no prompt."""
    if not contexto_raw:
        return ""
    return f"""NOTAS RELACIONADAS DO VAULT DO RICARDO (usa como inspiração e fonte, não copies literalmente):
{contexto_raw}"""


def _skill_carrossel(client: anthropic.Anthropic, texto: str) -> str:
    perfil = _obter_perfil_voz()
    contexto = _formatar_contexto(_obter_contexto_relevante(texto))
    resposta = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": CARROSSEL_PROMPT.format(
            input=texto, perfil_voz=perfil, contexto_notas=contexto
        )}],
    )
    conteudo = resposta.content[0].text.strip()

    # Guardar na pasta instagram
    caminho = guardar(conteudo, "marca-pessoal/instagram", f"carrossel-{date.today().isoformat()}")

    # Sync para Lyra (content_pieces)
    lyra_msg = ""
    try:
        from .supabase_sync import sync_content_piece
        slides = conteudo.count("---") + 1
        sync_content_piece(
            titulo=f"Carrossel — {date.today().isoformat()}",
            brief=texto,
            channel="carousel",
            sub_agent="carrosseis",
            nota_path=caminho,
            categoria="instagram",
            copy_preview=conteudo,
            slides=slides,
        )
        lyra_msg = "\n↗ Enviado para Lyra (para revisão)"
    except Exception:
        pass

    return f"🎠 Carrossel gerado!\n\n{conteudo}\n\n📄 Guardado em `{os.path.basename(caminho)}`{lyra_msg}"


def _skill_guiao(client: anthropic.Anthropic, texto: str) -> str:
    perfil = _obter_perfil_voz()
    contexto = _formatar_contexto(_obter_contexto_relevante(texto))
    resposta = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": GUIAO_PROMPT.format(
            input=texto, perfil_voz=perfil, contexto_notas=contexto
        )}],
    )
    conteudo = resposta.content[0].text.strip()

    caminho = guardar(conteudo, "marca-pessoal/youtube", f"guiao-{date.today().isoformat()}")

    # Sync para Lyra (content_pieces)
    lyra_msg = ""
    try:
        from .supabase_sync import sync_content_piece
        sync_content_piece(
            titulo=f"Guião — {date.today().isoformat()}",
            brief=texto,
            channel="reel",
            sub_agent="reels",
            nota_path=caminho,
            categoria="youtube",
            copy_preview=conteudo,
        )
        lyra_msg = "\n↗ Enviado para Lyra (para revisão)"
    except Exception:
        pass

    return f"🎬 Guião gerado!\n\n{conteudo}\n\n📄 Guardado em `{os.path.basename(caminho)}`{lyra_msg}"


def _skill_proposta(client: anthropic.Anthropic, texto: str) -> str:
    contexto = _formatar_contexto(_obter_contexto_relevante(texto))
    resposta = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": PROPOSTA_PROMPT.format(
            input=texto, data=date.today().isoformat(), contexto_notas=contexto
        )}],
    )
    conteudo = resposta.content[0].text.strip()

    caminho = guardar(conteudo, "agency-os/financeiro", f"proposta-{date.today().isoformat()}")

    # Sync para Supabase
    sync_msg = ""
    try:
        from .supabase_sync import sync_para_supabase
        sync_para_supabase(client, conteudo, "quotes")
        sync_msg = "\n↗ Synced para Supabase (quotes)"
    except Exception:
        sync_msg = "\n⚠ Supabase offline"

    return f"📋 Proposta gerada!\n\n{conteudo}\n\n📄 Guardado em `{os.path.basename(caminho)}`{sync_msg}"


def _skill_resumo(client: anthropic.Anthropic, texto: str) -> str:
    # Buscar notas recentes
    from .leitor import listar, ler
    notas_recentes = listar(limite=20)
    conteudos = []
    for n in notas_recentes:
        conteudos.append(f"[{n['categoria']}] {ler(n['caminho'])[:300]}")

    # Buscar dados do Supabase
    dados_supabase = ""
    try:
        from .supabase_sync import get_supabase_client
        sb = get_supabase_client()
        for tabela in ["clients", "projects", "meetings", "quotes"]:
            try:
                resultado = sb.table(tabela).select("*").limit(20).execute()
                if resultado.data:
                    dados_supabase += f"\n{tabela}: {json.dumps(resultado.data, ensure_ascii=False)[:500]}\n"
            except Exception:
                pass
    except Exception:
        dados_supabase = "Supabase indisponível"

    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": RESUMO_SEMANAL_PROMPT.format(
            input=texto,
            notas="\n---\n".join(conteudos) if conteudos else "Sem notas",
            dados_supabase=dados_supabase or "Sem dados",
        )}],
    )

    return resposta.content[0].text.strip()
