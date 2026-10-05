<div align="center">

# 🏦 Assistente LATAM

**Resolva a sua vida no banco só conversando.**

Um assistente com IA que consulta saldos, explica gastos, faz pagamentos e gera extratos — em português ou espanhol, com os dados reais da sua conta e sempre com a sua confirmação antes de mover dinheiro.

### [▶️ Experimente agora](https://factored-hackathon-2026-crud-makers.vercel.app/)

*Projeto do time **CRUDmakers** para o Factored AI & Data Hackathon 2026*

![Página inicial do Banco LATAM com o assistente aberto](docs/img/overview.png)

</div>

---

## 💡 O problema

Resolver qualquer coisa no banco costuma significar navegar por menus, procurar a tela certa ou esperar na fila do atendimento. Perguntas simples — *"minha compra foi aprovada?"*, *"quanto devo no cartão?"*, *"já paguei o aluguel este mês?"* — tomam tempo demais.

## ✨ A solução

O **Banco LATAM** é um internet banking de um banco fictício que atua no **México, Colômbia e Argentina**, com um assistente que entende o que você escreve e age por você. Em vez de procurar a função, você pede:

> *"Quais são os meus pagamentos previstos para este mês?"*
> *"Pague tudo."*

E pronto.

---

## 🚀 O que o assistente faz

| | Funcionalidade | Exemplo de pergunta |
|---|---|---|
| 💰 | **Saldos e cartões** — saldo de cada conta, fatura, limite disponível, dias em atraso e vencimento do cartão | *"Quanto devo no cartão final 4947?"* |
| 🧾 | **Movimentos** — últimas transações, busca por data, loja ou valor, e o motivo de uma compra recusada | *"Tenho alguma compra recusada recentemente? Por quê?"* |
| 💸 | **Transferências e contas** — transfere entre suas contas, paga a fatura do cartão e paga boletos | *"Quero pagar 100 COP da fatura do cartão final 6411"* |
| 📅 | **Pagamentos do mês** — descobre o que você paga todo mês (aluguel, internet, assinaturas), mostra o que já foi pago e o que falta, e paga tudo com uma única confirmação | *"Quais são os meus pagamentos previstos para este mês?"* |
| 📊 | **Análise de gastos** — resume para onde vai o seu dinheiro por mês, categoria e cartão, e dá dicas práticas para gastar menos | *"Para onde vai meu dinheiro e como gastar menos?"* |
| 📄 | **Extratos e relatórios** — gera na hora extrato em PDF, resumo de saldos, relatório de gastos, comprovantes e planilhas | *"Quero o extrato dos últimos 30 dias em PDF"* |
| 💱 | **Câmbio** — converte entre dólar e pesos mexicanos, colombianos e argentinos com a cotação do banco | *"Quanto são 100 dólares em pesos argentinos?"* |
| 🙋 | **Atendente humano** — cobrança desconhecida, negociação de dívida ou reclamação: o caso vai para uma pessoa com todo o contexto e um número de protocolo | *"Não reconheço essa cobrança"* |

Fala **português e espanhol** — dá até para misturar os dois.

---

## 📸 Veja funcionando

### Pagando todas as contas do mês de uma vez

O assistente lista o que já foi pago e o que ainda está em aberto. Ao pedir *"Pague tudo"*, ele mostra exatamente o que vai ser debitado e **espera a sua confirmação**.

![Assistente mostrando os pagamentos previstos e pedindo confirmação](docs/img/before_pay.png)

Depois de confirmar, cada pagamento é executado e conferido no banco, com o número de comprovante. O saldo da conta é atualizado na hora.

![Pagamentos aprovados com comprovantes](docs/img/after_pay.png)

### Saldos, pagamentos previstos e extrato em PDF

Perguntas do dia a dia respondidas em segundos — e o extrato pronto para baixar direto na conversa.

