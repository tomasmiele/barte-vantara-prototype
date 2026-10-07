# Protótipo de contas a receber

Este projeto compara os títulos dos arquivos **01** e **02** com os créditos do extrato **03**. Ele mostra no terminal quais pagamentos foram localizados, se chegaram até o vencimento e se o valor recebido foi igual, menor ou maior que o valor do título. Também grava o resultado em CSV. Os arquivos de entrada são apenas lidos; a execução não altera os CSVs originais.

## O que é necessário

- **Python 3.10 ou superior** instalado e disponível no terminal. Para conferir, execute `python3 --version` no macOS/Linux ou `py -3 --version` no Windows.
- A pasta deste projeto e o **pacote de dados** com os três CSVs descritos abaixo. A pasta `data/` está no `.gitignore`: quem baixar somente o repositório precisará obter o pacote separadamente.
- Um terminal (Terminal no macOS/Linux ou PowerShell no Windows).

Não há dependências externas para instalar com `pip`. A execução é local: **não exige conta, chave de API, arquivo `.env` nem acesso a Lovable, n8n ou Replit**. O Git só é necessário se você optar por baixar o projeto com `git clone`.

## Preparação, passo a passo

1. Obtenha o projeto por download ou, se tiver Git instalado, execute:

   ```sh
   git clone https://github.com/tomasmiele/barte-vantara-prototype.git
   cd barte-vantara-prototype
   ```

   Se baixou um ZIP, extraia-o e abra um terminal na pasta extraída, onde está `prototipo_contas_a_receber.py`.

2. Confirme a versão do Python com o comando indicado em **O que é necessário**. Se o comando não for reconhecido, instale Python 3.10 ou superior e abra o terminal novamente.

3. Crie a pasta `data/` na raiz do projeto, caso ela ainda não exista. Copie para ela os arquivos do pacote de dados, mantendo seus nomes:

   ```text
   barte-vantara-prototype/
   ├── prototipo_contas_a_receber.py
   └── data/
       ├── 01_contas_a_receber_protheus_jul2026.csv
       ├── 02_titulos_unidade_norte_omie_jul2026.csv
       └── 03_extrato_bancario_jul2026.csv
   ```

   O script procura **exatamente um CSV** começando com `01`, um com `02` e um com `03` na pasta indicada. O arquivo `04_caixa_de_entrada_contas_a_pagar.txt`, se estiver no pacote, não é usado neste protótipo.

## Como executar

Na raiz do projeto, rode:

```sh
python3 prototipo_contas_a_receber.py
```

No Windows, use:

```powershell
py -3 prototipo_contas_a_receber.py
```

Por padrão, o programa lê a pasta `data/` ao lado do script. Para usar outra pasta com os três CSVs, informe o caminho:

```sh
python3 prototipo_contas_a_receber.py --data-dir "/caminho/para/o/data-pack"
```

No Windows, substitua `python3` por `py -3` e use o caminho da pasta no seu computador. O relatório aparece no terminal e em `data/resultado_contas_a_receber.csv`. Para escolher outro destino, passe `--output "/caminho/resultado.csv"`. O programa substitui apenas o CSV de resultado em execuções seguintes; os arquivos 01, 02 e 03 não podem ser usados como destino. Se faltar algum CSV ou coluna obrigatória, ele mostra uma mensagem de erro no terminal.

O CSV tem uma linha por título classificado, inclusive os não localizados e os possíveis pagamentos. As colunas incluem `categoria`, `referencias`, `cliente`, `cnpj`, `nosso_numero`, `valor_titulo`, `vencimento`, `valor_recebido`, `data_pagamento`, `linhas_extrato`, `criterio`, `valor_faltante`, `valor_excedente`, `observacao` e `detalhes`. Os valores numéricos usam ponto decimal, as datas usam `AAAA-MM-DD` e os campos de pagamento ficam vazios quando não há crédito localizado. O arquivo usa UTF-8 com BOM e ponto e vírgula como separador para facilitar a abertura em planilhas. A pasta `data/`, incluindo esse resultado, não é versionada pelo Git.

