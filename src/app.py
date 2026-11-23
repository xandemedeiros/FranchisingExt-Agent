import json

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

import config
from graph import criar_assistente, novo_thread_id
from rag_engine import fontes
from runtime import executar  # laço de fundo (Proactor no Windows) para o grafo e o MCP

st.set_page_config(page_title="Assistente de Expansão de Franchising", layout="wide")

MODELOS = {"Não definido": None, "Quiosque": "quiosque", "Loja de Rua": "loja_rua", "Loja de Shopping": "loja_shopping"}
NOMES_NOS = {
    "no_guardrail_entrada": "Guardrail de entrada", "no_agente_orquestrador": "orquestrador",
    "no_rag_agentico": "RAG agêntico", "no_ferramentas_mcp": "ferramentas MCP", "no_guardrail_saida": "Guardrail de saída",
}


# ---------------------------------------------------------------------------
# Laço de eventos em segundo plano e montagem do assistente
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Preparando índice, modelo e conectores MCP...")
def assistente():
    async def montar():
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        config.DATA_DIR.mkdir(exist_ok=True)
        saver = AsyncSqliteSaver(await aiosqlite.connect(config.CHECKPOINT_DB))
        await saver.setup()
        grafo, status = await criar_assistente(saver)
        return grafo, saver, status
    return executar(montar())


async def listar_threads(saver) -> list[str]:
    vistos = []
    async for checkpoint in saver.alist(None, limit=500):
        thread = checkpoint.config["configurable"]["thread_id"]
        if thread not in vistos:
            vistos.append(thread)
    return vistos


async def rodar_turno(grafo, texto: str, thread_id: str, modelo: str | None):
    """Executa um turno pelo astream, guardando a ordem dos nós, e devolve."""
    entrada = {"messages": [HumanMessage(texto)], "modelo_em_analise": modelo}
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": 60}
    caminho = []
    async for update in grafo.astream(entrada, cfg, stream_mode="updates"):
        caminho += list(update)
    return caminho, (await grafo.aget_state(cfg)).values


# ---------------------------------------------------------------------------
# Rastreabilidade
# ---------------------------------------------------------------------------

def mostrar_json(texto: str):
    try:
        st.json(json.loads(texto), expanded=False)
    except (json.JSONDecodeError, TypeError):
        st.code(str(texto)[:2000])


def painel_rastreabilidade(trace: dict, caminho: list[str] | None):
    with st.expander("Rastreabilidade e Auditoria do Grafo"):
        entrada, saida = trace.get("guardrail_entrada", {}), trace.get("guardrail_saida", {})
        c1, c2 = st.columns(2)
        c1.markdown(f"**Guardrail de entrada:** {'Aprovado' if entrada.get('ok') else 'Reprovado (' + str(entrada.get('motivo')) + ')'}")
        c2.markdown(f"**Guardrail de saída:** {'Aprovado' if saida.get('ok') else 'Corrigido'}"
                    + (f" · devolvido ao orquestrador {saida['devolucoes']}x" if saida.get("devolucoes") else ""))
        if saida.get("problemas"):
            st.caption("Auditoria: " + "; ".join(saida["problemas"]))
        if caminho:
            st.markdown("**Caminho no grafo:** " + " → ".join(NOMES_NOS.get(n, n) for n in caminho))

        st.markdown("**Skills carregadas no turno:** " + (", ".join(f"`{s}`" for s in trace.get("skills_carregadas", [])) or "nenhuma"))

        rag = trace.get("rag", {})
        st.markdown(f"**RAG agêntico:** {rag.get('tentativas', 0)} busca(s)")
        for i, consulta in enumerate(rag.get("reformulacoes", []), 1):
            st.markdown(f"- reformulação {i}: _{consulta}_")
        if rag.get("documentos"):
            st.dataframe(
                [{"fonte": d["citacao"], "consulta": d["consulta"], "aprovado": d["aprovado"], "trecho": d["trecho"]} for d in rag["documentos"]],
                hide_index=True, width="stretch",
            )

        ferramentas = trace.get("ferramentas", [])
        st.markdown(f"**Chamadas MCP:** {len(ferramentas)}")
        for f in ferramentas:
            st.markdown(f"`{f['ferramenta']}` · {f['status']}")
            a, b = st.columns(2)
            with a:
                st.caption("parâmetros de entrada")
                st.json(f["argumentos"], expanded=False)
            with b:
                st.caption("retorno")
                mostrar_json(f["retorno"])


