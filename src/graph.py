import asyncio
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph

import config
from nodes import criar_nos
from rag_engine import criar_subgrafo_rag, indexar
from state import AgentState


async def carregar_ferramentas_mcp(servers: dict | None = None) -> tuple[list, dict[str, str]]:
    """Lista as ferramentas de cada servidor MCP separadamente, para que um servidor fora do ar não derrube os outros."""
    from fastmcp.client.transports import StdioTransport
    from langchain.mcp import MCPAdapter

    ferramentas, status = [], {}
    for nome, cfg in (servers or config.mcp_servers()).items():
        try:
            if "command" in cfg:
                # o stderr do servidor vai para um arquivo: no Jupyter para Windows o sys.stderr não tem
                # fileno, e o subprocesso falha com "Client failed to connect: fileno"
                config.DATA_DIR.mkdir(exist_ok=True)
                transporte = StdioTransport(command=cfg["command"], args=cfg["args"], log_file=config.DATA_DIR / f"mcp_{nome}.log")
                adapter = MCPAdapter(transporte)
            else:
                adapter = MCPAdapter({"mcpServers": {nome: cfg}})
            lista = await asyncio.wait_for(adapter.list_tools(), timeout=45)
            if nome == "exa":  # menor privilégio (aula 14): do conector externo, só as ferramentas de busca
                lista = [t for t in lista if "search" in t.name]
            ferramentas += lista
            status[nome] = f"ok: {', '.join(t.name for t in lista)}"
        except Exception as error:  # noqa: BLE001
            status[nome] = f"indisponível ({type(error).__name__}: {error})"[:300]
    return ferramentas, status


def criar_grafo(llm, ferramentas_mcp: list, store, checkpointer=None):
    """Compila o grafo com o modelo, as ferramentas MCP, o índice do RAG e o checkpointer dados."""
    nos = criar_nos(llm, ferramentas_mcp, criar_subgrafo_rag(llm, store))

    builder = StateGraph(AgentState)
    for nome in ["no_guardrail_entrada", "no_agente_orquestrador", "no_rag_agentico", "no_ferramentas_mcp", "no_guardrail_saida"]:
        builder.add_node(nome, nos[nome])

    builder.add_edge(START, "no_guardrail_entrada")
    builder.add_conditional_edges("no_guardrail_entrada", nos["rota_entrada"])
    builder.add_conditional_edges("no_agente_orquestrador", nos["rota_orquestrador"])
    builder.add_conditional_edges("no_rag_agentico", nos["rota_rag"])
    builder.add_edge("no_ferramentas_mcp", "no_agente_orquestrador")
    builder.add_conditional_edges("no_guardrail_saida", nos["rota_saida"])

    return builder.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())


async def criar_assistente(checkpointer=None, llm=None, store=None):
    """Monta tudo com as configurações do .env: modelo, índice (criado na primeira vez) e servidores MCP."""
    llm = llm or config.get_model()
    store = store or indexar()
    ferramentas, status = await carregar_ferramentas_mcp()
    if not status.get("franquia", "").startswith("ok"):
        # sem o servidor próprio o modelo não tem as ferramentas de cálculo; melhor parar com o motivo
        raise RuntimeError(
            f"O servidor MCP próprio não iniciou: {status.get('franquia')}. "
            "Teste-o com `python src/mcp_server/mcp_franchising_server.py`. No Jupyter para Windows, "
            "rode o grafo pelo runtime.executar (como no notebook do projeto), e não com await direto."
        )
    return criar_grafo(llm, ferramentas, store, checkpointer), status


async def conversar(grafo, texto: str, thread_id: str, modelo_em_analise: str | None = None) -> dict:
    """Roda um turno da conversa e devolve o estado final. O histórico vem do checkpointer pelo thread_id."""
    entrada = {"messages": [HumanMessage(texto)]}
    if modelo_em_analise:
        entrada["modelo_em_analise"] = modelo_em_analise
    return await grafo.ainvoke(entrada, {"configurable": {"thread_id": thread_id}, "recursion_limit": 60})


def novo_thread_id(prefixo: str = "sessao") -> str:
    """Identificador de conversa, como candidato_joao_silva_001 ou sessao_3f2a9c1b."""
    return f"{prefixo}_{uuid.uuid4().hex[:8]}"
