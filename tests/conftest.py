"""Peças compartilhadas pelos testes: caminho do src, embeddings offline e um modelo roteirizado."""

import hashlib
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from langchain_core.embeddings import Embeddings  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402


class HashEmbeddings(Embeddings):
    """Embedding de saco de palavras por hashing: sem rede, determinístico e bom o bastante para testar a busca."""

    dim = 1024

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for token in re.findall(r"\w{3,}", text.lower()):
            v[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


class ScriptedLLM(BaseChatModel):
    """Modelo falso: `responder` decide a AIMessage e `structured` decide as saídas estruturadas."""

    responder: Any
    structured: Any

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.responder(messages))])

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(lambda prompt: self.structured(schema, prompt))


@pytest.fixture
def scripted() -> Callable[..., ScriptedLLM]:
    def make(responder, structured=None):
        def default_structured(schema, prompt):
            fields = schema.model_fields
            if "binary_score" in fields:
                return schema(binary_score="sim")
            return schema(categoria="franchising", motivo="teste")
        return ScriptedLLM(responder=responder, structured=structured or default_structured)
    return make


GUIA_EXEMPLO = [  # páginas de um guia SINTÉTICO, no formato do guia do Sebrae, só para os testes offline
    ["FRANQUEADO", "1. Como escolher a franquia certa",
     "Antes de escolher, o candidato deve avaliar o próprio perfil, o segmento e a rede franqueadora."],
    ["3. Aspectos financeiros",
     "O investimento inicial inclui taxa de franquia, instalação, equipamentos e despesas de abertura.",
     "O capital de giro costuma não ser informado espontaneamente: pergunte quanto é necessário além da taxa e da instalação.",
     "Os royalties são em geral um percentual mensal do faturamento bruto, e o fundo de propaganda financia o marketing da rede.",
     "O prazo de retorno varia muito entre os modelos, e o prazo do contrato deve ser maior que o prazo de retorno esperado."],
    ["5. O ponto comercial",
     "O ponto é fator crítico de sucesso. Verifique licenças, se o aluguel cabe no plano de negócios",
     "e o prazo e as condições de renovação do contrato de locação, porque a reforma do imóvel se perde se a locação acabar cedo."],
]


@pytest.fixture(scope="session")
def docs_dir(tmp_path_factory):
    """Pasta docs/ de teste: o fontes.json real, as leis de exemplo e um guia de exemplo em PDF."""
    import shutil

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    import config

    root = Path(__file__).resolve().parents[1]
    pasta = tmp_path_factory.mktemp("docs")
    shutil.copy(root / "docs" / "fontes.json", pasta / "fontes.json")
    shutil.copy(root / "tests" / "fixtures" / "lei_13966_exemplo.htm", pasta / "Lei_13966_2019.htm")
    shutil.copy(root / "tests" / "fixtures" / "lei_8245_exemplo.htm", pasta / "Lei_8245_1991.htm")
    pdf = canvas.Canvas(str(pasta / "Sebrae_Guia_Franquias.pdf"), pagesize=A4)
    for linhas in GUIA_EXEMPLO:
        y = 780
        for linha in linhas:
            pdf.drawString(50, y, linha)
            y -= 20
        pdf.showPage()
    pdf.save()
    config.DOCS_DIR = pasta
    return pasta


@pytest.fixture(scope="session")
def store(tmp_path_factory, docs_dir):
    """Índice Chroma com os documentos de teste, em pasta temporária e com HashEmbeddings."""
    import config
    import rag_engine

    config.CHROMA_DIR = tmp_path_factory.mktemp("chroma")
    return rag_engine.indexar(embeddings=HashEmbeddings(), baixar=False)


@pytest.fixture(scope="session")
def mcp_tools():
    """Ferramentas do servidor MCP próprio, sem o Exa (que exige internet)."""
    import asyncio

    import config
    from graph import carregar_ferramentas_mcp

    servers = {"franquia": config.mcp_servers()["franquia"]}
    tools, status = asyncio.run(carregar_ferramentas_mcp(servers))
    assert status["franquia"].startswith("ok"), status
    return tools


def ai(text: str = "", calls: list[dict] | None = None) -> AIMessage:
    """AIMessage com chamadas de ferramenta no formato do LangChain."""
    return AIMessage(text, tool_calls=[{"name": n, "args": a, "id": f"call_{i}_{n}"} for i, (n, a) in enumerate(calls or [])])
