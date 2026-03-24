FROM python:3.11-slim

WORKDIR /app

# Instala ffmpeg para Whisper (transcrição de áudio)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cria pastas do vault
RUN mkdir -p vault/marca-pessoal/pessoal \
    vault/marca-pessoal/empreendedor \
    vault/marca-pessoal/ia \
    vault/marca-pessoal/instagram \
    vault/marca-pessoal/youtube \
    vault/agency-os/clientes \
    vault/agency-os/projetos \
    vault/agency-os/reunioes \
    vault/agency-os/financeiro \
    vault/inbox

CMD ["python3", "telegram_bot.py"]
