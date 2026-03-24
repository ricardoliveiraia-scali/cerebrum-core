"""
Comandos — executa skills quando o Ricardo pede algo via Telegram.
"""

SKILLS_DISPONIVEIS = {
    "carrossel": {
        "descricao": "Gerar carrossel para Instagram",
        "estado": "em breve",
    },
    "guiao": {
        "descricao": "Gerar guião para vídeo YouTube",
        "estado": "em breve",
    },
    "proposta": {
        "descricao": "Gerar proposta/orçamento para cliente",
        "estado": "em breve",
    },
    "resumo": {
        "descricao": "Gerar resumo semanal/mensal",
        "estado": "em breve",
    },
}


def executar_comando(texto: str, skill_detetada: str = None) -> str:
    """Executa um comando ou indica que a skill está por implementar."""

    skill = None
    if skill_detetada:
        # Procura match parcial
        for nome, info in SKILLS_DISPONIVEIS.items():
            if nome in skill_detetada.lower():
                skill = (nome, info)
                break

    if not skill:
        # Lista skills disponíveis
        lista = "\n".join(
            f"• `{nome}` — {info['descricao']} ({info['estado']})"
            for nome, info in SKILLS_DISPONIVEIS.items()
        )
        return f"Não percebi o comando. Skills disponíveis:\n\n{lista}"

    nome, info = skill

    if info["estado"] == "em breve":
        return f"⚡ Skill `{nome}` — {info['descricao']}\n\nEm desenvolvimento. Quando estiver pronta, basta dizer e eu executo."

    # Aqui entra a lógica de execução real de cada skill
    return f"A executar `{nome}`..."
