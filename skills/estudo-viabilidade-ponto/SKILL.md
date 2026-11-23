---
name: estudo-viabilidade-ponto
description: Emite o parecer técnico de um ponto comercial, com exclusividade territorial, metragem, tipo de ponto, concorrência no entorno e cuidados com o contrato de locação. Use quando o analista pedir para avaliar, analisar ou aprovar um imóvel, endereço ou ponto para uma unidade.
---

# Estudo de viabilidade de ponto

Fluxo: [Início] → (Receber endereço e metragem) → (Checar raio no MCP próprio) → (Validar o imóvel no MCP próprio) → (Pesquisar entorno no MCP da comunidade) → (Cuidados com o ponto e a locação via RAG) → (Parecer do comitê) → [Fim]

1. **Dados do imóvel.** Extraia logradouro, bairro, cidade, CEP, metragem útil (m²), tipo de ponto (rua, centro_comercial, shopping, galeria ou aeroporto) e modelo pretendido. Endereço de avenida ou rua sem menção a shopping é tipo `rua`. Se faltar bairro, cidade ou CEP, pergunte.
2. **Território (MCP próprio).** Chame `checar_raio_saturacao(bairro, cidade, cep)`.
3. **Imóvel (MCP próprio).** Chame `validar_especificacao_imovel(modelo, metragem, tipo_ponto)`.
4. **Entorno (MCP da comunidade).** Use a busca web do Exa (`web_search_exa`) com "cafeterias e padarias perto de <logradouro>, <bairro>, <cidade>" e, se couber, "estação de metrô faculdade supermercado perto de <logradouro>, <cidade>". Liste até cinco concorrentes ou polos de fluxo citados nos resultados. Se a ferramenta não estiver disponível ou falhar, diga que a análise de entorno ficou pendente e siga.
5. **Ponto e locação (RAG).** Chame `buscar_documentos` com `tipo_documento="GUIA"` e "escolha do ponto comercial, aluguel e licenças" e, depois, com `tipo_documento="LEI"` e "requisitos para renovação do contrato de locação comercial" (acrescente "shopping center" se o ponto for em shopping). Use os trechos para recomendar o prazo mínimo do contrato de locação.
6. **Parecer.** Responda com:
   - uma tabela Markdown `Critério | Resultado | Detalhe` com as linhas Exclusividade territorial, Metragem, Tipo de ponto e Entorno/concorrência;
   - o parecer **APROVADO** só se território e imóvel forem aprovados; caso contrário **REPROVADO**, listando cada impedimento em separado (territorial e técnico);
   - a seção **Cuidados com a locação**, com as fontes copiadas dos trechos, como (Lei nº 8.245/1991, Art. 51) e (Sebrae – Guia de Franquias, <seção>, p. <página>);
   - recomendações: outro ponto ou renegociação, quando reprovado.
