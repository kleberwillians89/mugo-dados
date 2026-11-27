# Inventario de migrations do Kanban

Este registro documenta o estado observado em 27 de novembro de 2026. Ele nao
autoriza reaplicacao, renumeracao ou reparo do ledger remoto.

## Colisoes historicas preservadas

- `20270107_000116_relationship_audiences.sql`
- `20270107_000116_task_multi_assignees.sql`
- `20270130_000164_client_final_approval_preset.sql`
- `20270130_000164_mugo_notice_disposition.sql`

Os SQLs acima permanecem inalterados. Os numeros logicos `000123` a `000129`
continuam reservados como lacunas historicas e nao devem ser reutilizados.

## Drift remoto observado

No projeto remoto auditado, as estruturas previstas pelas migrations `000089`,
`000096`, `000097` e `000159` estavam presentes, assim como os efeitos dos dois
arquivos `000164`. Entretanto, nao havia entradas correspondentes por nome ou
numero no ledger `supabase_migrations.schema_migrations` disponivel na
inspecao.

Consequentemente, a presenca estrutural nao comprova qual arquivo foi aplicado
nem permite reaplicar migrations com seguranca. Qualquer reconciliacao futura
deve comparar schema e hashes, registrar a decisao de operacao e permanecer
separada das migrations funcionais.
