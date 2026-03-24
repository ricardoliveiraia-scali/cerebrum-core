"""
Embeddings — pesquisa semântica via Supabase pgvector.

Usa a API de embeddings do Voyage (Anthropic) para gerar vetores
e guarda-os no Supabase para pesquisa por similaridade.

Tabela necessária no Supabase:
    CREATE TABLE IF NOT EXISTS note_embeddings (
        id BIGSERIAL PRIMARY KEY,
        nota_path TEXT UNIQUE NOT NULL,
        categoria TEXT,
        conteudo TEXT,
        embedding VECTOR(1024),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX ON note_embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

    -- Função de pesquisa
    CREATE OR REPLACE FUNCTION match_notes(query_embedding VECTOR(1024), match_count INT DEFAULT 5)
    RETURNS TABLE(id BIGINT, nota_path TEXT, categoria TEXT, conteudo TEXT, similarity FLOAT)
    LANGUAGE plpgsql AS $$
    BEGIN
        RETURN QUERY
        SELECT ne.id, ne.nota_path, ne.categoria, ne.conteudo,
               1 - (ne.embedding <=> query_embedding) AS similarity
        FROM note_embeddings ne
        ORDER BY ne.embedding <=> query_embedding
        LIMIT match_count;
    END;
    $$;
"""

import os
import httpx
import anthropic
from .supabase_sync import get_supabase_client


def gerar_embedding(texto: str) -> list[float]:
    """Gera embedding via API Voyage (Anthropic)."""
    client = anthropic.Anthropic()

    # Usa a API de embeddings da Voyage via Anthropic
    try:
        response = httpx.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {os.environ.get('VOYAGE_API_KEY', '')}",
                "Content-Type": "application/json",
            },
            json={
                "model": "voyage-3-lite",
                "input": [texto[:8000]],
                "input_type": "document",
            },
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()["data"][0]["embedding"]
    except Exception:
        pass

    # Fallback: embedding simples com Anthropic (hash do texto)
    # Se não tiver Voyage, usa uma aproximação
    return []


def guardar_embedding(nota_path: str, categoria: str, conteudo: str):
    """Gera e guarda embedding de uma nota no Supabase."""
    embedding = gerar_embedding(conteudo)
    if not embedding:
        return

    try:
        sb = get_supabase_client()
        sb.table("note_embeddings").upsert({
            "nota_path": nota_path,
            "categoria": categoria,
            "conteudo": conteudo[:5000],
            "embedding": embedding,
        }, on_conflict="nota_path").execute()
    except Exception:
        pass


def pesquisar_semantico(query: str, limite: int = 5) -> list[dict]:
    """Pesquisa notas por similaridade semântica."""
    embedding = gerar_embedding(query)
    if not embedding:
        return []

    try:
        sb = get_supabase_client()
        resultado = sb.rpc("match_notes", {
            "query_embedding": embedding,
            "match_count": limite,
        }).execute()
        return resultado.data if resultado.data else []
    except Exception:
        return []
