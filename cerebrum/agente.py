from __future__ import annotations
"""
Lógica principal do Cerebrum — classificar, estruturar, guardar e sincronizar.
"""

import os
import re
import json
import logging
import anthropic
from datetime import date
from .categorias import CATEGORIAS

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """És o Cerebrum — o cérebro pessoal de Ricardo.
O teu trabalho é receber notas em bruto (faladas ou escritas) e transformá-las em conteúdo estruturado.

Regras fundamentais:
- Preserva o tom e a forma de falar do Ricardo — natural, direto, português europeu
- Não uses linguagem corporativa ou formal a mais
- Mantém a energia e a personalidade do input original
- Estruturas, mas não engessas — o conteúdo tem de continuar a soar a ele"""

TRIAGEM_PROMPT = """Analisa a mensagem do Ricardo e faz a triagem completa num só passo.

MENSAGEM:
{input}

CATEGORIAS DISPONÍVEIS:
{categorias}

---

Responde APENAS com JSON válido:
{{
  "intencao": "guardar|pergunta|comando",
  "categoria": "<chave da categoria, só se intencao=guardar>",
  "titulo": "<título curto natural, máximo 60 chars, só se intencao=guardar>",
  "skill": "<nome da skill se intencao=comando, senão null>",
  "confianca": "<alta/media/baixa>",
  "justificacao": "<1 frase>"
}}

Regras de intenção:
- "guardar": nota, ideia, reflexão, resumo, briefing, algo que aconteceu — algo para GUARDAR
- "pergunta": quer SABER algo ("quanto faturei?", "quem é o cliente X?")
- "comando": quer FAZER algo ("cria carrossel", "gera proposta")

Regras de categoria (só para intencao=guardar):
- Escolhe APENAS 1 categoria — a mais relevante.
- NUNCA mistures marca-pessoal com agency-os. São mundos separados.
- agency-os só recebe: clientes, projetos, reunioes, financeiro — apenas quando é claramente operacional da agência.
- marca-pessoal recebe tudo o resto: pensamentos, ideias de conteúdo, IA, jornada de empreendedor.
- Em caso de dúvida usa "inbox".
"""

ESTRUTURACAO_PROMPT = """Preenche o template com base no input. Mantém o tom e a forma de falar do Ricardo.

INPUT ORIGINAL:
{input}

TEMPLATE:
{template}

TÍTULO: {titulo}
DATA: {data}

{perfil_voz}

---

Regras:
- Preserva o vocabulário e expressões do input
- Preenche os campos com o que foi dito — não inventes
- Para campos sem info escreve "A definir"
- YAML frontmatter válido
- Responde APENAS com o Markdown final, sem explicações
"""


def triar(client: anthropic.Anthropic, texto: str, contexto: str = "") -> dict:
    """Triagem num só call: intenção + categoria + título."""
    categorias_desc = "\n".join(
        f'- "{k}": {v["descricao"]}' for k, v in CATEGORIAS.items()
    )
    input_com_contexto = texto
    if contexto:
        input_com_contexto = f"CONTEXTO DA CONVERSA:\n{contexto}\n\nMENSAGEM ATUAL:\n{texto}"

    prompt = TRIAGEM_PROMPT.format(input=input_com_contexto, categorias=categorias_desc)

    resposta = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = resposta.content[0].text.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        raise ValueError(f"Resposta inválida: {raw}")

    return json.loads(match.group())


def estruturar(client: anthropic.Anthropic, texto: str, categoria: dict, titulo: str) -> str:
    template = categoria["template"].format(
        data=date.today().isoformat(),
        titulo=titulo,
        conteudo=texto,
    )

    # Injeta perfil de voz para categorias de conteúdo
    perfil_voz = ""
    pasta = categoria.get("pasta", "")
    if "instagram" in pasta or "youtube" in pasta:
        try:
            from .perfil_voz import obter_prompt_tom
            perfil_voz = obter_prompt_tom()
        except Exception:
            pass

    prompt = ESTRUTURACAO_PROMPT.format(
        input=texto,
        template=template,
        titulo=titulo,
        data=date.today().isoformat(),
        perfil_voz=perfil_voz,
    )

    system = SYSTEM_PROMPT
    if perfil_voz:
        system = SYSTEM_PROMPT + "\n\n" + perfil_voz

    resultado = []
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            resultado.append(text)

    conteudo = "".join(resultado)
    # Remove blocos de código se o modelo os incluir
    conteudo = re.sub(r'^```(?:markdown)?\n?', '', conteudo)
    conteudo = re.sub(r'\n?```$', '', conteudo).strip()
    return conteudo


def guardar(conteudo: str, pasta: str, titulo: str, categoria: str = "inbox") -> str:
    slug = re.sub(r'[^\w\s-]', '', titulo.lower())
    slug = re.sub(r'[\s]+', '-', slug).strip('-')[:50]
    caminho = f"{pasta}/{date.today().isoformat()}-{slug}.md"

    try:
        from .supabase_sync import get_supabase_client
        sb = get_supabase_client()
        sb.table("vault_notes").insert({
            "path": caminho,
            "categoria": categoria,
            "titulo": titulo,
            "conteudo": conteudo,
        }).execute()
    except Exception as e:
        log.warning(f"vault_notes insert falhou: {e}")

    return caminho


