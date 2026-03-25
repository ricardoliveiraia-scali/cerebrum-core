"""
Supabase Sync — envia dados estruturados para o Agency OS (Supabase).

Schema do Supabase (valores válidos):
- clients.status: active, inactive, prospect, churned (default: active)
- projects.status: active, completed, on_hold, cancelled, draft (default: active)
- meetings.type: internal, client, discovery, sales, other (default: internal)
- quotes: precisa de client_id (NOT NULL)
- clients: precisa de company_id (NOT NULL) — criamos company primeiro
"""

import os
import re
import json
import logging
import anthropic
from datetime import datetime
from supabase import create_client, Client

log = logging.getLogger(__name__)

TABLE_SCHEMAS = {
    "clients": {
        "prompt": """Extrai os seguintes campos (JSON):
- company_name: nome da empresa ou pessoa (obrigatório)
- company_email: email se mencionado, senão null
- company_phone: telefone se mencionado, senão null
- company_industry: setor/indústria se mencionado, senão null
- status: "prospect" ou "active" (default: "prospect")
- monthly_value: valor mensal numérico se mencionado, senão null
- notes: resumo curto do contexto/como chegou""",
    },
    "projects": {
        "prompt": """Extrai os seguintes campos (JSON):
- name: nome do projeto (obrigatório)
- status: "draft" ou "active" (default: "draft")
- type: tipo de projeto (texto livre, ex: "website", "branding")
- description: briefing resumido
- budget: valor numérico se mencionado, senão null
- currency: "EUR" (default)""",
    },
    "meetings": {
        "prompt": """Extrai os seguintes campos (JSON):
- title: título da reunião (obrigatório)
- type: "client" | "discovery" | "sales" | "internal" | "other" (default: "client")
- summary: resumo do que foi discutido
- next_steps: próximos passos""",
    },
    "quotes": {
        "prompt": """Extrai os seguintes campos (JSON):
- company_name: nome da empresa/cliente associado (obrigatório)
- subtotal: valor sem IVA numérico se mencionado, senão null
- tax_rate: taxa IVA (default: 23)
- total: valor total numérico se mencionado, senão null
- currency: "EUR" (default)
- notes: detalhes da proposta""",
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
    return {k: v for k, v in campos.items() if v is not None}


def _get_or_create_company(sb: Client, name: str, extra: dict = None) -> str:
    """Procura ou cria uma empresa, retorna o ID."""
    existing = sb.table("companies").select("id").eq("name", name).limit(1).execute()
    if existing.data:
        log.info(f"Empresa existente: {name}")
        return existing.data[0]["id"]

    data = {"name": name}
    if extra:
        data.update(extra)
    result = sb.table("companies").insert(data).execute()
    log.info(f"Empresa criada: {name}")
    return result.data[0]["id"]


def _get_client_id_by_company(sb: Client, company_id: str) -> str:
    """Procura client_id pela company_id."""
    existing = sb.table("clients").select("id").eq("company_id", company_id).limit(1).execute()
    if existing.data:
        return existing.data[0]["id"]
    # Criar client minimal
    result = sb.table("clients").insert({"company_id": company_id, "status": "prospect"}).execute()
    return result.data[0]["id"]


def sync_para_supabase(client_anthropic: anthropic.Anthropic, conteudo_md: str, tabela: str) -> dict:
    """Extrai campos e insere no Supabase. Retorna os dados inseridos."""
    campos = extrair_campos(client_anthropic, conteudo_md, tabela)

    if not campos:
        log.warning(f"Sem campos extraídos para {tabela}")
        return {}

    log.info(f"Campos extraídos para {tabela}: {json.dumps(campos, ensure_ascii=False)}")

    sb = get_supabase_client()
    agora = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")

    try:
        if tabela == "clients":
            company_name = campos.pop("company_name", "Sem nome")
            company_extra = {}
            for k in ["company_email", "company_phone", "company_industry"]:
                v = campos.pop(k, None)
                if v:
                    company_extra[k.replace("company_", "")] = v

            company_id = _get_or_create_company(sb, company_name, company_extra)

            client_data = {"company_id": company_id}
            for k in ["status", "monthly_value", "currency", "notes"]:
                if k in campos:
                    client_data[k] = campos[k]

            result = sb.table("clients").insert(client_data).execute()

        elif tabela == "meetings":
            meeting_data = {
                "title": campos.get("title", "Reunião sem título"),
                "date": campos.get("date", agora),
                "type": campos.get("type", "client"),
            }
            for k in ["summary", "next_steps"]:
                if k in campos:
                    meeting_data[k] = campos[k]

            result = sb.table("meetings").insert(meeting_data).execute()

        elif tabela == "projects":
            project_data = {
                "name": campos.get("name", "Projeto sem nome"),
            }
            for k in ["status", "type", "description", "budget", "currency"]:
                if k in campos:
                    project_data[k] = campos[k]

            result = sb.table("projects").insert(project_data).execute()

        elif tabela == "quotes":
            company_name = campos.pop("company_name", None)
            if company_name:
                company_id = _get_or_create_company(sb, company_name)
                client_id = _get_client_id_by_company(sb, company_id)
            else:
                log.warning("Quote sem company_name — ignorado")
                return {}

            # Gerar número da proposta (QT-YYYYMMDD-XXX)
            count = sb.table("quotes").select("id", count="exact").execute()
            num = (count.count or 0) + 1
            numero = f"QT-{datetime.utcnow().strftime('%Y%m%d')}-{num:03d}"

            quote_data = {"client_id": client_id, "number": numero}
            for k in ["subtotal", "tax_rate", "total", "currency", "notes"]:
                if k in campos:
                    quote_data[k] = campos[k]

            result = sb.table("quotes").insert(quote_data).execute()

        else:
            log.warning(f"Tabela {tabela} não suportada")
            return {}

        log.info(f"Inserido em {tabela} com sucesso")
        return result.data[0] if result.data else {}

    except Exception as e:
        log.error(f"Erro ao inserir em {tabela}: {e}")
        return {}


# ---------------------------------------------------------------------------
# Lyra — content_pieces
# ---------------------------------------------------------------------------

def _mapear_canal(categoria: str, conteudo: str) -> tuple[str, str | None]:
    """Mapeia categoria Cerebrum → canal/sub-agente Lyra."""
    conteudo_lower = conteudo.lower()

    if categoria == "youtube":
        return "reel", "reels"

    # instagram — detectar formato pelo conteúdo
    if "reel" in conteudo_lower or "formato: reel" in conteudo_lower:
        return "reel", "reels"

    return "carousel", "carrosseis"


def sync_content_piece(
    titulo: str,
    brief: str,
    channel: str,
    sub_agent: str | None,
    nota_path: str,
    categoria: str,
    copy_preview: str | None = None,
    slides: int | None = None,
) -> dict:
    """Insere uma peça de conteúdo na fila da Lyra (content_pieces)."""
    sb = get_supabase_client()

    status = "review" if copy_preview else "producing"

    data = {
        "title": titulo[:200],
        "channel": channel,
        "status": status,
        "sub_agent": sub_agent,
        "brief": brief[:5000] if brief else None,
        "copy_preview": copy_preview,
        "slides": slides,
        "source": "cerebrum",
        "cerebrum_nota_path": nota_path,
        "cerebrum_categoria": categoria,
    }

    try:
        result = sb.table("content_pieces").insert(data).execute()
        log.info(f"Content piece criada: {titulo} ({channel}, {status})")
        return result.data[0] if result.data else {}
    except Exception as e:
        log.error(f"Erro ao criar content piece: {e}")
        return {}
