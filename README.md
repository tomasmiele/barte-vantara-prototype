# Protótipo de contas a receber

Este projeto compara os títulos dos arquivos **01** e **02** com os créditos do extrato **03**. Ele mostra no terminal quais pagamentos foram localizados, se chegaram até o vencimento e se o valor recebido foi igual, menor ou maior que o valor do título. Os arquivos de entrada são apenas lidos; a execução não altera os CSVs.

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

No Windows, substitua `python3` por `py -3` e use o caminho da pasta no seu computador. O programa **não** cria arquivos de saída: o relatório aparece no mesmo terminal em que o comando foi executado. Se faltar algum CSV ou coluna obrigatória, ele mostra uma mensagem de erro nesse terminal.

## Como ler a saída

O programa imprime uma seção para cada categoria, com a quantidade entre parênteses e as linhas correspondentes:

- `PAGAMENTO EM DIA` e `PAGAMENTO ATRASADO`: crédito do mesmo valor, até o vencimento ou depois dele.
- `PAGAMENTO INCOMPLETO`: crédito menor que o valor devido; a linha mostra `faltam=...` e, quando aplicável, `crédito após vencimento`.
- `PAGAMENTO MAIOR EM DIA` e `PAGAMENTO MAIOR ATRASADO`: crédito maior que o valor devido; a linha mostra `excedente=...`.
- `PAGAMENTO NÃO LOCALIZADO`: título sem correspondência aceita no extrato.
- `POSSÍVEL PAGAMENTO EM DIA`, `POSSÍVEL PAGAMENTO ATRASADO` e `POSSÍVEL PAGAMENTO INCOMPLETO`: correspondência feita somente pelo valor, que exige conferência humana. No caso incompleto, a linha mostra o valor faltante.

Uma data igual ao vencimento conta como pagamento em dia. As referências `01:13` e `02:4`, por exemplo, indicam o arquivo de origem e o número da linha no CSV. `linha do extrato=13` aponta para a linha do arquivo 03. O `nosso_numero` é exibido sem zeros à esquerda. Quando uma linha reúne títulos distintos, como `01:8 + 02:4`, **a contagem da categoria inclui os dois títulos**, mesmo que só uma linha seja impressa.

Com o pacote de julho de 2026, um trecho da saída esperada é:

```text
PAGAMENTO MAIOR ATRASADO (1)
  - 01:13 | nosso_numero=12345761 | valor=R$ 22.900,00 | vencimento=22/07/2026 | recebido=R$ 23.358,00 | data=23/07/2026 | linha do extrato=13 | critério=cnpj/tax_id | cnpj=66777888000199 | excedente=R$ 458,00
```

## Regras e limitações atuais

- O protótipo trabalha apenas com os arquivos 01, 02 e 03. No extrato, considera somente lançamentos com `tipo=C` (crédito).
- Primeiro consolida títulos repetidos entre 01 e 02 quando **CNPJ, vencimento e valor** coincidem. Títulos com o mesmo CNPJ e vencimento, mas valores diferentes, podem ser agrupados; o valor esperado do grupo é a soma dos títulos.
- Procura correspondências por `nosso_numero` de 01 contra `documento` de 03, depois por nome do cliente em `historico` e por CNPJ em `historico`. O CNPJ é normalizado para 14 dígitos. A comparação de `nosso_numero` com `documento` exige o mesmo texto no CSV, inclusive zeros à esquerda; a remoção dos zeros vale só para a apresentação.
- A busca por nome usa palavras normalizadas e exige duas palavras adjacentes em comum. Abreviações ou grafias muito diferentes podem não ser reconhecidas.
- A busca final apenas por valor é conservadora: considera correspondências únicas de valor igual ou parcial entre créditos sem identificação e títulos ainda não encontrados. Ela não comprova a identidade do pagador e não cobre todos os casos ambíguos ou de valor excedente.
- Para pagamentos com mais de um crédito associado, a classificação de prazo usa a **data do último crédito**. Valores recebidos a menor ou a maior são mostrados sem ajuste automático, cobrança ou devolução.
- O programa não oferece interface gráfica, API, integração bancária nem exportação do relatório. Revisão humana continua necessária, especialmente para os `POSSÍVEL PAGAMENTO` e títulos não localizados.

## Protótipo de contas a pagar: preparação dos e-mails

Configure `OPENAI_API_KEY` no ambiente ou em `.env` na raiz do projeto e execute `python3 prototipo_contas_a_pagar.py`. O programa lê o único arquivo `04*.txt` em `data/` e cria `data/emails_contas_a_pagar.csv` com `company,date,document_type,document_id,amount_due,due_date`. Para usar outra pasta, passe `--data-dir "/caminho/para/o/data-pack"`; para escolher outro destino, passe `--output "/caminho/arquivo.csv"`. Não há dependências Python externas.

Cada bloco iniciado por `--- E-MAIL n ---` corresponde a um e-mail. O programa lê os campos `De` e `Data` do cabeçalho, ignora o trecho de WhatsApp, agrupa pelo domínio completo do remetente e ordena cada grupo pela data mais antiga. A coluna `company` contém a parte inicial do domínio: `financeiro@embalagenssaojorge.com.br` gera `embalagenssaojorge`. A data é gravada como `AAAA-MM-DD`.

O programa envia cada e-mail separadamente para `gpt-6-luna`, sem histórico de e-mails anteriores, com saída JSON restrita aos quatro campos extraídos. `amount_due` usa ponto decimal e duas casas; `due_date` usa `AAAA-MM-DD`. IDs compostos somente por dígitos são gravados como texto sem zeros à esquerda: `088231` vira `88231`. IDs alfanuméricos são preservados. O modelo interpreta prazos em linguagem natural: para "5 dias após o recebimento", usa a data do cabeçalho como recebimento quando o e-mail não informa outra data e soma cinco dias corridos. A chave da API não é impressa nem gravada no CSV. Cada execução faz uma nova chamada por e-mail e pode gerar cobrança na API.

Esta etapa organiza os e-mails; a conciliação com os débitos (`tipo=D`) do extrato 03 ainda não está implementada. A pasta `data/` está no `.gitignore`, inclusive o CSV gerado.
