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

async def transcrever_audio_api(caminho: str) -> str:
    """Transcreve áudio via Anthropic/OpenAI Whisper API (HTTP)."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não definida — transcrição por API indisponível.")

    async with httpx.AsyncClient(timeout=300) as client:
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
    except Exception:
        pass


def obter_contexto_sessao(chat_id: int) -> str:
    """Devolve as últimas mensagens como contexto (Supabase se cache vazio)."""
    if chat_id not in SESSAO:
        try:
            sb = _get_supabase()
            rows = sb.table("bot_sessions").select("role,texto").eq(
                "chat_id", chat_id
            ).order("created_at", desc=True).limit(20).execute()
            SESSAO[chat_id] = [{"role": r["role"], "texto": r["texto"]} for r in reversed(rows.data)]
        except Exception:
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

        try:
            await msg.edit_text(f"Transcrito:\n\n_{transcricao}_\n\nA processar...", parse_mode="Markdown")
        except Exception:
            await msg.edit_text(f"Transcrito:\n\n{transcricao}\n\nA processar...")
        await _processar_e_responder(update, msg, transcricao)

    except Exception as e:
        log.exception("Erro no handler de voz")
        try:
            await msg.edit_text(f"Erro: {e}")
        except Exception:
            pass
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
        contexto = obter_contexto_sessao(update.effective_chat.id)
        resultado = processar_com_intencao(texto, contexto=contexto, verbose=False)
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
# Resumo diário
# ---------------------------------------------------------------------------

async def enviar_resumo_diario(context: ContextTypes.DEFAULT_TYPE):
    """Envia resumo do dia às 21h para todos os utilizadores autorizados."""
    from cerebrum.resumo import gerar_resumo_diario

    try:
        resumo = gerar_resumo_diario()
        if not resumo:
            return

        for uid in ALLOWED_USER_IDS:
            try:
                await context.bot.send_message(chat_id=uid, text=resumo, parse_mode="Markdown")
            except Exception as e:
                log.warning(f"Não consegui enviar resumo para {uid}: {e}")
    except Exception as e:
        log.exception(f"Erro no resumo diário: {e}")


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

    # Resumo diário às 21h (UTC+0 — ajustar se necessário)
    if ALLOWED_USER_IDS:
        from telegram.ext import JobQueue
        import datetime
        app.job_queue.run_daily(
            enviar_resumo_diario,
            time=datetime.time(hour=21, minute=0),
            name="resumo_diario",
        )
        log.info("Resumo diário agendado para 21:00.")

    log.info("Cerebrum bot ativo.")
    app.run_polling()


if __name__ == "__main__":
    main()