## Como ler a saída

O programa imprime uma seção para cada categoria, com a quantidade entre parênteses e as linhas correspondentes:

- `PAGAMENTO EM DIA` e `PAGAMENTO ATRASADO`: crédito do mesmo valor, até o vencimento ou depois dele.
- `PAGAMENTO INCOMPLETO`: crédito menor que o valor devido; a linha mostra `faltam=...` e, quando aplicável, `crédito após vencimento`.
- `PAGAMENTO MAIOR EM DIA` e `PAGAMENTO MAIOR ATRASADO`: crédito maior que o valor devido; a linha mostra `excedente=...`.
- `PAGAMENTO NÃO LOCALIZADO`: título sem correspondência aceita no extrato.
- `POSSÍVEL PAGAMENTO EM DIA`, `POSSÍVEL PAGAMENTO ATRASADO` e `POSSÍVEL PAGAMENTO INCOMPLETO`: correspondência feita somente pelo valor, que exige conferência humana. No caso incompleto, a linha mostra o valor faltante.

Uma data igual ao vencimento conta como pagamento em dia. As referências `01:13` e `02:4`, por exemplo, indicam o arquivo de origem e o número da linha no CSV. `linha do extrato=13` aponta para a linha do arquivo 03. O `nosso_numero` é exibido sem zeros à esquerda. Uma linha como `01:10 + 02:2` representa o mesmo título encontrado nos dois arquivos e conta uma vez. Títulos com valores diferentes, como `01:8` e `02:4`, aparecem separadamente.

Com o pacote de julho de 2026, um trecho da saída esperada é:

```text
PAGAMENTO MAIOR ATRASADO (1)
  - 01:13 | nosso_numero=12345761 | valor=R$ 22.900,00 | vencimento=22/07/2026 | recebido=R$ 23.358,00 | data=23/07/2026 | linha do extrato=13 | critério=cnpj/tax_id | cnpj=66777888000199 | excedente=R$ 458,00
```

## Regras e limitações atuais

- O protótipo trabalha apenas com os arquivos 01, 02 e 03. No extrato, considera somente lançamentos com `tipo=C` (crédito).
- Primeiro consolida títulos repetidos entre 01 e 02 quando **CNPJ, vencimento e valor** coincidem. Títulos com o mesmo CNPJ e vencimento, mas valores diferentes, são classificados separadamente.
- Procura correspondências por `nosso_numero` de 01 contra `documento` de 03, depois por nome do cliente em `historico` e por CNPJ em `historico`. O CNPJ é normalizado para 14 dígitos. A comparação de `nosso_numero` com `documento` exige o mesmo texto no CSV, inclusive zeros à esquerda; a remoção dos zeros vale só para a apresentação.
- A busca por nome usa palavras normalizadas e exige duas palavras adjacentes em comum. Abreviações ou grafias muito diferentes podem não ser reconhecidas.
- A busca final apenas por valor é conservadora: considera correspondências únicas de valor igual ou parcial entre créditos sem identificação e títulos ainda não encontrados. Ela não comprova a identidade do pagador e não cobre todos os casos ambíguos ou de valor excedente.
- Para pagamentos com mais de um crédito associado, a classificação de prazo usa a **data do último crédito**. Valores recebidos a menor ou a maior são mostrados sem ajuste automático, cobrança ou devolução.
- O programa não oferece interface gráfica, API nem integração bancária. Revisão humana continua necessária, especialmente para os `POSSÍVEL PAGAMENTO` e títulos não localizados.

## Protótipo de contas a pagar: preparação dos e-mails

