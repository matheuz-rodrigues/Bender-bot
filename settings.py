"""Configuração do bot.

Na Discloud (deploy via GitHub) os valores vêm das variáveis de ambiente
informadas no upload (TOKEN_BOT e URL_API), que ela grava num .env.
Localmente, se existir, usa o token_bot.py (que não vai para o Git).
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import token_bot as _local
except ImportError:
    _local = None

TOKEN_BOT = os.getenv("TOKEN_BOT") or getattr(_local, "TOKEN_BOT", "")
url_api = os.getenv("URL_API") or getattr(_local, "url_api", "") or "http://localhost/"
if not url_api.endswith("/"):
    url_api += "/"

# Opcionais: IA do Bender (chave em platform.openai.com/api-keys). Sem chave, a IA fica desligada.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or getattr(_local, "OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or getattr(_local, "OPENAI_MODEL", "")

if not TOKEN_BOT:
    raise SystemExit("TOKEN_BOT não definido: configure a variável de ambiente ou o token_bot.py")
