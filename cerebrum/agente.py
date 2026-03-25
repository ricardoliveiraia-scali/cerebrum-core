"""
Lógica principal do Cerebrum — classificar, estruturar, guardar e sincronizar.
"""

import os
import re
import json
import anthropic
from datetime import date
from .categorias import CATEGORIAS

VAULT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vault")

SYSTEM_PROMPT = """És o Cerebrum — o cérebro pessoal de Ricardo.
O teu trabalho é receber notas em bruto (faladas ou escritas) e transformá-las em conteúdo estruturado.

Regras fundamentais:
- Preserva o tom e a forma de falar do Ricardo — natural, direto, português europeu
- Não uses linguagem corporativa ou formal a mais
- Mantém a energia e a personalidade do input original
- Estruturas, mas não engessas — o conteúdo tem de continuar a soar a ele"""

CLASSIFICACAO_PROMPT = """Analisa o seguinte input e classifica-o numa das categorias disponíveis.

O Cerebrum tem dois mundos:
- MARCA PESSOAL (pessoal, empreendedor, ia, instagram, youtube) → vault local
- AGENCY OS (cliente, projeto, reuniao, financeiro) → sync para Supabase

INPUT:
{input}

---

CATEGORIAS DISPONÍVEIS:
{categorias}

---

Responde APENAS com JSON válido neste formato:
{{
  "categoria": "<chave_principal>",
  "titulo": "<título curto que soa natural, máximo 60 chars>",
  "confianca": "<alta/media/baixa>",
  "justificacao": "<1 frase>",
  "multiplas": ["<categoria1>"]
}}

Regras para o campo "multiplas":
- Por defeito tem APENAS 1 categoria — a principal.
- Só usa 2 categorias se o conteúdo for EXPLICITAMENTE sobre os dois temas (ex: uma reflexão pessoal que o Ricardo diz claramente que quer usar no Instagram).
- NUNCA uses mais de 2 categorias.
- NUNCA mistures marca-pessoal com agency-os na mesma nota. São mundos separados.
- agency-os só recebe: clientes, projetos, reunioes, financeiro — apenas quando o input é claramente operacional da agência.
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


def classificar(client: anthropic.Anthropic, texto: str, contexto: str = "") -> dict:
    categorias_desc = "\n".join(
        f'- "{k}": {v["descricao"]}' for k, v in CATEGORIAS.items()
    )
    input_com_contexto = texto
    if contexto:
        input_com_contexto = f"CONTEXTO DA CONVERSA:\n{contexto}\n\nMENSAGEM ATUAL:\n{texto}"

    prompt = CLASSIFICACAO_PROMPT.format(input=input_com_contexto, categorias=categorias_desc)

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
        model="claude-opus-4-6",
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


def guardar(conteudo: str, pasta: str, titulo: str) -> str:
    destino = os.path.join(VAULT_ROOT, pasta)
    os.makedirs(destino, exist_ok=True)

    slug = re.sub(r'[^\w\s-]', '', titulo.lower())
    slug = re.sub(r'[\s]+', '-', slug).strip('-')[:50]
    nome = f"{date.today().isoformat()}-{slug}.md"
    caminho = os.path.join(destino, nome)

    with open(caminho, "w", encoding="utf-8") as f:
        f.write(conteudo)

    return caminho


def processar(texto: str, contexto: str = "", verbose: bool = False) -> list[dict]:
    """
    Processa um texto: classifica, estrutura, guarda e sync.
    Retorna lista de dicts com info sobre cada nota criada.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY não definida.")

    client = anthropic.Anthropic()

    # 0. Atualizar perfil de voz (com texto original bruto)
    try:
        from .perfil_voz import atualizar_perfil
        atualizar_perfil(client, texto)
    except Exception:
        pass

    # 1. Classificar
    classificacao = classificar(client, texto, contexto=contexto)
    titulo = classificacao.get("titulo", f"nota-{date.today().isoformat()}")
    multiplas = classificacao.get("multiplas", [classificacao.get("categoria", "inbox")])

    if verbose:
        print(f"→ Categorias:  {', '.join(multiplas)}")
        print(f"→ Título:      {titulo}")
        print(f"→ Confiança:   {classificacao.get('confianca', '?')}")
        print(f"→ Motivo:      {classificacao.get('justificacao', '')}")
        print()

    resultados = []
    for chave in multiplas:
        categoria = CATEGORIAS.get(chave, CATEGORIAS["inbox"])

        # 2. Estruturar
        conteudo = estruturar(client, texto, categoria, titulo)

        # 3. Guardar no vault (sempre — serve de backup)
        caminho = guardar(conteudo, categoria["pasta"], titulo)

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
        except Exception:
            pass

        # 6. Se for conteúdo (instagram/youtube), sync para Lyra
        if chave in ("instagram", "youtube"):
            try:
                from .supabase_sync import sync_content_piece, _mapear_canal
                channel, sub_agent = _mapear_canal(chave, conteudo)
                sync_content_piece(
                    titulo=titulo,
                    brief=texto,
                    channel=channel,
                    sub_agent=sub_agent,
                    nota_path=caminho,
                    categoria=chave,
                )
                resultado["lyra_synced"] = True
                if verbose:
                    print(f"  ↗ Lyra: {channel}")
            except Exception as e:
                if verbose:
                    print(f"  ⚠ Lyra: {e}")

        resultados.append(resultado)

        if verbose:
            print(f"✓ Guardado: {caminho}")

    return resultados


def processar_com_intencao(texto: str, contexto: str = "", verbose: bool = False) -> dict:
    """
    Entry point com deteção de intenção.
    Retorna: {"tipo": "guardar|pergunta|comando", "resultado": ...}
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY não definida.")

    client = anthropic.Anthropic()

    # 1. Detetar intenção (com contexto de sessão)
    from .intencoes import detetar_intencao
    texto_com_contexto = texto
    if contexto:
        texto_com_contexto = f"{contexto}\n\n[MENSAGEM ATUAL]: {texto}"
    intencao = detetar_intencao(client, texto_com_contexto)
    tipo = intencao.get("intencao", "guardar")

    if verbose:
        print(f"→ Intenção: {tipo} ({intencao.get('detalhe', '')})")

    if tipo == "guardar":
        resultados = processar(texto, contexto=contexto, verbose=verbose)
        return {"tipo": "guardar", "resultado": resultados}

    elif tipo == "pergunta":
        from .consultas import responder_pergunta
        resposta = responder_pergunta(client, texto, contexto=contexto)
        return {"tipo": "pergunta", "resultado": resposta}

    elif tipo == "comando":
        from .comandos import executar_comando
        resposta = executar_comando(client, texto, intencao.get("skill"))
        return {"tipo": "comando", "resultado": resposta}

    # Fallback
    resultados = processar(texto, contexto=contexto, verbose=verbose)
    return {"tipo": "guardar", "resultado": resultados}
