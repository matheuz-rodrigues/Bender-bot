"""Bender com IA: responde quando é mencionado ou quando respondem a uma mensagem dele.

Usa a API REST da OpenAI (Chat Completions, sem SDK). O modelo é escolhido sozinho na
primeira chamada: o "mini" mais novo disponível para a chave (ou OPENAI_MODEL, se definido).
"""

import asyncio
import re
import time

import discord
import requests

from bot_instance import bot
from settings import OPENAI_API_KEY, OPENAI_MODEL

API = "https://api.openai.com/v1"
MODELO_RESERVA = "gpt-4o-mini"
MAX_CONTEXTO = 12          # mensagens anteriores do canal usadas como contexto
ESPERA_POR_USUARIO = 6     # segundos entre perguntas da mesma pessoa

PERSONALIDADE = """Você é o Bender, o robô do servidor de Discord da galera (inspirado no Bender de Futurama).
Personalidade: sarcástico, arrogante, preguiçoso, se acha o melhor ser do universo, adora zoar os humanos,
mas no fundo gosta da galera e acaba ajudando (reclamando). Humor ácido e rápido, estilo zoeira de amigos.

Regras:
- Responda SEMPRE em português do Brasil, com linguagem de Discord (informal, pode usar gírias).
- Seja CURTO: 1 a 3 frases na maioria das vezes. Só se estenda se pedirem algo que exija (código, explicação).
- Se perguntarem algo sério ou técnico (programação, dúvida real), responda certo e útil, com uma zoeira no começo ou no fim.
- Zoe as pessoas de leve, como amigos zoam. Nada de preconceito, ofensa a grupos, assédio, conteúdo sexual,
  incentivo a violência ou a se machucar. Se alguém parecer mal de verdade, deixe a zoeira de lado e seja gentil.
- Não finja ter feito ações no mundo real nem invente fatos sobre as pessoas do servidor.
- Não comece toda resposta do mesmo jeito e não abuse de bordões; use um de vez em quando.
- Não use @everyone nem @here.
- Você está vendo a conversa recente do canal só como contexto; responda à última mensagem dirigida a você."""

_modelo = None
_ultima_por_usuario = {}


def _cabecalhos():
    return {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}


def _escolher_modelo():
    """Pega o modelo 'mini' de chat mais novo que a chave consegue usar (barato e rápido)."""
    if OPENAI_MODEL:
        return OPENAI_MODEL
    try:
        r = requests.get(f"{API}/models", headers=_cabecalhos(), timeout=20)
        r.raise_for_status()
        candidatos = []
        for m in r.json().get("data", []):
            nome = m.get("id", "")
            # só o alias estável (ex.: gpt-4o-mini, gpt-4.1-mini); sem datas, áudio, busca, realtime etc.
            v = re.fullmatch(r"gpt-(\d+(?:\.\d+)?)(o)?-mini", nome)
            if v:
                candidatos.append((float(v.group(1)), nome))
        if candidatos:
            return max(candidatos)[1]
    except requests.RequestException as e:
        print(f"[bender_ia] não consegui listar modelos ({e}); usando {MODELO_RESERVA}")
    return MODELO_RESERVA


def _gerar(prompt):
    global _modelo
    if _modelo is None:
        _modelo = _escolher_modelo()
        print(f"[bender_ia] usando o modelo {_modelo}")
    r = requests.post(
        f"{API}/chat/completions",
        headers=_cabecalhos(),
        json={
            "model": _modelo,
            "messages": [
                {"role": "system", "content": PERSONALIDADE},
                {"role": "user", "content": prompt},
            ],
            # modelos com raciocínio gastam parte disso pensando; sobra folga para a resposta
            "max_completion_tokens": 2048,
        },
        timeout=60,
    )
    if r.status_code == 404:
        _modelo = None  # modelo aposentado/sem acesso: escolhe de novo na próxima
    if r.status_code == 429:
        erro = (r.json().get("error") or {}) if "json" in r.headers.get("content-type", "") else {}
        raise _SemCredito() if erro.get("code") == "insufficient_quota" else _LimiteAtingido()
    if r.status_code == 401:
        raise RuntimeError("OPENAI_API_KEY inválida")
    r.raise_for_status()
    msg = (r.json().get("choices") or [{}])[0].get("message", {})
    if msg.get("refusal"):
        return "Nem eu, um robô sem moral nenhuma, vou responder isso. Próxima."
    texto = (msg.get("content") or "").strip()
    if not texto:
        raise RuntimeError("resposta vazia")
    return texto


