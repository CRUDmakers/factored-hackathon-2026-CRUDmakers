# banking-cs-ai

Dados do Factored Datathon 2026 (bucket S3 `factored-datathon-2026-s3-157725502942-us-east-2-an`, região `us-east-2`, acesso somente leitura).

Os dados ficam em `data/`, que está no `.gitignore` e não vai para o git. As credenciais AWS devem ficar num `.env` local, que também está ignorado.

## Visão geral

- **Formato:** CSV
- **Volume:** 7.671 arquivos, cerca de 5,2 GB
- **Período:** 2023-06-17 a 2026-06-17 (1.097 dias)
- **Tabelas diárias:** particionadas como `data/<tabela>/year=YYYY/month=MM/day=DD/<tabela>_YYYYMMDD.csv`, com um arquivo por dia
- **Dimensões:** um CSV único na raiz de `data/`

O bucket também tem `data_backup_20260831/`, que não foi baixado. É uma cópia incompleta: não tem `call_transcripts` nem `satisfaction_surveys`, e `transactions` só vai até 2024-09-25.

## Tabelas

Os dados são de um banco fictício, o **Banco LATAM**, com clientes no México, na Colômbia e na Argentina. Os textos estão em espanhol e os valores aparecem em MXN, COP, ARS e USD.

### Tabelas diárias (fatos)

| Tabela | Arquivos | Tamanho | Período | Descrição |
|---|---|---|---|---|
| `digital_events` | 1.097 | 3.583 MB | 2023-06-17 → 2026-06-17 | Eventos de navegação no app/web, como login, pageview e erro, com sessão, dispositivo, IP e UTM |
| `transactions` | 1.097 | 771 MB | 2023-06-17 → 2026-06-17 | Transações (depósito, saque, transferência...) com valor na moeda original e em USD, canal, estabelecimento e flag/score de fraude |
| `campaign_sends` | 1.083 | 311 MB | 2023-07-01 → 2026-06-17 | Envio de cada campanha a cada cliente, com funil entregue → aberto → clicado → convertido e custo |
| `call_center_interactions` | 1.097 | 133 MB | 2023-06-17 → 2026-06-17 | Atendimentos (ligação, e-mail...), com motivo, duração, espera, resolução, escalonamento, sentimento e sotaque |
| `call_transcripts` | 1.097 | 131 MB | 2023-06-17 → 2026-06-17 | Texto das ligações (completo e separado por cliente/atendente), com palavras-chave, intenções, tópicos e sotaque detectado |
| `satisfaction_surveys` | 1.097 | 44 MB | 2023-06-17 → 2026-06-17 | Pesquisas CSAT/CES/NPS após o atendimento, com nota, respostas, comentário aberto e sentimento |
| `complaints` | 1.097 | 18 MB | 2023-06-17 → 2026-06-17 | Reclamações e solicitações, com categoria, prioridade, status, datas do ciclo de vida, SLA, resolução e compensação |

### Dimensões

| Tabela | Tamanho | Descrição |
|---|---|---|
| `products.csv` | 65 MB | Um registro por produto contratado pelo cliente (conta, cartão...), com saldo, limite, juros, status e dias de atraso |
| `customers.csv` | 45 MB | Cadastro de clientes, com dados pessoais, localização, segmento, score de crédito, renda e aceite de marketing |
| `daily_exchange_rates.csv` | 0,7 MB | Taxas de câmbio diárias entre MXN/COP/ARS e USD, com compra e venda |
| `service_agents.csv` | 0,2 MB | Atendentes, com sotaque nativo, país, tipo, senioridade, especialidade, CSAT médio e turno |
| `branches.csv` | 0,09 MB | Agências, com tipo, endereço, horário, caixas eletrônicos, guichês e coordenadas |
| `marketing_campaigns.csv` | 0,03 MB | Campanhas, com tipo, objetivo, produto promovido, segmento e país-alvo, datas, orçamento e conversão esperada |

## Colunas e exemplos

As 5 linhas de cada tabela foram copiadas do início do arquivo indicado. Textos longos foram cortados em 80 caracteres (…), e as quebras de linha viraram espaço.

### `branches`

Fonte: `data/branches.csv` · 22 colunas

