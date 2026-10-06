"""Agrupa os e-mails do arquivo 04 por domínio e exporta empresa/data.

Esta primeira etapa prepara os dados para a conciliação futura com os
lançamentos de débito (tipo D) do extrato 03.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


EMAIL_START = re.compile(r"^--- E-MAIL\s+\d+\s+-+\s*$", re.MULTILINE)
HEADER = re.compile(r"^(De|Data):\s*(.+?)\s*$", re.MULTILINE)
ADDRESS = re.compile(r"^[^\s@<>]+@([^\s@<>]+)$")


@dataclass(frozen=True)
class Email:
    domain: str
    company: str
    date: datetime


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
        # A seção posterior de WhatsApp não pertence ao último e-mail.
        block = block.split("--- TRECHO DO GRUPO DE WHATSAPP", 1)[0]
        header_text = block.lstrip("\n").split("\n\n", 1)[0]
        headers = dict(HEADER.findall(header_text))
        if "De" not in headers or "Data" not in headers:
            raise ValueError(f"'De' ou 'Data' ausente no E-MAIL {index + 1}")

        sender = headers["De"].strip()
        address = ADDRESS.fullmatch(sender)
        if not address:
            raise ValueError(f"Remetente inválido no E-MAIL {index + 1}: {sender!r}")
        domain = address.group(1).lower().rstrip(".")
        company = domain.split(".", 1)[0]
        try:
            sent_at = datetime.strptime(headers["Data"], "%d/%m/%Y %H:%M")
        except ValueError as exc:
            raise ValueError(
                f"Data inválida no E-MAIL {index + 1}: {headers['Data']!r}"
            ) from exc
        emails.append(Email(domain, company, sent_at))
    return emails


def grouped_emails(emails: list[Email]) -> list[Email]:
    groups: dict[str, list[Email]] = defaultdict(list)
    for email in emails:
        groups[email.domain].append(email)
    # Cada domínio fica junto; os grupos e seus e-mails começam pelos mais antigos.
    ordered_domains = sorted(groups, key=lambda domain: (min(e.date for e in groups[domain]), domain))
    return [email for domain in ordered_domains for email in sorted(groups[domain], key=lambda e: e.date)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", type=Path, default=Path(__file__).resolve().parent / "data"
    )
    parser.add_argument(
        "--output", type=Path, help="Destino do CSV (padrão: data/emails_contas_a_pagar.csv)"
    )
    args = parser.parse_args()

    source = input_file(args.data_dir)
    output = args.output or args.data_dir / "emails_contas_a_pagar.csv"
    emails = grouped_emails(parse_emails(source.read_text(encoding="utf-8-sig")))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("company", "date"))
        writer.writerows((email.company, email.date.strftime("%Y-%m-%d")) for email in emails)
    print(f"{len(emails)} e-mails exportados para {output}")


if __name__ == "__main__":
    main()