Configure `OPENAI_API_KEY` no ambiente ou em `.env` na raiz do projeto e execute `python3 prototipo_contas_a_pagar.py`. Esse comando executa a sequência completa: extrai os campos dos e-mails do único `04*.txt` em `data/`, relaciona cada documento aos débitos do único `03*.csv` e classifica todos os e-mails. O resultado final é `data/emails_contas_a_pagar.csv`, com `company,date,document_type,document_id,amount_due,due_date,payment_row,classification`. Para usar outra pasta, passe `--data-dir "/caminho/para/o/data-pack"`; para escolher outro destino, passe `--output "/caminho/arquivo.csv"`. Não há dependências Python externas.

Cada bloco iniciado por `--- E-MAIL n ---` corresponde a um e-mail. O programa lê os campos `De` e `Data` do cabeçalho, ignora o trecho de WhatsApp, agrupa pelo domínio completo do remetente e ordena cada grupo pela data mais antiga. A coluna `company` contém a parte inicial do domínio: `financeiro@embalagenssaojorge.com.br` gera `embalagenssaojorge`. A data é gravada como `AAAA-MM-DD`.

O programa envia cada e-mail separadamente para `gpt-6-luna`, sem histórico de e-mails anteriores, com saída JSON restrita aos quatro campos extraídos. `amount_due` usa ponto decimal e duas casas; `due_date` usa `AAAA-MM-DD`. IDs compostos somente por dígitos são gravados como texto sem zeros à esquerda: `088231` vira `88231`. IDs alfanuméricos são preservados. O modelo interpreta prazos em linguagem natural: para "5 dias após o recebimento", usa a data do cabeçalho como recebimento quando o e-mail não informa outra data e soma cinco dias corridos. A chave da API não é impressa nem gravada no CSV. O comando completo faz uma chamada por e-mail para extração e outra por empresa/documento distinto para relacionar o histórico, podendo gerar cobrança na API. A classificação final não usa a API.

O CSV final só substitui a versão anterior se as três etapas terminarem sem erro. A pasta `data/` está no `.gitignore`, inclusive o CSV gerado.

### Procurar pagamentos no extrato 03

Para refazer apenas a relação com o extrato, execute `python3 prototipo_contas_a_pagar.py --check-payments`. Esta etapa lê `data/emails_contas_a_pagar.csv` e o único `03*.csv` em `data/`, considera apenas linhas com `tipo=D` e envia à API somente a empresa, o tipo e o ID do documento junto aos números das linhas e textos de `historico` desses débitos. Para usar outro CSV de e-mails, passe `--emails-csv "/caminho/emails.csv"`.

E-mails com a mesma empresa e ID de documento geram uma única chamada; se o tipo variar, os tipos são enviados juntos. Se o ID estiver ausente, cada linha é verificada separadamente. O resultado é salvo na coluna `payment_row` do CSV de e-mails, sem imprimir uma resposta por consulta no terminal. A numeração é a linha física do extrato, incluindo o cabeçalho como linha 1. Esta busca usa apenas o texto de `historico`; ainda não compara valores e datas.

### Classificar os e-mails sem API

Para refazer apenas a classificação, execute `python3 prototipo_contas_a_pagar.py --classify`. O programa usa `payment_row` quando ela contém uma linha válida. Se estiver ausente ou vazia, procura localmente uma única linha `tipo=D` cujo `historico` contenha o ID do documento; quando não há ID, procura o nome da empresa. Correspondências ambíguas não são aceitas. O resultado é gravado nas colunas `payment_row` e `classification` do CSV. Esta execução não faz chamadas à API.

- `paid`: débito do mesmo valor em data igual ou anterior ao vencimento.
- `late payment`: débito do mesmo valor depois do vencimento.
- `wrongful billing`: outro e-mail da mesma empresa e ID tem vencimento anterior e já foi classificado como `paid` ou `late payment`.
- `not paid and late`: não há pagamento do valor esperado e a última data do extrato passou do vencimento.
- `not paid`: não há pagamento do valor esperado e a última data do extrato ainda não passou do vencimento.

Um débito com valor diferente não confirma pagamento. O programa compara valores exatos, sem somar pagamentos parciais. A classificação é feita com a informação disponível até a última data do extrato.
