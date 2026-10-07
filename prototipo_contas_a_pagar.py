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
            f"OpenAI API retornou HTTP {exc.code} para E-MAIL {email.number}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Falha de conexão com OpenAI API para E-MAIL {email.number}"
        ) from exc
    if result.get("status") != "completed":
        raise RuntimeError(
            f"Resposta incompleta da OpenAI API para E-MAIL {email.number}"
        )
    content = [
        item
        for output in result.get("output", [])
        if output.get("type") == "message"
        for item in output.get("content", [])
    ]
    if any(item.get("type") == "refusal" for item in content):
        raise RuntimeError(f"Modelo recusou o E-MAIL {email.number}")
    texts = [item["text"] for item in content if item.get("type") == "output_text"]
    if len(texts) != 1:
        raise RuntimeError(f"JSON de saída ausente para E-MAIL {email.number}")
    return validate_extraction(json.loads(texts[0]), email.number)


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
    args = parser.parse_args()
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