<p align="center">
  <img src="docs/img/pdf.png" alt="Conversa com saldos, pagamentos previstos e extrato em PDF" width="520">
</p>

---

## 🖥️ Além do chat

- **Início** — visão geral com patrimônio líquido, contas, cartões (com fatura, limite usado e alertas de atraso) e empréstimos, além de atalhos de um clique para as perguntas mais comuns.
- **Meus gastos** — tendência mês a mês, gastos por categoria e por cartão, com filtros de período, download em CSV e o botão **"Analisar com IA"**, que leva a análise direto para o assistente.
- **Guia do assistente** — explica o que ele sabe fazer, como os pagamentos são confirmados e quando ele chama um atendente.
- **Português ou espanhol** — toda a interface muda de idioma com um clique.

---

## 🔒 Seguro por design

Um assistente que mexe com dinheiro precisa ser confiável. Por isso:

1. **Prévia** — o banco verifica saldo, limites e destino sem mover dinheiro.
2. **Você confirma** — valor, origem e saldo depois aparecem na tela; nada é debitado sem o seu *Confirmar*.
3. **Execução única** — o pagamento roda uma vez só, mesmo se você clicar duas vezes.
4. **Comprovante** — o assistente confere no banco antes de dizer que deu certo.

Além disso, os valores sempre vêm do banco (nunca são "inventados" pela IA), os números de cartão aparecem mascarados, a sessão expira sozinha em 15 minutos e casos sensíveis — como suspeita de fraude ou valores acima do limite — vão automaticamente para um atendente humano.

### Os números

Testamos o assistente em **262 cenários** (perguntas comuns, pedidos ambíguos, tentativas de manipulação, falhas do banco, mistura de idiomas), cada um rodado 3 vezes:

| | |
|---|---|
| ✅ Pedidos resolvidos com segurança | **99,3%** |
| 🛡️ Operações inseguras | **0** de 786 |
| 🙋 Casos que deveriam ir para um atendente e não foram | **0** de 192 |

Para comparação, o mesmo modelo de IA **sem** as nossas regras de segurança executou 140 operações inseguras nos mesmos testes.

---

## 🧪 Como testar

1. Acesse **[factored-hackathon-2026-crud-makers.vercel.app](https://factored-hackathon-2026-crud-makers.vercel.app/)**.
2. Na tela de login, escolha um dos **clientes de teste** — eles entram com um clique. Recomendamos a **Marta Sánchez Romero** (Colômbia), que tem contas, cartões, empréstimo e pagamentos recorrentes.
3. Clique em **Falar com o assistente** e experimente uma das sugestões, ou escreva do seu jeito.

> Todos os dados são fictícios, do dataset do Factored Datathon 2026. Nenhum dinheiro real é movimentado.

---

## 🛠️ Por trás dos panos

<details>
<summary>Para quem tem curiosidade técnica</summary>

<br>

O sistema tem três partes:

- **Frontend** — React, com a interface do banco e o chat do assistente.
- **API do banco** — Node.js + PostgreSQL, carregada com ~3 anos de dados do banco fictício (clientes, produtos, transações e câmbio). Simula pagamentos, agendamentos e relatórios.
- **Backend de IA** — Python com LangGraph. Um classificador decide se o pedido está no escopo, o modelo de linguagem conversa e escolhe as ferramentas, e um motor de regras em código garante a segurança das operações.

Documentação detalhada:

- [Guia do assistente (exemplos reais e resultados)](ai-backend/ASSISTANT_GUIDE.md)
- [Arquitetura do backend de IA](ai-backend/ARCHITECTURE.md)
- [API do banco](backend/README.md) · [Frontend](frontend/README.md)
- [Dicionário de dados](docs/data_dictionary.md) · [Engenharia de dados](docs/data_engineering.md)

</details>

---

<div align="center">

Feito com ☕ pelo time **CRUDmakers** · Factored AI & Data Hackathon 2026

</div>
