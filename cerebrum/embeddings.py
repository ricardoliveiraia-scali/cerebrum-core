"""
Embeddings — pesquisa semântica via Supabase pgvector.

Usa OpenAI text-embedding-3-small (1536 dimensões) via httpx.
Requer OPENAI_API_KEY no ambiente.

SQL necessário no Supabase:

    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS note_embeddings (
        id BIGSERIAL PRIMARY KEY,
        nota_path TEXT UNIQUE NOT NULL,
        categoria TEXT,
        conteudo TEXT,
        embedding VECTOR(1536),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS note_embeddings_embedding_idx
    ON note_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

    CREATE OR REPLACE FUNCTION match_notes(
        query_embedding VECTOR(1536), match_count INT DEFAULT 5
    )
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
import logging
import httpx
from .supabase_sync import get_supabase_client

log = logging.getLogger(__name__)


def gerar_embedding(texto: str) -> list[float]:
    """Gera embedding via OpenAI text-embedding-3-small."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return []

    try:
        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "text-embedding-3-small",
                "input": texto[:8000],
            },
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()["data"][0]["embedding"]
        log.warning(f"OpenAI embeddings erro {response.status_code}")
    except Exception as e:
        log.warning(f"Erro ao gerar embedding: {e}")

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
    except Exception as e:
        log.warning(f"Erro ao guardar embedding: {e}")


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
    except Exception as e:
        log.warning(f"Erro na pesquisa semântica: {e}")
        return []
