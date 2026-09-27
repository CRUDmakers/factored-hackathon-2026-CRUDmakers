# Escopo

**Customer Service/Assistent - Transactional**

Como usuário do banco gostaria de conseguir resolver todos meus problemas de maneira eficiente apenas conversando com um chat operacional.

## Features:

1. **Visualizar quanto de dinheiro tem** (cartão de crédito fatura, cartão de crédito limite, cartão de crédito fatura – limite, dinheiro da conta corrente)

2. **Fazer Transações** (pagar contas: boleto, pix, transferência (verificar de acordo com os países do banco), fazer pix, transferências em geral).

3. **Agendamento de transações:** tornar possível pagamentos automáticos previstos

4. **Consultar a conversão para transações internacionais** `daily_exchange_rates`

## Extra:

 5. **Checar status de pagamentos** (se foi concluído, se foi negado (e se foi negado porque)

 6. **Checar últimas transações e gerar relatório**

 7. `transaction_category`: Conseguimos saber a categoria do que gastamos e gerar o relatorio também, fazer um tracer do que estamos gastando, do que podemos gerar, um controle financeiro

 8. **Checar What the customer asks:** "Where did this withdrawal happen?": the ATM or branch

 9. **What the customer asks:** "What's this adjustment on my loan?" **Data used:** Transaction type + product type

10. **What the customer asks:** "When does my card expire?" / "What's my interest rate?" **Data used:** expiration_date, interest_rate

## Extra: Investimento

* **Frontend:** Responsável por reproduzir a parte visual do banco.

* **Backend 1:** Responsável pela leitura de dados e manipulações do banco (simular transações...)

* **Backend 2:** IA aplicada para responder e gerar as respostas