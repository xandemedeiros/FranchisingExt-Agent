import json
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.skills.provider import SkillsDirectoryProvider

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "skills"
UNITS_FILE = ROOT / "data" / "unidades_ativas.json"
LEADS_DB = ROOT / "data" / "franchising.db"

mcp = FastMCP("franquia")
# Cada pasta em skills/ também vira os recursos skill://{nome}/SKILL.md, como no servidor da disciplina.
mcp.add_provider(SkillsDirectoryProvider([SKILLS_DIR]))

# Parâmetros internos (simulados) de cada modelo da rede: investimento e médias de desempenho.
DADOS_MODELOS = {
    "quiosque": {"taxa_franquia": 30000.0, "instalacao": 60000.0, "capital_giro": 20000.0,
                 "faturamento_medio": 45000.0, "lucro_liq_pct": 0.15, "royalties_pct": 0.05, "fundo_prop_pct": 0.02},
    "loja_rua": {"taxa_franquia": 50000.0, "instalacao": 180000.0, "capital_giro": 50000.0,
                 "faturamento_medio": 110000.0, "lucro_liq_pct": 0.18, "royalties_pct": 0.05, "fundo_prop_pct": 0.02},
    "loja_shopping": {"taxa_franquia": 60000.0, "instalacao": 250000.0, "capital_giro": 70000.0,
                      "faturamento_medio": 160000.0, "lucro_liq_pct": 0.16, "royalties_pct": 0.05, "fundo_prop_pct": 0.02},
}

# Regras físicas por modelo, do manual de implantação (simulado) da rede.
REGRAS_IMOVEL = {
    "quiosque": {"min_m2": 6.0, "max_m2": 15.0, "tipos_permitidos": ["shopping", "galeria", "aeroporto"]},
    "loja_rua": {"min_m2": 80.0, "max_m2": 200.0, "tipos_permitidos": ["rua", "centro_comercial"]},
    "loja_shopping": {"min_m2": 40.0, "max_m2": 120.0, "tipos_permitidos": ["shopping"]},
}

APELIDOS = {
    "quiosque": "quiosque",
    "loja_rua": "loja_rua", "loja_de_rua": "loja_rua", "rua": "loja_rua",
    "loja_shopping": "loja_shopping", "loja_de_shopping": "loja_shopping", "loja_em_shopping": "loja_shopping",
}


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e com espaços e hífens trocados por _, como 'Loja de Rua' -> 'loja_de_rua'."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "_".join(sem_acento.lower().replace("-", " ").split())


def chave_modelo(modelo_franquia: str) -> str | None:
    """Converte o nome do modelo, em qualquer grafia, na chave interna ou None."""
    return APELIDOS.get(normalizar(modelo_franquia))


