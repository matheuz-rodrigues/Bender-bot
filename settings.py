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

# Opcionais: liga/desliga da EC2 proapp-dev (usuário IAM bender-ec2, só start/stop dessa instância).
def _env_limpa(nome):
    """Valor sem espaços e sem aspas em volta (erro comum ao colar no painel da Discloud)."""
    return (os.getenv(nome) or getattr(_local, nome, "") or "").strip().strip("\"'").strip()


AWS_EC2_KEY_ID = _env_limpa("AWS_EC2_KEY_ID")
AWS_EC2_SECRET = _env_limpa("AWS_EC2_SECRET")
AWS_EC2_REGION = _env_limpa("AWS_EC2_REGION") or "sa-east-1"
AWS_EC2_INSTANCE = _env_limpa("AWS_EC2_INSTANCE")

if not TOKEN_BOT:
    raise SystemExit("TOKEN_BOT não definido: configure a variável de ambiente ou o token_bot.py")
