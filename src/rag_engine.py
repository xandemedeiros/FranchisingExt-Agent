import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Literal, TypedDict

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

import config

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
K = 3  # trechos por busca; mais que isso estoura o limite de tokens por chamada do Groq gratuito
MAX_TENTATIVAS = 3

splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


# ---------------------------------------------------------------------------
# Fontes
# ---------------------------------------------------------------------------

def fontes(docs_dir: Path | None = None) -> list[dict]:
    """Lê docs/fontes.json, com título, órgão, URL, arquivo e data de cada documento."""
    docs_dir = docs_dir or config.DOCS_DIR
    return json.loads((docs_dir / "fontes.json").read_text(encoding="utf-8"))


def baixar_fontes(docs_dir: Path | None = None) -> list[str]:
    """Baixa para docs/ os documentos que ainda não estão lá. Devolve os avisos das fontes que falharam."""
    docs_dir = docs_dir or config.DOCS_DIR
    avisos = []
    for fonte in fontes(docs_dir):
        destino = docs_dir / fonte["arquivo"]
        if destino.exists():
            continue
        request = urllib.request.Request(fonte["url"], headers={"User-Agent": "Mozilla/5.0"})
        erro = None
        for contexto in _contextos_ssl():  # o certificado do Planalto costuma falhar com a lista de CAs do Windows
            try:
                with urllib.request.urlopen(request, timeout=90, context=contexto) as response:
                    destino.write_bytes(response.read())
                print(f"baixado: {fonte['arquivo']}")
                erro = None
                break
            except OSError as exc:
                erro = exc
        if erro is not None:
            avisos.append(f"não foi possível baixar {fonte['nome_documento']} ({erro}). Abra {fonte['url']} no navegador, "
                          f"salve a página (Ctrl+S) como docs/{fonte['arquivo']} e rode `python src/rag_engine.py --reindex`.")
    for aviso in avisos:
        print("aviso:", aviso, file=sys.stderr)
    return avisos


def _contextos_ssl():
    """Contexto SSL padrão e, se o pacote certifi estiver instalado, um com a lista de CAs dele."""
    import ssl

    yield None
    try:
        import certifi

        yield ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return


def verificar_base(store) -> dict[str, int]:
    """Trechos indexados por documento, com 0 para os documentos de docs/fontes.json que ficaram de fora."""
    contagem = {f["nome_documento"]: 0 for f in fontes()}
    for meta in store.get(include=["metadatas"])["metadatas"]:
        contagem[meta["nome_documento"]] = contagem.get(meta["nome_documento"], 0) + 1
    for nome, total in contagem.items():
        if not total:
            fonte = next(f for f in fontes() if f["nome_documento"] == nome)
            print(f"ATENÇÃO: {nome} não está no índice. Abra {fonte['url']} no navegador, salve a página (Ctrl+S) "
                  f"como docs/{fonte['arquivo']} e rode `python src/rag_engine.py --reindex`.")
    return contagem


# ---------------------------------------------------------------------------
# Corte estrutural
# ---------------------------------------------------------------------------

def _numero(artigo: str) -> int:
    return int(re.sub(r"\D", "", artigo) or 0)


def blocos_lei_html(path: Path) -> list[tuple[int, str, str]]:
    """Corta o HTML de uma lei do Planalto por artigo e parágrafo, sem o texto riscado (revogado).

    Um "Art." com número menor que o anterior é citação de outra lei e fica no artigo
    que a cita, como na aula 12. A página fica 0, porque o HTML não tem páginas.
    """
    from bs4 import BeautifulSoup

    raw = path.read_bytes()
    try:  # o Planalto serve windows-1252 na maioria das leis; uma cópia salva em UTF-8 também é aceita
        html = raw.decode("utf-8")
    except UnicodeDecodeError:
        html = raw.decode("cp1252", errors="replace")
    if html.count("\ufffd") > 20:
        # acontece quando a página é salva por uma ferramenta que decodifica o windows-1252 do Planalto como
        # UTF-8 (o Invoke-WebRequest do PowerShell, por exemplo): os acentos e o "º" dos artigos se perdem
        print(f"ATENÇÃO: {path.name} está com os acentos corrompidos ('�'), e os artigos 1º a 9º não serão reconhecidos. "
              f"Baixe de novo com `curl.exe -L -o docs\\{path.name} <url>` (veja docs/fontes.json) e reindexe.", file=sys.stderr)
    soup = BeautifulSoup(html, "html.parser")
    for revoked in soup.find_all(["strike", "s", "del"]):
        revoked.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" "))
    blocos: list[tuple[int, str, str]] = []
    ultimo = 0
    # só corta onde o artigo começa ("Art. 51. Nas locações"), não nas citações ("nos termos do art. 51")
    for part in re.split(r"(?=\bArt\. ?\d+(?:-[A-Z])?\s*[º°o]?\s*[.\-–]?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ(])", text)[1:]:
        artigo = re.match(r"Art\. ?(\d+(?:-[A-Z])?)\s*([º°o](?=\W))?", part)
        numero = artigo[1] + ("º" if _numero(artigo[1]) < 10 else "")
        if blocos and _numero(numero) < ultimo:
            pagina, secao, texto = blocos[-1]
            blocos[-1] = (pagina, secao, f"{texto} {part.strip()}")
            continue
        ultimo = _numero(numero)
        # o mesmo para parágrafos: "§ 2º Na hipótese..." abre parágrafo, "disposto no § 1º," é citação
        for piece in re.split(r"(?=§ ?\d+\s*[º°o]?\s*[.\-–]?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]|Parágrafo único)", part):
            if not piece.strip():
                continue
            paragrafo = re.match(r"(§ ?\d+)\s*[º°o]?|(Parágrafo único)", piece)
            if paragrafo:
                rotulo = paragrafo[2] or (paragrafo[1].replace("§", "§ ").replace("  ", " ") + ("º" if _numero(paragrafo[1]) < 10 else ""))
                secao = f"Art. {numero}, {rotulo}"
            else:
                secao = f"Art. {numero}"
            blocos.append((0, secao, piece.strip()))
    return blocos