@mcp.tool()
def simular_payback_e_dre(modelo_franquia: str, capital_disponivel: float, aluguel_estimado: float) -> str:
    """Calcula o investimento total, a folga ou o déficit de capital, a DRE mensal sintética e o payback estimado em meses.

    Use para qualificar financeiramente um candidato. modelo_franquia: quiosque, loja_rua ou loja_shopping
    (aceita 'Loja de Rua', 'Loja de Shopping'). capital_disponivel: capital líquido total em reais, já somando
    sócios investidores. aluguel_estimado: aluguel mensal do ponto em reais (use 0 se desconhecido).
    """
    chave = chave_modelo(modelo_franquia)
    if chave is None:
        return json.dumps({"erro": f"Modelo '{modelo_franquia}' não reconhecido. Opções: quiosque, loja_rua, loja_shopping."}, ensure_ascii=False)
    if capital_disponivel < 0 or aluguel_estimado < 0:
        return json.dumps({"erro": "capital_disponivel e aluguel_estimado não podem ser negativos."}, ensure_ascii=False)

    mod = DADOS_MODELOS[chave]
    investimento_total = mod["taxa_franquia"] + mod["instalacao"] + mod["capital_giro"]
    saldo_capital = capital_disponivel - investimento_total

    faturamento = mod["faturamento_medio"]
    royalties = faturamento * mod["royalties_pct"]
    fundo_prop = faturamento * mod["fundo_prop_pct"]
    lucro_operacional = (faturamento * mod["lucro_liq_pct"]) - (aluguel_estimado * 0.5)

    payback_meses = (investimento_total / lucro_operacional) if lucro_operacional > 0 else -1
    ponto_equilibrio_bruto = (investimento_total / 24) / mod["lucro_liq_pct"] if mod["lucro_liq_pct"] > 0 else 0

    resultado = {
        "modelo": chave,
        "investimento_total_necessario": investimento_total,
        "composicao_investimento": {"taxa_franquia": mod["taxa_franquia"], "instalacao": mod["instalacao"], "capital_giro": mod["capital_giro"]},
        "capital_disponivel": capital_disponivel,
        "status_capital": "FOLGA" if saldo_capital >= 0 else "DEFICIT",
        "diferenca_capital": abs(saldo_capital),
        "dre_mensal_estimada": {
            "faturamento_bruto": faturamento,
            "royalties": royalties,
            "fundo_propagandistico": fundo_prop,
            "custo_aluguel_projetado": aluguel_estimado,
            "lucro_liquido_projetado": lucro_operacional,
        },
        "metricas_financeiras": {
            "payback_estimado_meses": round(payback_meses, 1),
            "ponto_equilibrio_mensal_estimado": round(ponto_equilibrio_bruto, 2),
        },
        "observacao": "Estimativa com os parâmetros médios (simulados) da rede. Não é promessa de rendimento.",
    }
    return json.dumps(resultado, ensure_ascii=False)


@mcp.tool()
def checar_raio_saturacao(bairro: str, cidade: str, cep: str) -> str:
    """Verifica se há conflito de exclusividade territorial com unidades ativas, em implantação ou reservadas.

    Compara, na mesma cidade, o prefixo de três dígitos do CEP e o bairro do ponto proposto com a base de unidades.
    Ex.: bairro='Bela Vista', cidade='São Paulo', cep='01310-100'.
    """
    base_unidades = json.loads(UNITS_FILE.read_text(encoding="utf-8"))
    cep_limpo = "".join(ch for ch in cep if ch.isdigit())[:3]
    if len(cep_limpo) < 3:
        return json.dumps({"erro": f"CEP '{cep}' inválido: informe ao menos os cinco primeiros dígitos."}, ensure_ascii=False)

    conflitos = []
    for un in base_unidades:
        if normalizar(un["cidade"]) == normalizar(cidade):
            if un["cep_prefixo"] == cep_limpo or normalizar(un["bairro"]) == normalizar(bairro):
                conflitos.append(un)

    viabilidade = len(conflitos) == 0
    return json.dumps({
        "local_solicitado": {"bairro": bairro, "cidade": cidade, "cep": cep},
        "territorio_disponivel": viabilidade,
        "unidades_conflitantes": conflitos,
        "parecer": "APROVADO: Zona de exclusividade desimpedida." if viabilidade
        else "REPROVADO: Conflito com raio de exclusividade de unidade existente.",
    }, ensure_ascii=False)


