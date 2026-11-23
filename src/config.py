import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DOCS_DIR = ROOT / "docs"          # documentos reais da base (baixados na indexação)
FONTES_FILE = DOCS_DIR / "fontes.json"  # origem de cada documento: órgão, URL, data
DATA_DIR = ROOT / "data"
SKILLS_DIR = ROOT / "skills"
CHROMA_DIR = DATA_DIR / "chroma_franchising"
CHECKPOINT_DB = DATA_DIR / "checkpoints.sqlite"
MCP_SERVER = ROOT / "src" / "mcp_server" / "mcp_franchising_server.py"

# Chat pelo Groq, como no notebook 08. Outros exemplos: "openai:gpt-4.1-mini", "google_genai:gemini-2.5-flash".
LLM_MODEL = os.getenv("LLM_MODEL", "groq:openai/gpt-oss-120b")
# O Groq não oferece embeddings; o padrão é o modelo local que as aulas 11 e 12 deixam como alternativa.
# Para usar a OpenAI: EMBEDDINGS_MODEL=openai:text-embedding-3-small (e apague data/chroma_franchising).
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# Servidor MCP da comunidade usado na aula 13, remoto e sem chave.
EXA_MCP_URL = os.getenv("EXA_MCP_URL", "https://mcp.exa.ai/mcp")

os.environ.setdefault("FASTMCP_LOG_LEVEL", "WARNING")


def get_model(temperature: float = 0.0):
    """Modelo de chat definido em LLM_MODEL."""
    from langchain.chat_models import init_chat_model

    return init_chat_model(LLM_MODEL, temperature=temperature)


def get_embeddings():
    """Embeddings definidos em EMBEDDINGS_MODEL: 'provedor:modelo' pelo LangChain ou um modelo local do Hugging Face."""
    if ":" in EMBEDDINGS_MODEL:
        from langchain.embeddings import init_embeddings

        return init_embeddings(EMBEDDINGS_MODEL)
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=EMBEDDINGS_MODEL)


def mcp_servers() -> dict[str, dict]:
    """Servidores MCP do assistente, no formato mcpServers: o próprio, por stdio, e o Exa, remoto."""
    servers = {"franquia": {"command": sys.executable, "args": [str(MCP_SERVER)]}}
    if EXA_MCP_URL:
        servers["exa"] = {"url": EXA_MCP_URL}
    return servers