| branch_id | branch_code | branch_name | branch_type | address | city | state | country | postal_code | geographic_zone | phone | email | opening_time | closing_time | has_atms | atm_count | has_teller_windows | teller_window_count | latitude | longitude | branch_opening_date | branch_status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SUC-98QOW3F1 | S0001 | Banco LATAM Tijuana Sur | Express | Avenida Insurgentes 760, Centro | Tijuana | Baja California | México | 22000 | Urbana | +54 14 4257 9928 | sucursal0001@bancolatam.com | 09:30:00 | 17:30:00 | True | 5 | True | 12 | -0.0443619 | 0.0738601 | 1997-02-28 | Active |
| SUC-3DCC91G4 | S0002 | Banco LATAM Guadalajara Centro | Premium | Calzada Las Américas 345, Centro | Guadalajara | Jalisco | México | 44100 | Urbana | +54 91 6925 4150 | sucursal0002@bancolatam.com | 08:00:00 | 17:00:00 | True | 7 | True | 6 | 20.7143137 | -103.2525557 | 2000-06-11 | Active |
| SUC-COPO2MJ8 | S0003 | Banco LATAM Puebla 3 | Express | Camino Morelos 380, Centro | Puebla | Puebla | México | 72000 | Urbana | +54 92 4598 6313 | sucursal0003@bancolatam.com | 08:00:00 | 17:30:00 | True | 8 | True | 3 | 0.0610092 | -0.019767 | 1992-12-20 | Active |
| SUC-HVN55QJQ | S0004 | Banco LATAM Querétaro 4 | Express | Camino Revolución 672, Centro | Querétaro | Querétaro | México | 76000 | Urbana | +54 28 9348 9085 | sucursal0004@bancolatam.com | 08:00:00 | 17:00:00 | True | 8 | True | 4 | -0.0694317 | -0.0680036 | 2020-07-11 | Active |
| SUC-JYU0POJ9 | S0005 | Banco LATAM Puebla Centro | Express | Andador Carranza 480, Centro | Puebla | Puebla | México | 72000 | Urbana | +54 31 8433 1053 | sucursal0005@bancolatam.com | 09:00:00 | 20:00:00 | True | 8 | True | 5 | 0.0015363 | -0.0787178 | 2018-01-18 | Active |

### `call_center_interactions`

Fonte: `data/call_center_interactions/year=2023/month=06/day=17/call_center_interactions_20230617.csv` · 21 colunas

| interaction_id | interaction_date | process_date | customer_id | agent_id | interaction_type | channel | contact_reason | reason_category | duration_seconds | wait_time_seconds | was_resolved | requires_followup | detected_sentiment | sentiment_score | customer_detected_accent | agent_used_accent | was_escalated | mentioned_products | has_transcript | has_recording |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| INT-8LKPPFGAVR5FA7R3 | 2023-06-17 18:00:48 | 2023-06-17 | CLI-EBVG034XZPFT | AGT-HHYX8OE9JF | Inbound Call | Phone | Transaccional | Transaccional | 250.0 | 179.0 | True | False | Neutral | -0.28 | argentine | argentine | False |  | False | True |
| INT-R2TSE2WKP7HVN55Q | 2023-06-18 06:10:40 | 2023-06-17 | CLI-C46C63F54F0A | AGT-7CQYEF4L7J | Inbound Call | Phone | Comercial | Comercial | 545.0 | 186.0 | True | False | Neutral | -0.17 | mexican | mexican | False | PRD-LWE7ZI313MSF,PRD-2DZJYU0POJ9N,PRD-4FGYV9I6WVAN | True | True |
| INT-88K2QTZJ4NY5ILYX | 2023-06-18 03:38:17 | 2023-06-17 | CLI-ZOGX29P6Q6JB | AGT-3SCBQBHAUJ | Email | Email | Retención | Retención |  |  | True | False | Neutral | 0.29 | mexican | colombian | False |  | False | False |
| INT-3NJ03R8EHVW50EXS | 2023-06-17 17:03:11 | 2023-06-17 | CLI-XSM2WVAZ48IT | AGT-QZBFN7LRWT | Inbound Call | Phone | Comercial | Comercial | 605.0 | 149.0 | True | False | Muy Negativo | -0.76 | argentine | mexican | False |  | False | True |
| INT-VD5UPMZN0TANX443 | 2023-06-17 08:20:20 | 2023-06-17 | CLI-X00N9TOHD534 | AGT-1SD8N8Y4VV | Inbound Call | Phone | Queja | Queja | 603.0 | 119.0 | True | False | Positivo | 0.65 |  |  | False |  | False | True |

