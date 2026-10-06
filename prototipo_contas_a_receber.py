"""Concilia títulos dos arquivos 01/02 com créditos do extrato 03.

Esta primeira regra usa somente nosso_numero (01/02) = documento (03).
Os arquivos de entrada são abertos apenas para leitura.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


@dataclass(frozen=True)
class Row:
    source: str
    line: int
    fields: dict[str, str]


def csv_rows(path: Path) -> list[Row]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = handle.readline()
        if not header:
            raise ValueError(f"Arquivo vazio: {path}")
        delimiter = ";" if header.count(";") > header.count(",") else ","
        handle.seek(0)
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError(f"Cabeçalho ausente: {path}")
        rows = []
        for fields in reader:
            if None in fields:
                raise ValueError(
                    f"Colunas extras em {path.name}, linha {reader.line_num}"
                )
            rows.append(
                Row(
                    path.name,
                    reader.line_num,
                    {
                        key.strip().lower(): (value or "").strip()
                        for key, value in fields.items()
                    },
                )
            )
        return rows


def require_columns(path: Path, columns: set[str]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = handle.readline()
    delimiter = ";" if header.count(";") > header.count(",") else ","
    actual = {
        column.strip().lower()
        for column in next(csv.reader([header], delimiter=delimiter))
    }
    missing = columns - actual
    if missing:
        raise ValueError(
            f"Colunas ausentes em {path.name}: {', '.join(sorted(missing))}"
        )


def money(value: str) -> Decimal:
    cleaned = value.strip().replace("R$", "").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Valor monetário inválido: {value!r}") from exc


def parse_date(value: str) -> date:
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()  # noqa: DTZ007
        except ValueError:
            pass
    raise ValueError(f"Data inválida: {value!r}")


def brl(value: Decimal) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def input_file(directory: Path, prefix: str) -> Path:
    matches = sorted(directory.glob(f"{prefix}*.csv"))
    if len(matches) != 1:
        raise ValueError(
            f"Esperado exatamente um CSV começando com {prefix!r} em {directory}; "
            f"encontrados: {len(matches)}"
        )
    return matches[0]


def reconcile(directory: Path) -> dict[str, list[str]]:
    paths = [input_file(directory, prefix) for prefix in ("01", "02", "03")]
    source_01, source_02, bank = (csv_rows(path) for path in paths)
    require_columns(paths[0], {"nosso_numero", "vencimento", "valor"})
    require_columns(paths[1], {"due_date", "amount"})
    require_columns(paths[2], {"documento", "tipo", "data", "valor"})

    credits: dict[str, list[Row]] = defaultdict(list)
    for row in bank:
        document = row.fields["documento"]
        if row.fields["tipo"].upper() == "C" and document:
            credits[document].append(row)

    sources = source_01 + source_02
    key_counts = Counter(row.fields.get("nosso_numero", "") for row in sources)
    results: dict[str, list[str]] = defaultdict(list)
    for row in sources:
        is_01 = row.source == paths[0].name
        number = row.fields.get("nosso_numero", "")
        expected = money(row.fields["valor"] if is_01 else row.fields["amount"])
        due = parse_date(row.fields["vencimento"] if is_01 else row.fields["due_date"])
        display_number = (number.lstrip("0") or "0") if number else "ausente"
        label = (
            f"{'01' if is_01 else '02'}:{row.line} | nosso_numero={display_number} "
            f"| valor={brl(expected)} "
            f"| vencimento={due:%d/%m/%Y}"
        )

        if not number:
            results["SEM CHAVE PARA CONCILIAÇÃO"].append(label)
            continue
        if key_counts[number] > 1:
            results["CHAVE DUPLICADA NA ORIGEM"].append(label)
            continue

        matched = credits.get(number, [])
        if not matched:
            results["PAGAMENTO NÃO LOCALIZADO"].append(label)
            continue

        paid = sum((money(item.fields["valor"]) for item in matched), Decimal("0.00"))
        payment_dates = [parse_date(item.fields["data"]) for item in matched]
        last_payment = max(payment_dates)
        bank_lines = ", ".join(str(item.line) for item in matched)
        detail = (
            f"{label} | recebido={brl(paid)} | data={last_payment:%d/%m/%Y} "
            f"| linha do extrato={bank_lines}"
        )
        if paid < expected:
            results["PAGAMENTO INCOMPLETO"].append(
                f"{detail} | faltam={brl(expected - paid)}"
                + (" | crédito após vencimento" if last_payment > due else "")
            )
        elif paid > expected:
            results["VALOR RECEBIDO MAIOR QUE O TÍTULO"].append(
                f"{detail} | excedente={brl(paid - expected)}"
            )
        elif last_payment > due:
            results["PAGAMENTO ATRASADO"].append(detail)
        else:
            results["PAGAMENTO EM DIA"].append(detail)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()
    categories = (
        "PAGAMENTO EM DIA",
        "PAGAMENTO ATRASADO",
        "PAGAMENTO INCOMPLETO",
        "PAGAMENTO NÃO LOCALIZADO",
        "SEM CHAVE PARA CONCILIAÇÃO",
        "CHAVE DUPLICADA NA ORIGEM",
        "VALOR RECEBIDO MAIOR QUE O TÍTULO",
    )
    try:
        results = reconcile(args.data_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    print("Regra: nosso_numero (01/02) = documento (03), considerando apenas tipo C.")
    for category in categories:
        items = results[category]
        print(f"\n{category} ({len(items)})")
        for item in items:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
