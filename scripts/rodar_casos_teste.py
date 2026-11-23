"""Roda os dez casos de teste com o modelo real e preenche a tabela de resultados do README.

    python scripts/rodar_casos_teste.py                 # todos os casos
    python scripts/rodar_casos_teste.py --ids 04,07     # só alguns (os demais resultados são mantidos)
    python scripts/rodar_casos_teste.py --pausa 20      # segundos entre casos (limite de tokens do Groq)

Gera resultados/resultados_casos.json, resultados/resultados_casos.md (com as respostas
completas e a rastreabilidade) e reescreve o trecho do README entre os marcadores
RESULTADOS:INICIO e RESULTADOS:FIM com a entrada, o esperado, o obtido, a aprovação e
a taxa de acerto. A análise dos erros é escrita pela dupla logo abaixo da tabela.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

import config  # noqa: E402
from casos_teste import CASOS, resumo_obtido  # noqa: E402
from graph import conversar, criar_assistente  # noqa: E402

RESULTADOS = ROOT / "resultados"
README = ROOT / "README.md"
INICIO, FIM = "<!-- RESULTADOS:INICIO -->", "<!-- RESULTADOS:FIM -->"


def celula(texto: str) -> str:
    return " ".join(str(texto).split()).replace("|", "\\|")


async def rodar(ids: set[str] | None, pausa: float) -> dict:
    anteriores = {}
    arquivo = RESULTADOS / "resultados_casos.json"
    if arquivo.exists():
        anteriores = {r["id"]: r for r in json.loads(arquivo.read_text(encoding="utf-8"))["casos"]}

    grafo, status = await criar_assistente(MemorySaver())
    print("conectores MCP:", status)
    resultados = dict(anteriores)
    selecionados = [c for c in CASOS if not ids or c.id in ids]
    for i, caso in enumerate(selecionados):
        if i:
            await asyncio.sleep(pausa)
        print(f"\n=== caso {caso.id}: {caso.componente}")
        inicio, estado, erro = time.time(), {}, None
        thread = f"caso_{caso.id}_{datetime.now():%H%M%S}"
        try:
            for turno in caso.turnos:
                print("  usuário:", turno)
                estado = await conversar(grafo, turno, thread)
            aprovado, detalhe = caso.verificar(estado)
        except Exception as exc:  # noqa: BLE001
            aprovado, detalhe, erro = False, f"erro de execução: {type(exc).__name__}: {exc}", str(exc)
        resultados[caso.id] = {
            "id": caso.id, "componente": caso.componente, "desafiador": caso.desafiador, "turnos": caso.turnos,
            "esperado": caso.esperado, "obtido": resumo_obtido(estado) if estado else f"Erro: {erro}",
            "aprovado": aprovado, "verificacao": detalhe, "segundos": round(time.time() - inicio, 1),
            "resposta_final": estado.get("resposta_final"), "skills": estado.get("skills_carregadas", []),
            "ferramentas": estado.get("ferramentas_executadas", []), "rag_tentativas": estado.get("rag_tentativas", 0),
            "rag_reformulacoes": estado.get("rag_reformulacoes", []),
            "fontes": sorted({d["citacao"] for d in estado.get("documentos_recuperados", [])}),
            "guardrail_entrada": {"ok": estado.get("guardrail_entrada_ok"), "motivo": estado.get("guardrail_motivo")},
            "auditoria_saida": estado.get("auditoria_saida", []),
        }
        print(f"  {'APROVADO' if aprovado else 'REPROVADO'} ({detalhe})")
    return {"modelo": config.LLM_MODEL, "embeddings": config.EMBEDDINGS_MODEL, "data": datetime.now().isoformat(timespec="minutes"),
            "conectores": status, "casos": [resultados[c.id] for c in CASOS if c.id in resultados]}


def tabela(dados: dict) -> str:
    casos = dados["casos"]
    aprovados = sum(r["aprovado"] for r in casos)
    linhas = [
        f"_Execução de {dados['data']} com `{dados['modelo']}` e embeddings `{dados['embeddings']}`. "
        "Respostas completas e rastreabilidade em [`resultados/resultados_casos.md`](resultados/resultados_casos.md)._",
        "",
        "| ID | Componente | Entrada | Resultado esperado | Resultado obtido | Aprovado |",
        "|---|---|---|---|---|---|",
    ]
    for r in casos:
        entrada = " <br>".join(f"T{i}: {t}" for i, t in enumerate(r["turnos"], 1)) if len(r["turnos"]) > 1 else r["turnos"][0]
        nome = r["componente"] + (" *(desafiador)*" if r["desafiador"] else "")
        status = "✅ Sim" if r["aprovado"] else f"❌ Não ({celula(r['verificacao'])})"
        linhas.append(f"| {r['id']} | {celula(nome)} | {celula(entrada)} | {celula(r['esperado'])} | {celula(r['obtido'])} | {status} |")
    total = len(casos)
    linhas += ["", f"**Taxa de acerto: {aprovados}/{total} ({100 * aprovados / max(total, 1):.0f}%).**"]
    return "\n".join(linhas)


def detalhado(dados: dict) -> str:
    partes = [f"# Resultados dos casos de teste\n\nModelo `{dados['modelo']}`, embeddings `{dados['embeddings']}`, execução de {dados['data']}.\n",
              "Conectores MCP: " + "; ".join(f"{k}: {v}" for k, v in dados["conectores"].items()) + "\n"]
    for r in dados["casos"]:
        partes.append(f"## Caso {r['id']}: {r['componente']} — {'APROVADO' if r['aprovado'] else 'REPROVADO'}\n")
        for i, t in enumerate(r["turnos"], 1):
            partes.append(f"**Turno {i}:** {t}\n")
        partes += [f"**Esperado:** {r['esperado']}\n", f"**Verificação:** {r['verificacao']} ({r['segundos']} s)\n",
                   f"**Guardrail de entrada:** {r['guardrail_entrada']} · **Auditoria de saída:** {r['auditoria_saida'] or 'sem problemas'}\n",
                   f"**Skills:** {r['skills'] or 'nenhuma'} · **Buscas no RAG:** {r['rag_tentativas']} · **Reformulações:** {r['rag_reformulacoes'] or 'nenhuma'}\n",
                   "**Ferramentas MCP:**\n"]
        for f in r["ferramentas"]:
            partes.append(f"- `{f['ferramenta']}` {json.dumps(f['argumentos'], ensure_ascii=False)} → {f['status']}")
        partes.append("\n**Fontes recuperadas:**\n" + ("\n".join(f"- {c}" for c in r["fontes"]) or "- nenhuma"))
        partes.append(f"\n**Resposta final:**\n\n{r['resposta_final'] or '(sem resposta)'}\n\n---\n")
    return "\n".join(partes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", help="casos separados por vírgula, como 04,07")
    parser.add_argument("--pausa", type=float, default=10, help="segundos entre os casos")
    args = parser.parse_args()
    ids = set(args.ids.split(",")) if args.ids else None

    dados = asyncio.run(rodar(ids, args.pausa))
    RESULTADOS.mkdir(exist_ok=True)
    (RESULTADOS / "resultados_casos.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (RESULTADOS / "resultados_casos.md").write_text(detalhado(dados), encoding="utf-8")

    readme = README.read_text(encoding="utf-8")
    if INICIO in readme and FIM in readme:
        antes, resto = readme.split(INICIO, 1)
        _, depois = resto.split(FIM, 1)
        README.write_text(f"{antes}{INICIO}\n{tabela(dados)}\n{FIM}{depois}", encoding="utf-8")
        print("\nREADME atualizado.")
    aprovados = sum(r["aprovado"] for r in dados["casos"])
    print(f"Taxa de acerto: {aprovados}/{len(dados['casos'])}")


if __name__ == "__main__":
    main()