### `call_transcripts`

Fonte: `data/call_transcripts/year=2023/month=06/day=17/call_transcripts_20230617.csv` · 18 colunas

| transcript_id | interaction_id | process_date | customer_id | agent_id | full_text | customer_text | agent_text | detected_language | detected_accent | accent_confidence | detected_keywords | mentioned_entities | detected_intents | main_topics | transcription_model | audio_quality | duration_seconds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TRS-PPFGAVR5FA7R3DCC91G4 | INT-R2TSE2WKP7HVN55Q | 2023-06-17 | CLI-C46C63F54F0A | AGT-7CQYEF4L7J | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta … | Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorro… | Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. S… | es | mexican |  | banco, cuenta, servicio | {"account_numbers": 0, "dates": 0, "amounts": 0, "products": "Cuenta Ahorro"} | consulta_general | Comercial | Whisper v3 | High | 545.0 |
| TRS-DD79XNL6Q5DZNKOUR81B | INT-ERY0VKHXAEWUJQSW | 2023-06-17 | CLI-RTCOQFG4LA8Q | AGT-67FCNFADT1 | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta … | Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorro… | Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. S… | es | argentine | 0.76 | cuenta, banco | {"account_numbers": 0, "dates": 0, "amounts": 1, "products": "Tarjeta Crédito"} | consulta_general | Queja | AWS Transcribe | High | 470.0 |
| TRS-E7ZI313MSF2DZJYU0POJ | INT-HC9ALVKI68EJ8HPG | 2023-06-17 | CLI-N344OED0JO0L | AGT-LTX82QBP86 | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. Ag… | Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. | Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es … | es |  | 0.9 | cuenta, banco | {"account_numbers": 0, "dates": 1, "amounts": 2, "products": null} | consulta_general | Queja | AWS Transcribe | Medium | 420.0 |
| TRS-H4DZT88K2QTZJ4NY5ILY | INT-AP0TE0VSZWQTWR8S | 2023-06-17 | CLI-XH0KSNXXSM0P | AGT-O8KA4K5V2R | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. Ag… | Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. | Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es … | es | mexican | 0.93 | banco, cuenta, servicio | {"account_numbers": 0, "dates": 1, "amounts": 0, "products": null} | consulta_general | Técnico | Whisper v3 | High |  |
| TRS-0P221BIAHJQVK8HE3NCE | INT-5X2T33QTKLKB4CNR | 2023-06-17 | CLI-FFFXXSRASE9S | AGT-HQP1WC8P45 | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. Ag… | Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. | Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es … | es | colombian |  | banco, servicio | {"account_numbers": 0, "dates": 1, "amounts": 0, "products": null} | consulta_general | Producto | Google STT | High | 198.0 |

### `campaign_sends`

Fonte: `data/campaign_sends/year=2023/month=07/day=01/campaign_sends_20230701.csv` · 22 colunas

