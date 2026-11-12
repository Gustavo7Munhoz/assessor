# Etapa 8: juiz e gravações

## Decisão

Antes, a tool gravava antes do julgamento. Escolhemos Adiar: guardar as operações numa fila e gravar só com `choice == "apoiada"` e `noul >= 0.70`. Recusa ou falha do juiz descarta a fila.

Isso cobre `add_transaction`, `update_transaction`, `criar_evento`, `atualizar_evento` e `cancelar_evento`. O juiz recebe os argumentos e resultados das tools; o usuário recebe a confirmação depois da escrita. Cada fila confirma uma vez. Escrita no grafo sem turno identificado falha.

## Alternativas consideradas

- Interceptar barraria argumentos errados antes da tool, mas ainda não avaliaria a frase final. Outro avaliador acrescentaria uma chamada.
- Transacionar permitiria rollback, mas manteria conexão e travas abertas enquanto o juiz responde. Não resolveria sozinho os dois bancos.
- Compensar permitiria gravar imediatamente e desfazer na recusa. Descartamos porque a escrita inversa também pode falhar ou nem ocorrer após uma queda.

## Efeito no SRE

Adiar acrescenta validações e conexão de escrita na aprovação; na recusa, evita gravar. Não acrescenta modelo, mas envia mais evidências ao JEV. Interceptar com IA aumentaria latência, tokens e custo; compensar acrescentaria outra escrita nas recusas.

Recusa normal fica `ok`; falha do juiz ou da gravação, `erro`; bloqueio de entrada, `bloqueado`, sem contar como erro. Os limites continuam em p95 de 8 segundos e erro de 5%.

Não fizemos benchmark comparativo nem medimos o p95 do chat.

## Escopo, falhas e testes

A agenda usa MongoDB: `add_event` corresponde a `criar_evento`. Não existe `add_google_event`. `salvar_mensagem` mantém o histórico depois do juiz. CLI/MCP fora do chat continua gravando imediatamente; consultas leem o banco confirmado.

Uma queda antes da aprovação não deixa registros. Depois da aprovação, pode haver gravação parcial entre bancos; a resposta avisa desse risco. Queda após commit pode deixar dado salvo sem resposta. Reenviar o pedido pode duplicar lançamentos. A trava de conflitos da agenda vale apenas para o processo atual.

Passaram 46 testes locais simulados e 10 casos com PostgreSQL, MongoDB e JEV reais. Reproduzimos também o defeito antigo nas três operações obrigatórias. No novo: criação e evento ficaram 0→0 na recusa e 0→1 na aprovação; atualização ficou 80→80 e 80→95. Edição e cancelamento de eventos também passaram.


## Arquivos

Criados:

- `decisao_tecnica.md`

Modificados:

- `app/juiz.py`: fila, aprovação e tratamento de erros.
- `app/graph.py`: passagem do turno, evidências e status.
- `app/tools/financeiro.py`: escrita adiada, IDs e conferência do UPDATE.
- `app/tools/agenda.py`: escrita adiada e conferência de horários e conflitos.