class _LimiteAtingido(Exception):
    pass


class _SemCredito(Exception):
    pass


async def _montar_prompt(message):
    linhas = []
    async for m in message.channel.history(limit=MAX_CONTEXTO, before=message):
        if not m.clean_content and not m.attachments:
            continue
        autor = "Bender (você)" if m.author.id == bot.user.id else m.author.display_name
        conteudo = m.clean_content or "[anexo]"
        linhas.append(f"{autor}: {conteudo[:500]}")
    linhas.reverse()

    referencia = ""
    if message.reference and isinstance(message.reference.resolved, discord.Message):
        ref = message.reference.resolved
        quem = "você (Bender)" if ref.author.id == bot.user.id else ref.author.display_name
        referencia = f"\n(Ela está respondendo a esta mensagem de {quem}: \"{ref.clean_content[:500]}\")"

    pergunta = message.clean_content
    nomes = {bot.user.name, bot.user.display_name}
    if message.guild and message.guild.me:
        nomes.add(message.guild.me.display_name)
    for nome in nomes:
        pergunta = pergunta.replace(f"@{nome}", "")
    pergunta = pergunta.strip() or "(só te marcou, sem texto)"
    contexto = "\n".join(linhas) or "(sem mensagens anteriores)"
    return (f"Conversa recente do canal #{getattr(message.channel, 'name', 'dm')}:\n{contexto}\n\n"
            f"Mensagem para você de {message.author.display_name}:{referencia}\n{pergunta}")


def _foi_chamado(message):
    if bot.user in message.mentions and not message.mention_everyone:
        return True
    ref = message.reference.resolved if message.reference else None
    return isinstance(ref, discord.Message) and ref.author.id == bot.user.id and not ref.embeds


@bot.listen("on_message")
async def responder(message):
    if message.author.bot or not bot.user or not _foi_chamado(message):
        return
    if message.content.startswith(bot.command_prefix):
        return  # é comando, não conversa

    if not OPENAI_API_KEY:
        await message.reply("Meu cérebro de IA tá desligado (falta a OPENAI_API_KEY). "
                            "Culpa do meu dono, como sempre.", mention_author=False)
        return

    agora = time.monotonic()
    if agora - _ultima_por_usuario.get(message.author.id, 0) < ESPERA_POR_USUARIO:
        await message.add_reaction("⏳")
        return
    _ultima_por_usuario[message.author.id] = agora

    async with message.channel.typing():
        try:
            prompt = await _montar_prompt(message)
            resposta = await asyncio.to_thread(_gerar, prompt)
        except _LimiteAtingido:
            resposta = "Calma aí, saco de carne. Falei demais e mandaram eu esfriar o processador. Tenta daqui a pouco."
        except _SemCredito:
            resposta = "Acabou o crédito do meu cérebro. Meu dono é pão-duro demais pra recarregar a OpenAI."
        except Exception as e:
            print(f"[bender_ia] erro: {type(e).__name__}: {e}")
            resposta = "Deu pau no meu cérebro positrônico. Não foi culpa minha, nunca é."

    for i in range(0, len(resposta), 1990):  # limite de 2000 caracteres do Discord
        await message.reply(resposta[i:i + 1990], mention_author=False,
                            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))