| send_id | send_date | process_date | campaign_id | customer_id | send_channel | template_used | subject | send_status | was_delivered | was_opened | open_date | was_clicked | click_date | click_count | had_conversion | conversion_date | conversion_value | open_device | open_country | failure_reason | send_cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SND-YC33ULTQJZDJTMVKP18A | 2023-07-01 14:01:33 | 2023-07-01 | CMP-7SE3FL9JKMZE | CLI-0YQ44QPQ77DX | Email |  | ¡Oferta especial en Tarjeta Crédito! | Sent | True | False |  | False |  |  | False |  |  |  |  |  | 0.0011 |
| SND-9XO7BR2TSE2WKP7HVN55 | 2023-07-01 13:37:40 | 2023-07-01 | CMP-7SE3FL9JKMZE | CLI-PFYINQ8JMS43 | Email | template_CMP-7SE3FL9JKMZE_3 | ¡Oferta especial en Tarjeta Crédito! | Sent | True | False |  | False |  |  | False |  |  |  |  |  | 0.0016 |
| SND-U0POJ9N4FGYV9I6WVANL | 2023-07-01 09:18:35 | 2023-07-01 | CMP-7SE3FL9JKMZE | CLI-X5N59QU30KGC | Email | template_CMP-7SE3FL9JKMZE_1 | ¡Oferta especial en Tarjeta Crédito! | Sent | True | True | 2023-07-02 12:12:02 | False |  |  | False |  |  | Tablet | Colombia |  |  |
| SND-3H2RR4HJ9VF7JQ7BZNFI | 2023-07-01 06:42:32 | 2023-07-01 | CMP-7SE3FL9JKMZE | CLI-WU2FEYX344UB | Email | template_CMP-7SE3FL9JKMZE_1 | ¡Oferta especial en Tarjeta Crédito! | Sent | True | False |  | False |  |  | False |  |  |  |  |  | 0.0085 |
| SND-XKHST63FFGQOZ3ECV86G | 2023-07-01 14:20:07 | 2023-07-01 | CMP-7SE3FL9JKMZE | CLI-ELS8YZHEDC5B | Email | template_CMP-7SE3FL9JKMZE_1 | ¡Oferta especial en Tarjeta Crédito! | Sent | True | False |  | False |  |  | False |  |  |  |  |  | 0.0016 |

### `complaints`

Fonte: `data/complaints/year=2023/month=06/day=17/complaints_20230617.csv` · 27 colunas

| complaint_id | creation_date | process_date | customer_id | case_type | category | subcategory | reception_channel | affected_product_id | related_branch_id | origin_interaction_id | description | claimed_amount | currency | priority | status | assigned_agent_id | assignment_date | first_response_date | resolution_date | closing_date | sla_breached | resolution_days | resolution | compensation_granted | resolution_satisfaction | is_repeat_complainer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CMP-J7LT0TPC5YC33ULTQJZD | 2023-06-17 16:54:58 | 2023-06-17 | CLI-6TXMFGPFFTZG | Complaint | Transactions | Cargo no reconocido | Email |  | SUC-H24HUACK |  | Queja relacionada con transactions | 513.79 | COP | Medium | Open |  |  |  |  |  | True |  |  |  |  | False |
| CMP-P7HVN55QJQFLDZ4HRU55 | 2023-06-17 15:37:40 | 2023-06-17 | CLI-PFYINQ8JMS43 | Claim | Transactions | Cargo no reconocido | Email | PRD-ML7YZHXJWUCA | SUC-DG6C9C1K |  | Queja relacionada con transactions | 4948.14 | COP | Medium | Resolved | AGT-B69BF4590M | 2023-06-17 23:37:40 | 2023-06-18 03:37:40 | 2023-07-13 15:37:40 |  | False | 26.0 | Se brindó explicación detallada al cliente y se resolvió la situación. | 457.44 |  | False |
| CMP-JSJ0B0XVTB2VY3H2RR4H | 2023-06-17 08:07:05 | 2023-06-17 | CLI-5B1TIWCXY0U0 | Suggestion | Technical | Problema con app | Branch |  |  |  | Queja relacionada con technical |  |  | Low | In Process | AGT-OH0WV42QJM | 2023-06-18 04:07:05 | 2023-06-18 18:07:05 |  |  | True |  |  |  |  | False |
| CMP-74XKHST63FFGQOZ3ECV8 | 2023-06-18 05:25:10 | 2023-06-17 | CLI-7D9HFKZPAO82 | Complaint | Branch | Atención en sucursal | Call Center | PRD-6W9PH9FVWZP4 | SUC-JGB6PK8R |  | Queja relacionada con branch |  |  | High | Open |  |  |  |  |  | False |  |  |  |  | False |
| CMP-72Q2B1HXJ2IU22VEXKK1 | 2023-06-18 01:40:53 | 2023-06-17 | CLI-737470INRZYR | Complaint | Service |  | App | PRD-84KOGPJBV6A5 |  |  | Queja relacionada con service | 3931.15 | USD | Low | In Process | AGT-EBM3J7XZ6E | 2023-06-18 23:40:53 | 2023-06-20 22:40:53 |  |  | False |  |  |  |  | False |

### `customers`

Fonte: `data/customers.csv` · 27 colunas

