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
import subprocess
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from cerebrum.agente import processar

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8608115531:AAGgC5x3jvATlnY0eTLFaK5rN_Li4yTyxXY")

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Transcrição
# ---------------------------------------------------------------------------

def transcrever_audio(caminho: str) -> str:
    """Transcreve áudio com Whisper (CLI local)."""
    try:
        resultado = subprocess.run(
            ["/Users/ricardooliveira/Library/Python/3.9/bin/whisper", caminho, "--language", "pt", "--model", "base", "--output_format", "txt", "--output_dir", "/tmp"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        txt_path = Path("/tmp") / (Path(caminho).stem + ".txt")
        if txt_path.exists():
            return txt_path.read_text(encoding="utf-8").strip()
        raise RuntimeError(resultado.stderr)
    except FileNotFoundError:
        raise RuntimeError("Whisper não instalado. Corre: pip install openai-whisper")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Cerebrum ativo.\n\n"
        "Envia um áudio ou escreve — eu classifico e guardo.\n\n"
        "🧠 Marca Pessoal: pessoal · empreendedor · ia · instagram · youtube\n"
        "⚙️ Agency OS: cliente · projeto · reunião · financeiro"
    )


async def handle_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe mensagem de voz — usa transcrição do Telegram se disponível, senão Whisper."""
    msg = await update.message.reply_text("A transcrever...")

    voice = update.message.voice or update.message.audio
    transcricao = None

    # Tenta usar a transcrição já feita pelo Telegram
    if hasattr(update.message, "voice") and update.message.voice:
        try:
            result = await context.bot.transcribe_audio(
                chat_id=update.message.chat_id,
                message_id=update.message.message_id,
            )
            # Aguarda até a transcrição estar pronta (max 30s)
            for _ in range(15):
                if result.text:
                    transcricao = result.text
                    break
                await asyncio.sleep(2)
                result = await context.bot.transcribe_audio(
                    chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                )
        except Exception:
            pass  # fallback para Whisper

    # Fallback: Whisper local
    if not transcricao:
        ficheiro = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await ficheiro.download_to_drive(tmp.name)
            caminho_audio = tmp.name
        try:
            transcricao = transcrever_audio(caminho_audio)
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
    texto = update.message.text.strip()
    if not texto:
        return

    msg = await update.message.reply_text("A processar...")
    await _processar_e_responder(update, msg, texto)


async def _processar_e_responder(update: Update, msg, texto: str):
    try:
        caminhos = processar(texto, verbose=False)

        resposta = "✓ Guardado\n\n"
        for c in caminhos:
            p = Path(c)
            # Mostra se foi para Marca Pessoal ou Agency OS
            if "marca-pessoal" in str(p):
                mundo = "🧠 Marca Pessoal"
            elif "agency-os" in str(p):
                mundo = "⚙️ Agency OS → Supabase"
            else:
                mundo = "📥 Inbox"
            categoria = p.parent.name
            resposta += f"{mundo}\n📁 `{categoria}/`\n📄 `{p.name}`\n\n"

        await msg.edit_text(resposta, parse_mode="Markdown")

    except Exception as e:
        log.exception("Erro ao processar")
        await msg.edit_text(f"Erro: {e}")


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

    log.info("Cerebrum bot ativo.")
    app.run_polling()


if __name__ == "__main__":
    main()
