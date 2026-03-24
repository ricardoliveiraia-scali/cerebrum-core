"""
Lógica principal do Cerebrum — classificar, estruturar e guardar notas.
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
  "categoria": "<chave_da_categoria>",
  "titulo": "<título curto que soa natural, máximo 60 chars>",
  "confianca": "<alta/media/baixa>",
  "justificacao": "<1 frase>",
  "multiplas": ["<categoria1>", "<categoria2>"]
}}

O campo "multiplas" lista todas as categorias relevantes (pode ser só uma).
Uma nota pode pertencer a ambos os mundos (ex: uma ideia de negócio que também serve para Instagram).
Em caso de dúvida usa "inbox".
"""

ESTRUTURACAO_PROMPT = """Preenche o template com base no input. Mantém o tom e a forma de falar do Ricardo.

INPUT ORIGINAL:
{input}

TEMPLATE:
{template}

TÍTULO: {titulo}
DATA: {data}

---

Regras:
- Preserva o vocabulário e expressões do input
- Preenche os campos com o que foi dito — não inventes
- Para campos sem info escreve "A definir"
- YAML frontmatter válido
- Responde APENAS com o Markdown final, sem explicações
"""


def classificar(client: anthropic.Anthropic, texto: str) -> dict:
    categorias_desc = "\n".join(
        f'- "{k}": {v["descricao"]}' for k, v in CATEGORIAS.items()
    )
    prompt = CLASSIFICACAO_PROMPT.format(input=texto, categorias=categorias_desc)

    resposta = client.messages.create(
        model="claude-opus-4-6",
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

    prompt = ESTRUTURACAO_PROMPT.format(
        input=texto,
        template=template,
        titulo=titulo,
        data=date.today().isoformat(),
    )

    resultado = []
    with client.messages.stream(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            resultado.append(text)

    return "".join(resultado)


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


def processar(texto: str, verbose: bool = False) -> list[str]:
    """
    Processa um texto: classifica, estrutura e guarda.
    Retorna lista de caminhos dos ficheiros criados (pode ser mais de um se múltiplas categorias).
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise EnvironmentError("ANTHROPIC_API_KEY não definida.")

    client = anthropic.Anthropic()

    # 1. Classificar
    classificacao = classificar(client, texto)
    titulo = classificacao.get("titulo", f"nota-{date.today().isoformat()}")
    multiplas = classificacao.get("multiplas", [classificacao.get("categoria", "inbox")])

    if verbose:
        print(f"→ Categorias:  {', '.join(multiplas)}")
        print(f"→ Título:      {titulo}")
        print(f"→ Confiança:   {classificacao.get('confianca', '?')}")
        print(f"→ Motivo:      {classificacao.get('justificacao', '')}")
        print()

    caminhos = []
    for chave in multiplas:
        categoria = CATEGORIAS.get(chave, CATEGORIAS["inbox"])

        # 2. Estruturar
        conteudo = estruturar(client, texto, categoria, titulo)

        # 3. Guardar
        caminho = guardar(conteudo, categoria["pasta"], titulo)
        caminhos.append(caminho)

        if verbose:
            print(f"✓ Guardado: {caminho}")

    return caminhos