| customer_id | document_number | document_type | first_name | last_name | date_of_birth | gender | email | mobile_phone | landline_phone | address | city | state | country | postal_code | detected_accent | segment | credit_score | estimated_monthly_income | occupation | marital_status | education_level | registration_date | registration_branch_id | customer_status | last_updated | accepts_marketing |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CLI-G4X2AMVD62NR | G8637940 | Pasaporte | Samuel Andrés | Díaz Pérez | 1967-06-18 | M | samueldiaz@protonmail.com | +57 315 564 6977 | +57 4 314 5374 | Calle 433 #4-21, Barrio Bocagrande | Cartagena | Bolívar | Colombia |  | colombian | Plus | 701.0 | 24678431.94 | Administrative | Married | University | 2021-07-30 05:39:39 | SUC-7R3DCC91 | Active | 2021-08-15 05:39:39 | False |
| CLI-F2DZJYU0POJ9 | 42388496 | DNI | Javier | Campos Mendoza | 1976-04-16 | M | jcampos@gmail.com | +54 9 31 8433 1053 | +54 44 9201 3927 | Circuito Chapultepec 906, Centro | Guadalajara | Jalisco | México | 44100 | mexican | Basic | 576.0 |  | Homemaker | Single |  | 2022-12-09 13:10:47 | SUC-7ZI313MS | Active | 2023-05-15 13:10:47 | True |
| CLI-8WU28O74XKHS | 89638346 | DNI | Alejandro Catalina | Hernández Rojas | 1995-02-09 | O | alejandro.hernandez827@outlook.com | +54 9 95 8062 6804 |  | Privada Los Pinos 487, Centro | Guadalajara | Jalisco | México | 44100 |  | Basic | 657.0 | 28495.4 | Teacher | Divorced |  | 2024-04-06 16:26:17 | SUC-48CL872M | Active | 2025-01-12 16:26:17 | True |
| CLI-IU5Y26LO84W8 | 26064746 | DNI | José | Morales Flores | 1948-06-05 | O | jose.morales@live.com | +54 9 95 9565 6183 |  | Circuito Zaragoza 219, Centro | Puebla | Puebla | México | 72000 | mexican | Basic | 598.0 | 37284.11 | Employee |  | High School | 2024-09-10 17:43:08 | SUC-5AYKJQ2L | Inactive | 2024-10-15 17:43:08 | True |
| CLI-C4Z5FPK4YO51 | 12411824 | DNI | Jesús | Ruiz Herrera | 1985-07-22 | M | jesusruiz@yahoo.com | +54 9 50 6974 1653 |  | Paseo Insurgentes 684, Centro | Tijuana | Baja California | México | 22000 | mexican | Basic | 594.0 | 25257.93 | Lawyer | Married | Elementary | 2026-03-03 23:05:30 | SUC-UI9W1MT1 | Active | 2026-09-29 23:05:30 | True |

### `daily_exchange_rates`

Fonte: `data/daily_exchange_rates.csv` · 7 colunas

| date | source_currency | target_currency | exchange_rate | buy_rate | sell_rate | source |
|---|---|---|---|---|---|---|
| 2023-06-17 | MXN | USD | 0.059152 | 0.058841 | 0.059462 | Reuters |
| 2023-06-17 | COP | USD | 0.000247 | 0.000246 | 0.000249 | Central Bank |
| 2023-06-17 | ARS | USD | 0.002877 | 0.002837 | 0.002917 | Central Bank |
| 2023-06-17 | USD | MXN | 17.061535 | 16.970805 | 17.152265 | Central Bank |
| 2023-06-17 | USD | COP | 3954.982076 | 3915.220455 | 3994.743697 | Central Bank |

### `digital_events`

Fonte: `data/digital_events/year=2023/month=06/day=17/digital_events_20230617.csv` · 26 colunas