def resumo_turno(trace: dict):
    """Linha sempre visível com as ferramentas chamadas, as skills carregadas e as fontes citadas no turno."""
    ferramentas = [f["ferramenta"] for f in trace.get("ferramentas", [])]
    if trace.get("rag", {}).get("tentativas"):
        ferramentas = ["buscar_documentos"] + ferramentas
    skills = trace.get("skills_carregadas", [])
    fontes = sorted({d["nome_documento"] for d in trace.get("rag", {}).get("documentos", [])})
    partes = [
        "**Ferramentas:** " + (", ".join(f"`{f}`" for f in dict.fromkeys(ferramentas)) or "nenhuma"),
        "**Skills:** " + (", ".join(f"`{s}`" for s in skills) or "nenhuma"),
    ]
    if fontes:
        partes.append("**Fontes:** " + ", ".join(fontes))
    if not trace.get("guardrail_entrada", {}).get("ok", True):
        partes.append(f"**Bloqueado:** {trace['guardrail_entrada'].get('motivo')}")
    st.caption(" · ".join(partes))


def mostrar_historico(valores: dict):
    for m in valores.get("messages", []):
        if isinstance(m, HumanMessage) and m.name != "auditoria":
            st.chat_message("user").markdown(m.text)
        elif isinstance(m, AIMessage) and not m.tool_calls and m.text:
            with st.chat_message("assistant"):
                st.markdown(m.text)
                if trace := m.additional_kwargs.get("rastreabilidade"):
                    resumo_turno(trace)
                    painel_rastreabilidade(trace, st.session_state.caminhos.get(m.id))


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

st.session_state.setdefault("thread_id", novo_thread_id())
st.session_state.setdefault("caminhos", {})

try:
    grafo, saver, status = assistente()
except Exception as error:  # noqa: BLE001
    st.error(f"Não foi possível iniciar o assistente: {error}")
    st.info("Confira a GROQ_API_KEY no arquivo .env e se o índice foi criado com `python src/rag_engine.py`.")
    st.stop()

with st.sidebar:
    st.header("Sessão")
    if st.button("Nova Conversa / Reset", width="stretch"):
        st.session_state.thread_id = novo_thread_id()
        st.rerun()

    threads = executar(listar_threads(saver))
    opcoes = [st.session_state.thread_id] + [t for t in threads if t != st.session_state.thread_id]
    escolhido = st.selectbox("Conversa (thread_id)", opcoes, index=0)
    if escolhido != st.session_state.thread_id:
        st.session_state.thread_id = escolhido
        st.rerun()
    novo = st.text_input("Abrir ou criar thread_id", placeholder="candidato_joao_silva_001")
    if novo and novo != st.session_state.thread_id:
        st.session_state.thread_id = novo.strip()
        st.rerun()

    modelo_label = st.selectbox("Modelo de franquia em análise", list(MODELOS))
    st.divider()
    st.caption(f"LLM: `{config.LLM_MODEL}`")
    st.caption(f"Embeddings: `{config.EMBEDDINGS_MODEL}`")
    for servidor, situacao in status.items():
        st.caption(f"{'' if situacao.startswith('ok') else ''} MCP **{servidor}**: {situacao}")
    with st.expander("Base de documentos do RAG"):
        for fonte in fontes():
            baixado = (config.DOCS_DIR / fonte["arquivo"]).exists()
            st.markdown(f"{'' if baixado else ''} [{fonte['titulo']}]({fonte['url']})  \n_{fonte['orgao']}_")

st.title("Assistente de Expansão de Franchising")
st.caption("Co-piloto da equipe de expansão: qualificação de candidatos, viabilidade financeira, análise de pontos e dúvidas sobre a Lei de Franquias, a Lei do Inquilinato e o guia do Sebrae.")

config_thread = {"configurable": {"thread_id": st.session_state.thread_id}}
mostrar_historico(executar(grafo.aget_state(config_thread)).values)

if pergunta := st.chat_input("Ex.: Quero simular o modelo Loja de Rua com R$ 300.000 e aluguel de R$ 8.000"):
    st.chat_message("user").markdown(pergunta)
    with st.chat_message("assistant"), st.spinner("Consultando guardrails, COF e ferramentas MCP..."):
        try:
            caminho, valores = executar(rodar_turno(grafo, pergunta, st.session_state.thread_id, MODELOS[modelo_label]))
            ultima = valores["messages"][-1]
            st.session_state.caminhos[ultima.id] = caminho
        except Exception as error:  # noqa: BLE001
            st.error(f"Erro ao executar o grafo: {error}")
            st.stop()
    st.rerun()