def _guardar_nota(client: anthropic.Anthropic, texto: str, triagem: dict,
                   contexto: str = "", verbose: bool = False) -> list[dict]:
    """Estrutura, guarda e sincroniza uma nota já triada."""

    # 0. Atualizar perfil de voz (só marca pessoal — não faz sentido para agency-os)
    from .categorias import MARCA_PESSOAL
    if chave in MARCA_PESSOAL:
        try:
            from .perfil_voz import atualizar_perfil
            atualizar_perfil(client, texto)
        except Exception as e:
            log.warning(f"perfil_voz: {e}")

    titulo = triagem.get("titulo", f"nota-{date.today().isoformat()}")
    chave = triagem.get("categoria", "inbox")
    categoria = CATEGORIAS.get(chave, CATEGORIAS["inbox"])

    if verbose:
        print(f"→ Categoria:   {chave}")
        print(f"→ Título:      {titulo}")
        print(f"→ Confiança:   {triagem.get('confianca', '?')}")
        print(f"→ Motivo:      {triagem.get('justificacao', '')}")
        print()

    # 1. Verificar duplicado (mesmo título + mesma data)
    try:
        from .supabase_sync import get_supabase_client
        sb = get_supabase_client()
        hoje = date.today().isoformat()
        existente = sb.table("vault_notes").select("id").eq("titulo", titulo).gte(
            "created_at", f"{hoje}T00:00:00"
        ).limit(1).execute()
        if existente.data:
            if verbose:
                print(f"⚠ Duplicado: já existe nota '{titulo}' de hoje")
            return [{"caminho": "", "categoria": chave, "destino": "duplicado", "supabase_synced": False}]
    except Exception as e:
        log.warning(f"verificação de duplicado: {e}")

    # 2. Estruturar
    conteudo = estruturar(client, texto, categoria, titulo)

    # 3. Guardar no vault + Supabase
    caminho = guardar(conteudo, categoria["pasta"], titulo, categoria=chave)

    resultado = {
        "caminho": caminho,
        "categoria": chave,
        "destino": categoria.get("destino", "vault"),
        "supabase_synced": False,
    }

    # 4. Sync para Supabase (se for agency-os)
    if categoria.get("destino") == "supabase" and categoria.get("tabela"):
        try:
            from .supabase_sync import sync_para_supabase
            sync_para_supabase(client, conteudo, categoria["tabela"])
            resultado["supabase_synced"] = True
            if verbose:
                print(f"  ↗ Synced: {categoria['tabela']}")
        except Exception as e:
            if verbose:
                print(f"  ⚠ Supabase: {e}")

    # 5. Guardar embedding para pesquisa semântica
    try:
        from .embeddings import guardar_embedding
        guardar_embedding(caminho, chave, conteudo)
    except Exception as e:
        log.warning(f"embeddings: {e}")

    # 6. Enviar ideia para Lyra (todas as notas — curadoria é do Ricardo)
    try:
        from .supabase_sync import sync_content_piece
        sync_content_piece(
            titulo=titulo,
            brief=texto,
            nota_path=caminho,
            categoria=chave,
        )
        resultado["lyra_synced"] = True
        if verbose:
            print(f"  ↗ Lyra: ideia criada")
    except Exception as e:
        log.warning(f"Lyra sync: {e}")
        if verbose:
            print(f"  ⚠ Lyra: {e}")

    if verbose:
        print(f"✓ Guardado: {caminho}")

    return [resultado]


def processar_com_intencao(texto: str, contexto: str = "", verbose: bool = False) -> dict:
    """
    Entry point principal — triagem + execução num fluxo só.
    Retorna: {"tipo": "guardar|pergunta|comando", "resultado": ...}
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY não definida.")

    client = anthropic.Anthropic()

    # 1. Triagem: intenção + categoria num só call
    triagem = triar(client, texto, contexto=contexto)
    tipo = triagem.get("intencao", "guardar")

    if verbose:
        print(f"→ Intenção: {tipo} ({triagem.get('justificacao', '')})")

    if tipo == "guardar":
        # Já temos categoria e título da triagem — saltar classificação
        resultados = _guardar_nota(client, texto, triagem, contexto=contexto, verbose=verbose)
        return {"tipo": "guardar", "resultado": resultados}

    elif tipo == "pergunta":
        from .consultas import responder_pergunta
        resposta = responder_pergunta(client, texto, contexto=contexto)
        return {"tipo": "pergunta", "resultado": resposta}

    elif tipo == "comando":
        from .comandos import executar_comando
        resposta = executar_comando(client, texto, triagem.get("skill"))
        return {"tipo": "comando", "resultado": resposta}

    # Fallback
    resultados = _guardar_nota(client, texto, triagem, contexto=contexto, verbose=verbose)
    return {"tipo": "guardar", "resultado": resultados}