| event_id | event_date | process_date | customer_id | session_id | event_type | event_category | channel | platform | browser | app_version | page_url | page_title | action | element_id | product_id | event_value | duration_seconds | ip_address | ip_country | ip_city | is_mobile | referrer | utm_source | utm_medium | utm_campaign |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EVT-ZUVDGU5COPO2MJ8G9XO7 | 2023-06-17 08:52:08 | 2023-06-17 | CLI-X4M6ICRGTT9Z | SES-8QOW3F17I07NJ7LT0TPC5YC33ULT | Login | Authentication | Desktop Web | Linux | Chrome |  | /login | Iniciar Sesión |  | login_form |  |  |  | 142.150.185.148 | Colombia | Medellín | False |  |  |  |  |
| EVT-Z4HRU55OLDLG9JXO4VRR | 2023-06-17 08:52:47 | 2023-06-17 | CLI-X4M6ICRGTT9Z | SES-8QOW3F17I07NJ7LT0TPC5YC33ULT | PageView | Transaction | Desktop Web | Linux | Chrome |  | /payments | Pagar Servicios | initiate_payment | payment_form |  |  | 117.0 | 142.150.185.148 | Colombia | Medellín | False |  |  |  |  |
| EVT-4DZT88K2QTZJ4NY5ILYX | 2023-06-17 08:53:25 | 2023-06-17 | CLI-X4M6ICRGTT9Z | SES-8QOW3F17I07NJ7LT0TPC5YC33ULT | Login | Authentication | Desktop Web | Linux | Chrome |  | /login | Iniciar Sesión | login | login_form |  |  |  | 142.150.185.148 | Colombia | Medellín | False |  |  |  |  |
| EVT-HJQVK8HE3NCEV1NN2QS3 | 2023-06-17 08:53:32 | 2023-06-17 | CLI-X4M6ICRGTT9Z | SES-8QOW3F17I07NJ7LT0TPC5YC33ULT | Error | Transaction | Desktop Web | Linux | Chrome |  | /transactions | Mis Movimientos |  | transactions_page |  |  |  | 142.150.185.148 | Colombia |  | False |  |  |  |  |
| EVT-DZ9SGFYZKP5AYKJQ2LIU | 2023-06-17 08:54:07 | 2023-06-17 | CLI-X4M6ICRGTT9Z | SES-8QOW3F17I07NJ7LT0TPC5YC33ULT | Logout | Authentication | Desktop Web | Linux | Chrome |  | /login | Iniciar Sesión | login |  |  |  |  | 142.150.185.148 | Colombia | Medellín | False |  |  |  |  |

### `marketing_campaigns`

Fonte: `data/marketing_campaigns.csv` · 13 colunas

| campaign_id | campaign_name | description | campaign_type | campaign_objective | promoted_product | target_segment | target_country | start_date | end_date | budget | campaign_status | expected_conversion_rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CMP-8LKPPFGAVR5F | CMP_ACQ_CC_Jan2024_0001 | Campaña de acquisition para Tarjeta Crédito | Push | Acquisition | Tarjeta Crédito | Plus |  | 2024-01-12 | 2024-01-30 | 20732.43 | Completed | 1.86 |
| CMP-VKP18A283AMD | CMP_RET_SAV_Jul2025_0002 | Campaña de retention para Cuenta Ahorro | Email | Retention | Cuenta Ahorro |  | Mexico | 2025-07-31 | 2025-10-16 | 415555.31 | Completed | 9.47 |
| CMP-E2WKP7HVN55Q | CMP_XSL_SAV_Sep2024_0003 | Campaña de cross-sell para Cuenta Ahorro | Email | Cross-sell | Cuenta Ahorro | Student | Argentina | 2024-09-08 | 2024-09-22 | 411792.28 | Completed | 12.17 |
| CMP-G9JXO4VRRCA5 | CMP_RET_INV_May2024_0004 |  | Email | Retention | Inversión | Premium | Colombia | 2024-05-09 | 2024-07-31 | 195459.82 | Completed | 9.14 |
| CMP-4DZT88K2QTZJ | CMP_XSL_CHK_Apr2024_0005 |  | Email | Cross-sell | Cuenta Corriente |  |  | 2024-04-25 | 2024-05-22 | 301477.57 | Completed | 7.58 |

### `products`

Fonte: `data/products.csv` · 17 colunas