TITULO = re.compile(r"^(\d{1,2})\.\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n]{2,80})$")


def eh_titulo(linha: str) -> bool:
    """Título de capítulo: '3. Aspectos financeiros' ou uma linha curta toda em maiúsculas."""
    if TITULO.match(linha) and not linha.rstrip().endswith((".", ",", ";", ":")):
        return True
    letras = [c for c in linha if c.isalpha()]
    return 2 <= len(linha.split()) <= 10 and len(letras) >= 6 and all(c.isupper() for c in letras)


def blocos_pdf(path: Path) -> list[tuple[int, str, str]]:
    """Lê um PDF página a página e troca de seção quando encontra um título de capítulo."""
    import pdfplumber

    blocos: list[tuple[int, str, str]] = []
    secao = ""
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            atual: list[str] = []
            for linha in (page.extract_text() or "").splitlines():
                linha = linha.strip()
                if not linha:
                    continue
                if eh_titulo(linha):
                    if atual:
                        blocos.append((number, secao or f"Página {number}", "\n".join(atual)))
                        atual = []
                    secao = re.sub(r"\s+", " ", linha).strip().capitalize() if linha.isupper() else linha
                atual.append(linha)
            if atual:
                blocos.append((number, secao or f"Página {number}", "\n".join(atual)))
    return blocos


def carregar_documentos(docs_dir: Path | None = None) -> list[Document]:
    """Gera os trechos dos documentos de docs/fontes.json que existem na pasta, com os metadados de origem."""
    docs_dir = docs_dir or config.DOCS_DIR
    chunks: list[Document] = []
    for fonte in fontes(docs_dir):
        path = docs_dir / fonte["arquivo"]
        if not path.exists():
            continue
        blocos = blocos_lei_html(path) if path.suffix in {".htm", ".html"} else blocos_pdf(path)
        for pagina, secao, texto in blocos:
            for piece in splitter.split_text(texto):
                # o nome do documento e a seção vão no texto, para a busca achar o trecho pelo assunto
                chunks.append(Document(
                    page_content=f"{fonte['nome_documento']} – {secao}\n{piece}",
                    metadata={"nome_documento": fonte["nome_documento"], "secao": secao, "pagina": pagina,
                              "tipo_documento": fonte["tipo_documento"], "data_atualizacao": fonte["data_atualizacao"],
                              "url": fonte["url"]},
                ))
    return chunks


