#!/usr/bin/env python3
"""
Cerebrum — Bot Telegram

Fluxo:
    Áudio / Voz → Whisper transcreve → Cerebrum classifica → guarda no vault

Uso:
    export ANTHROPIC_API_KEY="sk-ant-..."
    export TELEGRAM_TOKEN="..."
    python telegram_bot.py
"""

import os
import sys
import asyncio
import logging
import tempfile
import httpx
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from cerebrum.agente import processar_com_intencao

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# IDs autorizados (separados por vírgula). Se vazio, aceita todos.
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "")
ALLOWED_USER_IDS = {int(uid.strip()) for uid in ALLOWED_USERS.split(",") if uid.strip()}

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# Cache de sessão em memória (carregada do Supabase no primeiro acesso)
SESSAO: dict[int, list[dict]] = {}

# ---------------------------------------------------------------------------
# Transcrição via API Whisper (OpenAI) — leve, sem PyTorch
# ---------------------------------------------------------------------------

async def _transcrever_ficheiro(caminho: str, api_key: str) -> str:
    """Transcreve um único ficheiro via Whisper API."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=180, write=60, pool=10)) as client:
        with open(caminho, "rb") as f:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={"model": "whisper-1", "language": "pt"},
                files={"file": (Path(caminho).name, f, "audio/ogg")},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Whisper API erro {resp.status_code}: {resp.text}")
        return resp.json().get("text", "").strip()


def _partir_audio(caminho: str, duracao_max: int = 120) -> list[str]:
    """Parte áudio em chunks usando ffmpeg. Retorna lista de caminhos temporários."""
    import subprocess
    chunks = []
    pasta = os.path.dirname(caminho)
    ext = Path(caminho).suffix

    # Obter duração total
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", caminho],
        capture_output=True, text=True
    )
    try:
        duracao_total = float(result.stdout.strip())
    except ValueError:
        log.warning("ffprobe não conseguiu ler duração — a usar ficheiro original")
        return [caminho]  # fallback: retornar original

    if duracao_total <= duracao_max:
        return [caminho]  # não precisa de partir

    # Partir em segmentos
    n = 0
    inicio = 0
    while inicio < duracao_total:
        saida = os.path.join(pasta, f"chunk_{n}{ext}")
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", caminho, "-ss", str(inicio),
             "-t", str(duracao_max), "-c", "copy", saida],
            capture_output=True
        )
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg falhou no chunk {n}: {r.stderr.decode()[:200]}")
        if not os.path.exists(saida) or os.path.getsize(saida) == 0:
            raise RuntimeError(f"ffmpeg produziu chunk vazio: {saida}")
        chunks.append(saida)
        inicio += duracao_max
        n += 1

    return chunks


async def transcrever_audio_api(caminho: str) -> str:
    """Transcreve áudio via Whisper API. Parte automaticamente áudios longos."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não definida — transcrição por API indisponível.")

    chunks = _partir_audio(caminho, duracao_max=120)

    async def transcrever_e_limpar(chunk: str) -> str:
        try:
            return await _transcrever_ficheiro(chunk, api_key)
        finally:
            if chunk != caminho and os.path.exists(chunk):
                os.unlink(chunk)

    import asyncio
    transcricoes = await asyncio.gather(*[transcrever_e_limpar(c) for c in chunks])
    return " ".join(transcricoes).strip()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def autorizado(update: Update) -> bool:
    """Verifica se o utilizador está autorizado."""
    if not ALLOWED_USER_IDS:
        return True  # Sem restrição configurada
    return update.effective_user.id in ALLOWED_USER_IDS


def _get_supabase():
    """Retorna cliente Supabase (lazy)."""
    from cerebrum.supabase_sync import get_supabase_client
    return get_supabase_client()


def guardar_sessao(chat_id: int, role: str, texto: str):
    """Guarda mensagem na sessão (memória + Supabase)."""
    if chat_id not in SESSAO:
        SESSAO[chat_id] = []
    SESSAO[chat_id].append({"role": role, "texto": texto})
    SESSAO[chat_id] = SESSAO[chat_id][-20:]

    try:
        sb = _get_supabase()
        sb.table("bot_sessions").insert({
            "chat_id": chat_id, "role": role, "texto": texto[:2000],
        }).execute()
    except Exception as e:
        log.warning(f"bot_sessions insert: {e}")


def obter_contexto_sessao(chat_id: int) -> str:
    """Devolve as últimas mensagens como contexto (Supabase se cache vazio)."""
    if chat_id not in SESSAO:
        try:
            sb = _get_supabase()
            rows = sb.table("bot_sessions").select("role,texto").eq(
                "chat_id", chat_id
            ).order("created_at", desc=True).limit(20).execute()
            SESSAO[chat_id] = [{"role": r["role"], "texto": r["texto"]} for r in reversed(rows.data)]
        except Exception as e:
            log.warning(f"bot_sessions load: {e}")
            SESSAO[chat_id] = []

    msgs = SESSAO.get(chat_id, [])
    if not msgs:
        return ""
    linhas = [f"[{m['role']}]: {m['texto']}" for m in msgs[-10:]]
    return "\n".join(linhas)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not autorizado(update):
        await update.message.reply_text("Não autorizado.")
        return
    await update.message.reply_text(
        "Cerebrum ativo.\n\n"
        "Envia um áudio ou escreve — eu classifico e guardo.\n\n"
        "🧠 Marca Pessoal: pessoal · empreendedor · ia · instagram · youtube\n"
        "⚙️ Agency OS: cliente · projeto · reunião · financeiro"
    )


