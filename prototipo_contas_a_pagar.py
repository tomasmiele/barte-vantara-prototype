"""Extrai dados de pagamento dos e-mails do arquivo 04 para um CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODEL = "gpt-6-luna"
API_URL = "https://api.openai.com/v1/responses"
EMAIL_START = re.compile(r"^--- E-MAIL\s+(\d+)\s+-+\s*$", re.MULTILINE)
HEADER = re.compile(r"^(De|Data):\s*(.+?)\s*$", re.MULTILINE)
ADDRESS = re.compile(r"^[^\s@<>]+@([^\s@<>]+)$")
FIELDS = ("document_type", "document_id", "amount_due", "due_date")
SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": ["string", "null"]},
        "document_id": {"type": ["string", "null"]},
        "amount_due": {"type": ["string", "null"]},
        "due_date": {"type": ["string", "null"]},
    },
    "required": list(FIELDS),
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "Extraia do e-mail quatro campos em JSON: document_type, document_id, "
    "amount_due, due_date. Use somente informações do próprio e-mail. "
    "Se houver nota fiscal com boleto, classifique como nota_fiscal e use "
    "o número da nota; boleto é o meio de pagamento. Para CT-e use ct_e. "
    "Devolva o ID como texto, sem prefixo como 'NF'. Se houver valor original e atualizado, "
    "use o valor atualizado a pagar. Escreva amount_due em BRL com ponto "
    "decimal e duas casas, sem R$. Escreva due_date em AAAA-MM-DD. "
    "Interprete também vencimentos descritos em texto, como '5 dias após o "
    "recebimento'. Use a Data do cabeçalho como data de recebimento quando "
    "não houver outra data de recebimento no e-mail; some dias corridos, "
    "exceto se o texto disser dias úteis. Se o vencimento tiver só dia/mês, "
    "use o ano da Data do cabeçalho quando for inequívoco. Prefira um "
    "vencimento atualizado a um original. Use null só se o campo realmente "
    "não puder ser determinado; "
    "não invente números, valores ou datas."
)
PAYMENT_SCHEMA = {
    "type": "object",
    "properties": {"payment_row": {"type": ["integer", "null"]}},
    "required": ["payment_row"],
    "additionalProperties": False,
}
PAYMENT_INSTRUCTIONS = (
    "Compare uma empresa e seu tipo/ID de documento com as descrições 'historico' "
    "dos lançamentos bancários tipo D fornecidos. Retorne payment_row como o "
    "número da linha do CSV original somente se o histórico identificar "
    "claramente essa empresa ou o mesmo documento pelo tipo e ID. "
    "Descrições genéricas de tarifas não são pagamentos da empresa. "
    "Se não houver correspondência confiável, retorne null. "
    "Não use outras informações além das fornecidas."
)


@dataclass(frozen=True)
class Email:
    number: int
    domain: str
    company: str
    date: datetime
    content: str


def input_file(directory: Path) -> Path:
    matches = sorted(directory.glob("04*.txt"))
    if len(matches) != 1:
        raise ValueError(
            f"Esperado exatamente um TXT começando com '04' em {directory}; "
            f"encontrados: {len(matches)}"
        )
    return matches[0]


def bank_file(directory: Path) -> Path:
    matches = sorted(directory.glob("03*.csv"))
    if len(matches) != 1:
        raise ValueError(
            f"Esperado exatamente um CSV começando com '03' em {directory}; "
            f"encontrados: {len(matches)}"
        )
    return matches[0]


def parse_emails(text: str) -> list[Email]:
    markers = list(EMAIL_START.finditer(text))
    if not markers:
        raise ValueError("Nenhum bloco '--- E-MAIL n ---' encontrado no arquivo 04")
    emails: list[Email] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        block = text[marker.end() : end]
        block = block.split("--- TRECHO DO GRUPO DE WHATSAPP", 1)[0].strip()
        headers = dict(HEADER.findall(block.split("\n\n", 1)[0]))
        number = int(marker.group(1))
        if "De" not in headers or "Data" not in headers:
            raise ValueError(f"'De' ou 'Data' ausente no E-MAIL {number}")
        sender = headers["De"].strip()
        address = ADDRESS.fullmatch(sender)
        if not address:
            raise ValueError(f"Remetente inválido no E-MAIL {number}: {sender!r}")
        domain = address.group(1).lower().rstrip(".")
        try:
            sent_at = datetime.strptime(headers["Data"], "%d/%m/%Y %H:%M")  # noqa: DTZ007
        except ValueError as exc:
            raise ValueError(
                f"Data inválida no E-MAIL {number}: {headers['Data']!r}"
            ) from exc
        emails.append(Email(number, domain, domain.split(".", 1)[0], sent_at, block))
    return emails


def grouped_emails(emails: list[Email]) -> list[Email]:
    groups: dict[str, list[Email]] = defaultdict(list)
    for email in emails:
        groups[email.domain].append(email)
    domains = sorted(
        groups, key=lambda domain: (min(e.date for e in groups[domain]), domain)
    )
    return [
        email
        for domain in domains
        for email in sorted(groups[domain], key=lambda e: e.date)
    ]


def api_key(project_dir: Path) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    env_file = project_dir / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            if (
                separator
                and name.strip().removeprefix("export ").strip() == "OPENAI_API_KEY"
            ):
                key = value.strip().strip("'\"")
                if key:
                    return key
    raise ValueError("OPENAI_API_KEY ausente do ambiente e do .env do projeto")


def validate_extraction(data: object, number: int) -> dict[str, str | None]:
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ValueError(f"Campos inesperados no JSON do E-MAIL {number}")
    if any(value is not None and not isinstance(value, str) for value in data.values()):
        raise ValueError(f"Tipo de dado inválido no JSON do E-MAIL {number}")
    result: dict[str, str | None] = dict(data)
    document_id = result["document_id"]
    if document_id is not None:
        document_id = document_id.strip()
        if re.fullmatch(r"[0-9]+", document_id):
            document_id = document_id.lstrip("0") or "0"
        result["document_id"] = document_id or None
    amount = result["amount_due"]
    if amount is not None:
        try:
            value = Decimal(amount)
        except InvalidOperation as exc:
            raise ValueError(f"Valor inválido no JSON do E-MAIL {number}") from exc
        if not value.is_finite() or value < 0 or value.as_tuple().exponent < -2:
            raise ValueError(f"Valor inválido no JSON do E-MAIL {number}")
        result["amount_due"] = f"{value:.2f}"
    due_date = result["due_date"]
    if due_date is not None:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")  # noqa: DTZ007
        except ValueError as exc:
            raise ValueError(f"Vencimento inválido no JSON do E-MAIL {number}") from exc
    return result


def model_json(payload: dict, key: str, context: str) -> object:
    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"OpenAI API retornou HTTP {exc.code} para {context}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Falha de conexão com OpenAI API para {context}") from exc
    if result.get("status") != "completed":
        raise RuntimeError(f"Resposta incompleta da OpenAI API para {context}")
    content = [
        item
        for output in result.get("output", [])
        if output.get("type") == "message"
        for item in output.get("content", [])
    ]
    if any(item.get("type") == "refusal" for item in content):
        raise RuntimeError(f"Modelo recusou {context}")
    texts = [item["text"] for item in content if item.get("type") == "output_text"]
    if len(texts) != 1:
        raise RuntimeError(f"JSON de saída ausente para {context}")
    return json.loads(texts[0])


def extract_json(email: Email, key: str) -> dict[str, str | None]:
    # Cada requisição contém somente um e-mail, sem histórico de respostas.
    payload = {
        "model": MODEL,
        "instructions": INSTRUCTIONS,
        "input": email.content,
        "reasoning": {"effort": "low"},
        "max_output_tokens": 400,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "payable_email_extraction",
                "strict": True,
                "schema": SCHEMA,
            }
        },
    }
    return validate_extraction(
        model_json(payload, key, f"E-MAIL {email.number}"), email.number
    )


def payment_queries(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"company", "document_type", "document_id"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"Colunas ausentes em {path.name}: {', '.join(sorted(required))}"
            )
        queries = []
        positions = {}
        for row in reader:
            company = (row["company"] or "").strip()
            document_type = (row["document_type"] or "").strip()
            document_id = (row["document_id"] or "").strip()
            if not company:
                raise ValueError(
                    f"Empresa ausente em {path.name}, linha {reader.line_num}"
                )
            if re.fullmatch(r"[0-9]+", document_id):
                document_id = document_id.lstrip("0") or "0"
            # Sem ID, duas linhas não podem ser tratadas como o mesmo documento.
            identity = (
                ("id", document_id) if document_id else ("linha", reader.line_num)
            )
            group = (company.casefold(), identity)
            if group not in positions:
                positions[group] = len(queries)
                queries.append(
                    {
                        "company": company,
                        "document_type": document_type,
                        "document_id": document_id,
                    }
                )
            elif document_type:
                existing = queries[positions[group]]
                types = (
                    existing["document_type"].split(" / ")
                    if existing["document_type"]
                    else []
                )
                if document_type.casefold() not in {item.casefold() for item in types}:
                    existing["document_type"] = " / ".join((*types, document_type))
    return queries


def debit_histories(path: Path) -> list[dict[str, int | str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"tipo", "historico"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"Colunas ausentes em {path.name}: {', '.join(sorted(required))}"
            )
        return [
            {"row": reader.line_num, "historico": (row["historico"] or "").strip()}
            for row in reader
            if (row["tipo"] or "").strip().upper() == "D"
        ]


def match_payment(
    query: dict[str, str], debits: list[dict[str, int | str]], key: str
) -> int | None:
    payload = {
        "model": MODEL,
        "instructions": PAYMENT_INSTRUCTIONS,
        "input": json.dumps({**query, "debits": debits}, ensure_ascii=False),
        "reasoning": {"effort": "low"},
        "max_output_tokens": 200,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "payment_history_match",
                "strict": True,
                "schema": PAYMENT_SCHEMA,
            }
        },
    }
    result = model_json(payload, key, f"{query['company']} / {query['document_id']}")
    if not isinstance(result, dict) or set(result) != {"payment_row"}:
        raise ValueError("Resposta de pagamento com campos inesperados")
    payment_row = result["payment_row"]
    if payment_row is None:
        return None
    valid_rows = {debit["row"] for debit in debits}
    if type(payment_row) is not int or payment_row not in valid_rows:
        raise ValueError(f"Linha de pagamento inválida: {payment_row!r}")
    return payment_row


def check_payments(directory: Path, emails_csv: Path) -> None:
    queries = payment_queries(emails_csv)
    debits = debit_histories(bank_file(directory))
    key = api_key(Path(__file__).resolve().parent) if queries and debits else ""
    calls = 0
    for query in queries:
        if debits:
            calls += 1
            row = match_payment(query, debits, key)
        else:
            row = None
        answer = "" if row is None else str(row)
        print(
            f"Chamada {calls if debits else 0} | empresa={query['company']} | "
            f"documento={query['document_type']} | id={query['document_id']} | "
            f"linha={answer}"
        )
    print(f"Chamadas OpenAI nesta etapa: {calls}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(__file__).resolve().parent / "data"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destino do CSV (padrão: data/emails_contas_a_pagar.csv)",
    )
    parser.add_argument(
        "--check-payments",
        action="store_true",
        help="Compara os documentos do CSV de e-mails com os históricos tipo D do arquivo 03",
    )
    parser.add_argument(
        "--emails-csv",
        type=Path,
        help="CSV de e-mails para --check-payments (padrão: data/emails_contas_a_pagar.csv)",
    )
    args = parser.parse_args()
    if args.check_payments:
        check_payments(
            args.data_dir,
            args.emails_csv or args.data_dir / "emails_contas_a_pagar.csv",
        )
        return
    source = input_file(args.data_dir)
    output = args.output or args.data_dir / "emails_contas_a_pagar.csv"
    emails = grouped_emails(parse_emails(source.read_text(encoding="utf-8-sig")))
    key = api_key(Path(__file__).resolve().parent)
    rows = []
    for email in emails:
        extracted = extract_json(email, key)
        rows.append(
            (
                email.company,
                email.date.strftime("%Y-%m-%d"),
                *(extracted[field] or "" for field in FIELDS),
            )
        )
        print(f"E-MAIL {email.number}: JSON extraído")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("company", "date", *FIELDS))
        writer.writerows(rows)
    print(f"{len(rows)} e-mails exportados para {output}")


if __name__ == "__main__":
    main()
