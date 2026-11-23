from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # O PDF sugere operator.add; add_messages faz a mesma concatenação e ainda permite
    # substituir uma mensagem pelo id (usado pelo guardrail de saída para trocar a
    # resposta auditada) e removê-la com RemoveMessage.
    messages: Annotated[List[BaseMessage], add_messages]
    user_input: str
    modelo_em_analise: Optional[str]
    guardrail_entrada_ok: bool
    guardrail_motivo: Optional[str]
    skills_carregadas: List[str]
    documentos_recuperados: List[Dict[str, Any]]
    rag_tentativas: int
    ferramentas_executadas: List[Dict[str, Any]]
    resposta_final: Optional[str]
    guardrail_saida_ok: bool
    rag_reformulacoes: List[str]
    auditoria_saida: List[str]
    saida_tentativas: int
    passos: int