| product_id | customer_id | product_type | product_number | currency | current_balance | credit_limit | interest_rate | opening_date | expiration_date | opening_branch_id | product_status | opening_channel | has_linked_app | days_past_due | last_transaction_date | last_updated |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PRD-LT0TPC5YC33U | CLI-0Y0HOQ83ZSO4 | Cuenta Corriente | 4332181960 | COP | 13026299.27 |  | 0.32 | 2025-03-18 |  | SUC-E1VTXGEU | Active | Web | True |  | 2025-07-08 17:19:16 | 2025-12-25 00:57:58 |
| PRD-L6Q5DZNKOUR8 | CLI-E33FWYXNBBAQ | Tarjeta Débito | 4959310341316475 | USD | 961.65 |  | 0.0 | 2022-08-12 | 2025-08-11 | SUC-LQXENAY2 | Active | App | True |  | 2026-03-31 15:32:04 | 2023-01-20 12:56:06 |
| PRD-9JXO4VRRCA50 | CLI-5A1RQN103PRE | Tarjeta Crédito | 4672423884969653 | USD | 1173.14 | 8489.22 | 22.32 | 2018-12-27 | 2023-12-26 | SUC-TVNO2KL5 | Active | Branch | True | 0.0 | 2024-03-27 23:15:23 | 2019-11-12 03:59:31 |
| PRD-H2RR4HJ9VF7J | CLI-B2YEBULXPM7U | Tarjeta Débito | 4893252880957015 | USD | 789.55 |  | 0.0 | 2021-02-22 | 2024-02-22 | SUC-QZU3WHKF | Closed | Branch | False |  |  | 2021-04-24 02:06:32 |
| PRD-K8HE3NCEV1NN | CLI-IS8ZF6LQOPAC | Cuenta Corriente | 5098393010 | COP | 11151672.05 |  | 0.31 | 2022-03-02 |  | SUC-4BEKYT6U | Active | Branch | True |  | 2022-11-27 23:22:14 | 2022-10-17 02:34:47 |

### `satisfaction_surveys`

Fonte: `data/satisfaction_surveys/year=2023/month=06/day=17/satisfaction_surveys_20230617.csv` · 20 colunas

| survey_id | survey_date | process_date | interaction_id | customer_id | agent_id | survey_type | send_channel | main_score | nps_category | question_1_text | question_1_response | question_2_text | question_2_response | question_3_text | question_3_response | open_comments | comment_sentiment | response_time_hours | campaign_response_rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRV-07NJ7LT0TPC5YC33ULTQ | 2023-06-18 13:07:11 | 2023-06-17 | INT-D1ETMPV8U41ES9T0 | CLI-9S40YA6NZO28 | AGT-HHZLM4XXDJ | CSAT | Email | 3 |  |  |  |  |  | ¿Volvería a contactarnos por este canal? | 4.0 | Tardaron mucho en atenderme. | Negative | 8.76 |  |
| SRV-Q5DZNKOUR81B97XVBNEW | 2023-06-18 01:25:31 | 2023-06-17 | INT-69AIU8SDHRFQS9OL | CLI-QK4ROD4VZT9U | AGT-AQSH0YRHNO | CSAT | Email | 1 |  | ¿Cómo calificaría la atención brindada? | 3.0 | ¿El tiempo de espera fue aceptable? | 3.0 |  |  | Tardaron mucho en atenderme. | Negative | 10.14 | 20.13 |
| SRV-JXO4VRRCA50PPYRI3MUI | 2023-06-17 13:55:11 | 2023-06-17 | INT-S3TBIRRGQRO7O0Q4 | CLI-LSWRINEGQ2XU | AGT-9FZV5Z7FAG | CSAT | Email | 1 |  |  |  |  |  | ¿Volvería a contactarnos por este canal? | 4.0 |  |  | 7.7 | 22.54 |
| SRV-ILYXROPEODWG820JL0P2 | 2023-06-18 13:38:27 | 2023-06-17 | INT-C1WN6AWOKBD3XKUN | CLI-37A60TIP1FRH | AGT-ZGEFMIKG5G | CES | App | 2 |  |  | 1.0 |  |  |  |  | Tuve que esperar demasiado tiempo. | Negative | 17.87 | 19.95 |
| SRV-6J56GV2TU3NJ03R8EHVW | 2023-06-17 20:24:15 | 2023-06-17 | INT-2CEJ1CHB2H4YK0S7 | CLI-VZM51SINRKQS | AGT-N0G051WG35 | CSAT | SMS | 4 |  |  | 4.0 |  |  | ¿Volvería a contactarnos por este canal? | 1.0 | Muy satisfecho con el servicio. | Positive | 19.97 | 18.28 |

