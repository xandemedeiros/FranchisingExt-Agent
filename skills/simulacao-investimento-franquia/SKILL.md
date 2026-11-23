---
name: simulacao-investimento-franquia
description: Qualifica financeiramente um candidato a franqueado, com investimento, capital de giro, DRE, payback, orientações do Sebrae e próximos passos legais. Use sempre que o consultor pedir simulação completa, qualificação, análise de capital ou viabilidade financeira de um candidato, mesmo sem o valor do aluguel.
---

# Simulação de investimento de franquia

Fluxo: [Início] → (Coletar perfil e capital) → (Simular DRE/payback no MCP) → (Orientações do Sebrae via RAG) → (Base legal da COF via RAG) → (Relatório e parecer) → [Fim]

1. **Coleta de perfil.** Identifique o modelo de interesse (quiosque, loja_rua ou loja_shopping) e o capital líquido próprio, somando o aporte de sócios investidores, se houver. Só pergunte se faltar o modelo ou o capital. Não pergunte o nome do candidato: se não vier, chame-o de "candidato". Se o aluguel não for informado, use 0 e avise que a DRE ficou sem aluguel.
2. **Cálculo (MCP próprio).** Chame `simular_payback_e_dre` com o modelo, o capital total e o aluguel. Se a ferramenta devolver `erro`, explique e peça o dado correto.
3. **Orientações do Sebrae (RAG).** Chame `buscar_documentos` com `tipo_documento="GUIA"` e uma consulta sobre "capital de giro, investimento inicial e prazo de retorno da franquia". Use os trechos para comentar o resultado: se há reserva de capital de giro além da taxa e da instalação e se o prazo do contrato deve superar o payback estimado.
4. **Base legal (RAG).** Chame `buscar_documentos` com `tipo_documento="LEI"` e a consulta "prazo de entrega da Circular de Oferta de Franquia antes da assinatura do contrato ou do pagamento de taxa". Use o trecho para orientar o próximo passo do consultor.
5. **Relatório.** Responda com:
   - uma tabela Markdown `Item | Valor` com taxa de franquia, instalação, capital de giro, investimento total, capital disponível e folga ou déficit;
   - uma tabela `Linha da DRE | Valor mensal` com faturamento, royalties, fundo de propaganda, aluguel e lucro líquido projetado, e o payback estimado em meses;
   - o parecer: **VIÁVEL** (folga) ou **NÃO VIÁVEL NO MOMENTO** (déficit), com a parcela complementar quando houver déficit;
   - a seção **Orientações e próximos passos**, com uma frase do Sebrae e uma da Lei, cada uma com a fonte copiada do trecho, como (Sebrae – Guia de Franquias, <seção>, p. <página>) e (Lei nº 13.966/2019, Art. 2º, § 1º).

Nunca apresente payback ou lucro como garantia: são estimativas com as médias da rede.
