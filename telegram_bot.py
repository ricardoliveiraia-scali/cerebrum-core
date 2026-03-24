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

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8608115531:AAGgC5x3jvATlnY0eTLFaK5rN_Li4yTyxXY")

# IDs autorizados (separados por vírgula). Se vazio, aceita todos.
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "")
ALLOWED_USER_IDS = {int(uid.strip()) for uid in ALLOWED_USERS.split(",") if uid.strip()}

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# Memória de sessão — últimas mensagens por chat
SESSAO: dict[int, list[dict]] = {}

# ---------------------------------------------------------------------------
# Transcrição via API Whisper (OpenAI) — leve, sem PyTorch
# ---------------------------------------------------------------------------

async def transcrever_audio_api(caminho: str) -> str:
    """Transcreve áudio via Anthropic/OpenAI Whisper API (HTTP)."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não definida — transcrição por API indisponível.")

    async with httpx.AsyncClient(timeout=120) as client:
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


def guardar_sessao(chat_id: int, role: str, texto: str):
    """Guarda mensagem na memória de sessão (últimas 20)."""
    if chat_id not in SESSAO:
        SESSAO[chat_id] = []
    SESSAO[chat_id].append({"role": role, "texto": texto})
    SESSAO[chat_id] = SESSAO[chat_id][-20:]


def obter_contexto_sessao(chat_id: int) -> str:
    """Devolve as últimas mensagens como contexto."""
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

    voice = update.message.voice or update.message.audio
    transcricao = None

    # Descarrega o áudio e transcreve via API
    ficheiro = await context.bot.get_file(voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await ficheiro.download_to_drive(tmp.name)
        caminho_audio = tmp.name
    try:
        transcricao = await transcrever_audio_api(caminho_audio)
    except RuntimeError as e:
        await msg.edit_text(f"Erro na transcrição: {e}")
        return
    finally:
        os.unlink(caminho_audio)

    if not transcricao or not transcricao.strip():
        await msg.edit_text("Não consegui perceber o áudio. Tenta de novo.")
        return

    await msg.edit_text(f"Transcrito:\n\n_{transcricao}_\n\nA processar...", parse_mode="Markdown")
    await _processar_e_responder(update, msg, transcricao)


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
            resposta = "✓ Guardado\n\n"
            for r in resultado["resultado"]:
                p = Path(r["caminho"])
                if r["destino"] == "supabase":
                    sync_status = "✓" if r["supabase_synced"] else "⚠ offline"
                    mundo = f"⚙️ Agency OS → Supabase {sync_status}"
                elif "marca-pessoal" in str(p):
                    mundo = "🧠 Marca Pessoal"
                else:
                    mundo = "📥 Inbox"
                categoria = p.parent.name
                resposta += f"{mundo}\n📁 `{categoria}/`\n📄 `{p.name}`\n\n"

        elif tipo == "pergunta":
            resposta = f"🔍 {resultado['resultado']}"

        elif tipo == "comando":
            resposta = f"⚡ {resultado['resultado']}"

        else:
            resposta = "Processado."

        guardar_sessao(update.effective_chat.id, "cerebrum", resposta[:200])
        await msg.edit_text(resposta, parse_mode="Markdown")

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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Erro: define ANTHROPIC_API_KEY.", file=sys.stderr)
        sys.exit(1)

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
