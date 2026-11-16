# Backup do Mugoverso

Duas camadas, para nunca depender de um lugar só:

| Camada | O que cobre | Frequência | Guarda | Onde |
|---|---|---|---|---|
| Supabase (plano Pro) | banco | diário (~08h BRT) | 7 dias | Supabase |
| **Backup externo** (`.github/workflows/backup.yml`) | **banco + arquivos do Storage** | banco diário (02:17 BRT); arquivos aos domingos | **30 dias** | armazenamento privado da AURUM |

O backup do Supabase **não inclui os arquivos do Storage** (artes dos posts, Biblioteca, miniaturas). O backup
externo inclui.

## Regras de LGPD do backup

- **Finalidade:** só continuidade e recuperação de desastre. Backup não é usado para análise nem por IA.
- **Criptografia:** AES-256 (GPG simétrico) **antes** de sair do runner. Sem a `BACKUP_PASSPHRASE`, o arquivo é ilegível.
- **Local:** use **região São Paulo** (Google Cloud `southamerica-east1` ou AWS `sa-east-1`). Assim os dados ficam no
  Brasil e o backup não gera transferência internacional. No Cloudflare R2 não há região Brasil: se escolher R2,
  registre a transferência internacional (art. 33) no `docs/LGPD.md`.
- **Retenção:** cópias com mais de 30 dias são apagadas automaticamente a cada execução.
- **Exclusão a pedido do titular:** o dado sai do banco na hora. Nas cópias de segurança, ele some quando elas
  expiram: em até 7 dias no Supabase e 30 dias no backup externo. As cópias não são consultadas nesse período. Se
  houver restauração, os pedidos de exclusão já atendidos são reaplicados antes de liberar o acesso. Isso consta na
  Política de Privacidade.
- **Acesso:** só os donos da conta de armazenamento e quem tem a `BACKUP_PASSPHRASE`. O bucket deve ser
  **privado**, com acesso público desligado. A chave usada pelo GitHub só pode **gravar, listar e apagar** naquele bucket.
- **Log público:** o GitHub mostra só totais (bytes, quantidade de arquivos). Nunca nomes de arquivo nem conteúdo.
- **Repositório público:** o backup **nunca** fica no GitHub, nem como artifact.

## Configurar (uma vez)

### 1. Criar o armazenamento (escolha um)

**Google Cloud Storage (recomendado: São Paulo)**
1. console.cloud.google.com → Cloud Storage → Criar bucket `mugoverso-backup`, local **southamerica-east1**,
   classe Standard, **Impedir acesso público** ligado, controle de acesso **Uniforme**.
2. IAM → Contas de serviço → criar `backup-mugoverso` → no bucket, papel **Storage Object Admin** (só nesse bucket).
3. Chaves → Adicionar chave → JSON. O conteúdo do JSON vai no `RCLONE_CONFIG`:

```ini
[backup]
type = google cloud storage
bucket_policy_only = true
location = southamerica-east1
service_account_credentials = {"type":"service_account", ... cole o JSON inteiro em uma linha ...}
```

**Amazon S3 (São Paulo)**: bucket em `sa-east-1` com Block Public Access ligado e um usuário IAM com permissão só
nesse bucket:

```ini
[backup]
type = s3
provider = AWS
region = sa-east-1
access_key_id = ...
secret_access_key = ...
```

**Cloudflare R2**: bucket privado e um token R2 com "Object Read & Write" só nesse bucket:

```ini
[backup]
type = s3
provider = Cloudflare
endpoint = https://<ACCOUNT_ID>.r2.cloudflarestorage.com
access_key_id = ...
secret_access_key = ...
```

### 2. Segredos no GitHub (Settings → Secrets and variables → Actions)

| Segredo | Valor |
|---|---|
| `SUPABASE_DB_URL` | Supabase → **Connect** → *Session pooler* → URI, com a senha do banco no lugar de `[YOUR-PASSWORD]` |
| `BACKUP_PASSPHRASE` | senha longa (30+ caracteres). **Guarde também num cofre fora do GitHub** (ex.: gerenciador de senhas da empresa): sem ela, ninguém restaura |
| `RCLONE_CONFIG` | o bloco `[backup]` acima |
| `BACKUP_PATH` | `mugoverso-backup/prod` (nome do bucket e pasta) |

`MUGO_JOBS_ENV` já existe e fornece `SUPABASE_URL` e `SUPABASE_SERVICE_ROLE_KEY` para baixar os arquivos.

### 3. Primeira execução

Actions → **Backup externo** → Run workflow → `tudo`. Depois rode `teste-restauracao`. Se os dois ficarem verdes,
está funcionando.

## Restaurar

**Banco (perda de até 1 dia):**
1. Prefira primeiro o backup do próprio Supabase (Database → Backups → Restore), se o problema tiver menos de 7 dias.
2. Se não der: baixe o arquivo `banco/banco-AAAA-MM-DDTHHMMZ.dump.gpg` do bucket e rode:

```bash
gpg --decrypt banco-....dump.gpg > banco.dump
```

```bash
pg_restore --no-owner --no-privileges --clean --if-exists -d "<URI do projeto de destino>" banco.dump
```

   O ideal é restaurar num projeto Supabase **novo**, conferir e então apontar a plataforma para ele.
3. Reaplique os pedidos de exclusão de titulares atendidos depois da data do backup (registro em
   privacidade@mugoagencia.com.br).

**Arquivos:**

```bash
gpg --decrypt arquivos-....tar.gz.gpg | tar -xzf -
```

Isso gera a pasta `storage/<bucket>/...`. Reenvie para o Storage com o mesmo caminho, pelo painel ou pelo rclone.

## Teste de restauração

No dia 1º de cada mês, o workflow restaura o último dump num Postgres temporário e confere se as tabelas e as
empresas voltaram. Falha abre a issue "Job parado: teste-de-restauracao".