async def handle_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe mensagem de voz — descarrega e transcreve via Whisper API."""
    if not autorizado(update):
        return
    msg = await update.message.reply_text("A transcrever...")
    caminho_audio = None

    try:
        voice = update.message.voice or update.message.audio
        duracao = getattr(voice, "duration", 0) or 0
        log.info(f"Áudio recebido: {duracao}s, file_id={voice.file_id}")

        # Descarrega o áudio
        ficheiro = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await ficheiro.download_to_drive(tmp.name)
            caminho_audio = tmp.name

        tamanho = os.path.getsize(caminho_audio)
        log.info(f"Áudio descarregado: {tamanho} bytes")

        # Transcreve via Whisper API
        transcricao = await transcrever_audio_api(caminho_audio)

        if not transcricao or not transcricao.strip():
            await msg.edit_text("Não consegui perceber o áudio. Tenta de novo.")
            return

        preview = transcricao[:300] + ("…" if len(transcricao) > 300 else "")
        try:
            await msg.edit_text(f"Transcrito:\n\n_{preview}_\n\nA processar...", parse_mode="Markdown")
        except Exception:
            await msg.edit_text(f"Transcrito:\n\n{preview}\n\nA processar...")
        await _processar_e_responder(update, msg, transcricao)

    except Exception as e:
        log.exception("Erro no handler de voz")
        try:
            await msg.edit_text(f"Erro: {e}")
        except Exception as e2:
            log.warning(f"edit_text erro final: {e2}")
    finally:
        if caminho_audio and os.path.exists(caminho_audio):
            os.unlink(caminho_audio)


async def handle_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe texto direto e processa."""
    if not autorizado(update):
        return
    texto = update.message.text.strip()
    if not texto:
        return

    guardar_sessao(update.effective_chat.id, "ricardo", texto)
    msg = await update.message.reply_text("A processar...")
    await _processar_e_responder(update, msg, texto)


async def _processar_e_responder(update: Update, msg, texto: str):
    try:
        import asyncio
        contexto = obter_contexto_sessao(update.effective_chat.id)
        resultado = await asyncio.to_thread(processar_com_intencao, texto, contexto=contexto, verbose=False)
        tipo = resultado["tipo"]

        if tipo == "guardar":
            r = resultado["resultado"][0]
            if r.get("destino") == "duplicado":
                resposta = "⚠ Nota duplicada — já guardei isto hoje."
            else:
                p = Path(r["caminho"])
                if r["destino"] == "supabase":
                    sync_status = "✓" if r["supabase_synced"] else "⚠ offline"
                    mundo = f"⚙️ Agency OS → Supabase {sync_status}"
                elif "marca-pessoal" in str(p):
                    mundo = "🧠 Marca Pessoal"
                else:
                    mundo = "📥 Inbox"
                categoria = p.parent.name
                resposta = f"✓ Guardado\n\n{mundo}\n📁 `{categoria}/`\n📄 `{p.name}`\n"
                if r.get("lyra_synced"):
                    resposta += "↗ Enviado para Lyra\n"

        elif tipo == "pergunta":
            resposta = f"🔍 {resultado['resultado']}"

        elif tipo == "comando":
            resposta = f"⚡ {resultado['resultado']}"

        else:
            resposta = "Processado."

        guardar_sessao(update.effective_chat.id, "cerebrum", resposta[:200])
        try:
            await msg.edit_text(resposta, parse_mode="Markdown")
        except Exception:
            await msg.edit_text(resposta)

    except Exception as e:
        log.exception("Erro ao processar")
        await msg.edit_text(f"Erro: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not TELEGRAM_TOKEN:
        print("Erro: define TELEGRAM_TOKEN.", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Erro: define ANTHROPIC_API_KEY.", file=sys.stderr)
        sys.exit(1)
    if not ALLOWED_USER_IDS:
        log.warning("⚠ ALLOWED_USERS não definido — bot acessível a qualquer pessoa!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_texto))

    # Webhook (Railway) ou polling (local)
    webhook_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if webhook_domain:
        webhook_url = f"https://{webhook_domain}/webhook"
        port = int(os.environ.get("PORT", 8443))
        log.info(f"Cerebrum bot ativo (webhook: {webhook_url})")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=webhook_url,
            url_path="/webhook",
        )
    else:
        log.info("Cerebrum bot ativo (polling — modo local).")
        app.run_polling()


if __name__ == "__main__":
    main()