@mcp.tool()
def validar_especificacao_imovel(modelo_franquia: str, metragem_m2: float, tipo_ponto: str) -> str:
    """Valida se a metragem útil e o tipo de ponto do imóvel atendem ao manual de implantação do modelo.

    modelo_franquia: quiosque, loja_rua ou loja_shopping. metragem_m2: área útil em m².
    tipo_ponto: rua, centro_comercial, shopping, galeria ou aeroporto.
    """
    chave = chave_modelo(modelo_franquia)
    if chave is None:
        return json.dumps({"erro": f"Modelo '{modelo_franquia}' não possui regras cadastradas."}, ensure_ascii=False)

    spec = REGRAS_IMOVEL[chave]
    erros = []
    if metragem_m2 < spec["min_m2"]:
        erros.append(f"Metragem de {metragem_m2}m² abaixo do mínimo exigido de {spec['min_m2']}m².")
    elif metragem_m2 > spec["max_m2"]:
        erros.append(f"Metragem de {metragem_m2}m² acima do limite recomendado de {spec['max_m2']}m².")

    if normalizar(tipo_ponto) not in spec["tipos_permitidos"]:
        erros.append(f"Tipo de ponto '{tipo_ponto}' incompatível. Permitidos: {', '.join(spec['tipos_permitidos'])}.")

    return json.dumps({
        "modelo": chave,
        "metragem_avaliada": metragem_m2,
        "tipo_ponto_avaliado": tipo_ponto,
        "aprovado": len(erros) == 0,
        "inconformidades": erros,
    }, ensure_ascii=False)


@mcp.tool()
def carregar_skill(nome: str) -> str:
    """Carrega as instruções completas (SKILL.md) de uma skill pelo nome, como 'simulacao-investimento-franquia'."""
    path = SKILLS_DIR / nome / "SKILL.md"
    if not path.is_file() or path.resolve().parent.parent != SKILLS_DIR.resolve():
        disponiveis = ", ".join(sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md")))
        return f"erro: skill '{nome}' não existe. Disponíveis: {disponiveis}"
    return path.read_text(encoding="utf-8")


def conexao_leads() -> sqlite3.Connection:
    """Abre o banco de leads e cria a tabela na primeira vez."""
    LEADS_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(LEADS_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, criado_em TEXT, candidato TEXT, modelo TEXT,
        capital_disponivel REAL, parecer TEXT, observacao TEXT)""")
    return con


@mcp.tool()
def registrar_lead(candidato: str, modelo_franquia: str, capital_disponivel: float, parecer: str, observacao: str = "") -> str:
    """Grava no banco de leads o resultado de uma qualificação ou de um estudo de ponto.

    parecer: APROVADO, REPROVADO ou PENDENTE. Use só quando o consultor pedir para registrar o candidato.
    """
    parecer = parecer.upper().strip()
    if parecer not in {"APROVADO", "REPROVADO", "PENDENTE"}:
        return "erro: parecer deve ser APROVADO, REPROVADO ou PENDENTE"
    with conexao_leads() as con:
        cursor = con.execute(
            "INSERT INTO leads (criado_em, candidato, modelo, capital_disponivel, parecer, observacao) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), candidato, chave_modelo(modelo_franquia) or modelo_franquia, capital_disponivel, parecer, observacao),
        )
    return json.dumps({"registrado": True, "id": cursor.lastrowid}, ensure_ascii=False)


@mcp.tool()
def listar_leads(limite: int = 10) -> str:
    """Lista os leads registrados mais recentes, do mais novo para o mais antigo."""
    with conexao_leads() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (max(1, min(limite, 50)),)).fetchall()
    return json.dumps([dict(row) for row in rows], ensure_ascii=False)


@mcp.resource("franquia://modelos")
def modelos() -> str:
    """Parâmetros financeiros e regras físicas de cada modelo de franquia, em JSON."""
    return json.dumps({"financeiro": DADOS_MODELOS, "imovel": REGRAS_IMOVEL}, ensure_ascii=False, indent=2)


@mcp.resource("franquia://unidades")
def unidades() -> str:
    """Base de unidades ativas, em implantação e reservadas, com bairro, CEP e raio de exclusividade."""
    return UNITS_FILE.read_text(encoding="utf-8")


@mcp.prompt()
def parecer_ponto(endereco: str, metragem_m2: str, modelo_franquia: str) -> str:
    """Pede o estudo completo de viabilidade de um ponto comercial."""
    return (f"Analise o ponto em {endereco}, com {metragem_m2} m², para o modelo {modelo_franquia}. "
            "Siga a skill estudo-viabilidade-ponto e emita o parecer do comitê.")


if __name__ == "__main__":
    mcp.run(show_banner=False)