### `service_agents`

Fonte: `data/service_agents.csv` · 18 colunas

| agent_id | employee_code | first_name | last_name | email | phone | native_accent | country_of_origin | assigned_branch_id | agent_type | experience_level | languages | specialty | hire_date | avg_csat | total_monthly_interactions | agent_status | work_shift |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AGT-FGAVR5FA7R | E23396 | José | Morales Cruz | jose.morales95@bancogmail.com | +54 9 56 6635 5333 | mexican | Mexico | SUC-L138LKPP | In-Person | Mid-Senior | español | Ventas | 2025-09-11 | 4.43 | 691.0 | Active | Afternoon |
| AGT-5DZNKOUR81 | E51347 | Laura | Rodríguez Alvarez | lrodriguez@bancogmail.com | +54 9 38 6155 4483 | mexican | Mexico | SUC-D79XNL6Q | Hybrid | Senior | español | Retención | 2021-08-24 | 4.31 | 538.0 | Active | Morning |
| AGT-OJ9N4FGYV9 | E75612 | César | González Sánchez | cesargonzalez@bancolive.com | +54 9 24 5889 9317 | mexican | Mexico |  | Digital | Senior | español | Créditos | 2022-12-07 | 4.23 | 471.0 | Active | Morning |
| AGT-Q7BZNFI48C | E87110 | Manuel | Pérez Pérez | manuelperez@bancolive.com | +54 9 39 1117 2163 | mexican | Mexico |  | Phone | Mid-Senior | español, inglés |  | 2025-05-30 | 4.23 | 684.0 | Active | Afternoon |
| AGT-FA8XFVJ1ZU | E22224 | Gabriela Norma | Delgado Castillo | gabrieladelgado@bancooutlook.com | +54 9 63 8956 8886 | mexican | Mexico | SUC-Z3ECV86G | Phone | Specialist | español, inglés | Ventas | 2014-09-05 | 4.68 | 669.0 | Active | Morning |

### `transactions`

Fonte: `data/transactions/year=2023/month=06/day=17/transactions_20230617.csv` · 22 colunas

| transaction_id | transaction_date | process_date | product_id | customer_id | transaction_type | transaction_category | amount | currency | amount_usd | channel | branch_id | merchant_name | merchant_category | transaction_country | transaction_city | transaction_status | response_code | is_fraud | fraud_score | latitude | longitude |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-7I07NJ7LT0TPC5YC33UL | 2023-06-17 14:54:58 | 2023-06-17 | PRD-7EFOVFRUE3UQ | CLI-DRS40C485MAB | Deposit |  | 3695.53 | USD |  | Web |  |  |  | México | Monterrey | Approved | 00 | False | 0.89 |  |  |
| TRX-5COPO2MJ8G9XO7BR2TSE | 2023-06-17 14:17:51 | 2023-06-17 | PRD-HMGUZQXKE413 | CLI-RIO7AY0XG4MY | Withdrawal |  | 492.91 | USD |  | App |  |  |  | México | Tijuana | Approved | 00 | False | 25.02 |  |  |
| TRX-SF2DZJYU0POJ9N4FGYV9 | 2023-06-18 03:17:02 | 2023-06-17 | PRD-Z9VH3WRVEJP5 | CLI-NRCMAC93SWIH | Withdrawal |  | 1200383.22 | COP | 300.1 | POS |  |  |  | Argentina | Mendoza | Approved | 00 | False |  |  |  |
| TRX-VY3H2RR4HJ9VF7JQ7BZN | 2023-06-18 03:48:24 | 2023-06-17 | PRD-3963712YA073 | CLI-NRS8RG7UHLKI | Withdrawal |  | 10272.09 | ARS | 29.35 | App |  |  |  | Argentina | Buenos Aires | Approved | 00 | False | 1.74 |  |  |
| TRX-8HE3NCEV1NN2QS36J56G | 2023-06-17 07:08:37 | 2023-06-17 | PRD-S6CRGMNKOGAT | CLI-M1CZMRQ8CW3G | Transfer |  | 801.49 | USD |  | ATM | SUC-LQXENAY2 |  |  | México | Guadalajara | Approved | 00 | False |  |  |  |