def abrir_indice(embeddings=None) -> Chroma:
    """Abre (ou cria vazio) o índice Chroma persistente."""
    return Chroma(
        collection_name="franchising",
        embedding_function=embeddings or config.get_embeddings(),
        persist_directory=str(config.CHROMA_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def indexar(reindex: bool = False, embeddings=None, baixar: bool = True) -> Chroma:
    """Indexa os documentos se o índice estiver vazio (ou sempre, com reindex) e devolve o vector store."""
    store = abrir_indice(embeddings)
    if reindex:
        # apaga a coleção pelo próprio Chroma, sem remover a pasta: no Windows a pasta não pode ser
        # apagada enquanto outro processo (o kernel do Jupyter ou o Streamlit) estiver com o índice aberto
        store.delete_collection()
        store = abrir_indice(embeddings)
    if not store.get(limit=1)["ids"]:
        if baixar:
            baixar_fontes()
        chunks = carregar_documentos()
        if not chunks:
            raise RuntimeError("Nenhum documento em docs/. Rode com internet ou baixe os arquivos listados em docs/fontes.json.")
        store.add_documents(chunks, ids=[f"chunk-{i}" for i in range(len(chunks))])
        por_doc = {}
        for c in chunks:
            por_doc[c.metadata["nome_documento"]] = por_doc.get(c.metadata["nome_documento"], 0) + 1
        print("trechos indexados:", por_doc)
    return store


# ---------------------------------------------------------------------------
# Subfluxo de RAG agêntico
# ---------------------------------------------------------------------------

def citacao(meta: dict) -> str:
    """Fonte no formato das respostas: (Lei nº 8.245/1991, Art. 51) ou (Sebrae – Guia de Franquias, <seção>, p. 10)."""
    if meta.get("pagina"):
        return f"({meta['nome_documento']}, {meta['secao']}, p. {meta['pagina']})"
    return f"({meta['nome_documento']}, {meta['secao']})"


def format_docs(documents: list[Document]) -> str:
    """Junta os trechos com a fonte na frente de cada um, porque o modelo só vê o texto."""
    return "\n\n".join(f"[fonte: {citacao(doc.metadata)}]\n{doc.page_content}" for doc in documents)


GRADE_PROMPT = """# Papel
Você avalia se trechos recuperados da Lei de Franquias, da Lei do Inquilinato ou do guia de franquias do Sebrae respondem a uma pergunta.

# Regras
Responda 'sim' só se algum trecho traz a informação que a pergunta pede, mesmo com outras palavras.
Responda 'nao' se os trechos só compartilham palavras ou o tema geral com a pergunta.

# Pergunta
<pergunta>
{question}
</pergunta>

# Trechos
<trechos>
{context}
</trechos>"""

REWRITE_PROMPT = """# Papel
Você reescreve perguntas de consultores e candidatos a franqueado para a busca na Lei nº 13.966/2019 (Lei de Franquias),
na Lei nº 8.245/1991 (Lei do Inquilinato) e no guia de franquias do Sebrae.

# Regras
Troque a linguagem coloquial pelos termos que esses documentos usam, como "Circular de Oferta de Franquia",
"anulabilidade", "devolução das quantias pagas", "renovação do contrato de locação", "locação não residencial",
"capital de giro", "prazo de retorno", "royalties", "fundo de propaganda" ou "ponto comercial".
Tente termos diferentes das consultas anteriores.
Responda só com a consulta reescrita, em uma linha.

# Pergunta original
<pergunta>
{question}
</pergunta>

# Consultas já tentadas
<tentadas>
{tried}
</tentadas>"""


class GradeDocuments(BaseModel):
    """Veredito sobre a relevância dos trechos."""

    binary_score: Literal["sim", "nao"] = Field(description="'sim' se os trechos respondem à pergunta, 'nao' se não")


class RAGState(TypedDict, total=False):
    pergunta: str
    tipo_documento: str | None
    consulta: str
    documentos: list[Document]
    tentativas: int
    reformulacoes: list[str]
    aprovado: bool


def criar_subgrafo_rag(llm, store: Chroma):
    """Grafo recuperar -> avaliar -> (reformular -> recuperar)*, com no máximo MAX_TENTATIVAS buscas."""
    grader = llm.with_structured_output(GradeDocuments)

    def recuperar(state: RAGState) -> dict:
        consulta = state.get("consulta") or state["pergunta"]
        tipo = state.get("tipo_documento")
        filtro = {"tipo_documento": tipo} if tipo in {"LEI", "GUIA"} else None
        documentos = store.similarity_search(consulta, k=K, filter=filtro)
        if not documentos and filtro:  # o tipo pedido pode não estar indexado (ex.: download falhou)
            documentos = store.similarity_search(consulta, k=K)
        return {"consulta": consulta, "documentos": documentos, "tentativas": state.get("tentativas", 0) + 1}

    def avaliar(state: RAGState) -> dict:
        if not state["documentos"]:
            return {"aprovado": False}
        try:
            verdict = grader.invoke(GRADE_PROMPT.format(question=state["pergunta"], context=format_docs(state["documentos"])))
            return {"aprovado": verdict.binary_score == "sim"}
        except Exception:  # juiz indisponível: segue com os trechos em vez de travar o fluxo
            return {"aprovado": True}

    def decidir(state: RAGState) -> Literal["reformular", "__end__"]:
        if state["aprovado"] or state["tentativas"] >= MAX_TENTATIVAS:
            return END
        return "reformular"

    def reformular(state: RAGState) -> dict:
        tried = [state["pergunta"], *state.get("reformulacoes", [])]
        try:
            nova = llm.invoke(REWRITE_PROMPT.format(question=state["pergunta"], tried="\n".join(tried))).text.strip()
        except Exception:  # limite de tokens ou modelo indisponível: encerra com os trechos que já tem
            return {"tentativas": MAX_TENTATIVAS}
        return {"consulta": nova, "reformulacoes": state.get("reformulacoes", []) + [nova]}

    builder = StateGraph(RAGState)
    builder.add_node("recuperar", recuperar)
    builder.add_node("avaliar", avaliar)
    builder.add_node("reformular", reformular)
    builder.add_edge(START, "recuperar")
    builder.add_edge("recuperar", "avaliar")
    builder.add_conditional_edges("avaliar", decidir)
    builder.add_edge("reformular", "recuperar")
    return builder.compile()


if __name__ == "__main__":
    store = indexar(reindex="--reindex" in sys.argv)
    print("trechos por documento:", verificar_base(store))
