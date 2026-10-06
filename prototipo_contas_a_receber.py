"""Concilia títulos dos arquivos 01/02 com créditos do extrato 03.

Primeiro usa nosso_numero = documento; depois procura nomes em historico.
Os arquivos de entrada são abertos apenas para leitura.
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import combinations
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


def name_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value.upper())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    legal_words = {
        "LTDA",
        "EIRELI",
        "ME",
        "SA",
        "S",
        "A",
        "DE",
        "DA",
        "DO",
        "DOS",
        "DAS",
        "E",
    }
    return [
        word for word in re.findall(r"[A-Z0-9]+", normalized) if word not in legal_words
    ]


def name_in_history(name: str, history: str) -> bool:
    """Require two adjacent name words; one generic word is insufficient."""
    customer = name_tokens(name)
    bank = name_tokens(history)
    if len(customer) < 2 or len(bank) < 2:
        return False
    return bool(set(zip(customer, customer[1:])) & set(zip(bank, bank[1:])))


def reconcile(directory: Path) -> dict[str, list[str]]:
    paths = [input_file(directory, prefix) for prefix in ("01", "02", "03")]
    source_01, source_02, bank = (csv_rows(path) for path in paths)
    require_columns(paths[0], {"cliente", "nosso_numero", "vencimento", "valor"})
    require_columns(paths[1], {"customer_name", "due_date", "amount"})
    require_columns(paths[2], {"documento", "historico", "tipo", "data", "valor"})

    credits: dict[str, list[Row]] = defaultdict(list)
    for row in bank:
        document = row.fields["documento"]
        if row.fields["tipo"].upper() == "C" and document:
            credits[document].append(row)

    sources = source_01 + source_02
    key_counts = Counter(row.fields.get("nosso_numero", "") for row in sources)
    results: dict[str, list[str]] = defaultdict(list)
    labels: list[str] = []
    names: list[str] = []
    expected_values: list[Decimal] = []
    due_dates: list[date] = []
    for row in sources:
        is_01 = row.source == paths[0].name
        number = row.fields.get("nosso_numero", "")
        expected = money(row.fields["valor"] if is_01 else row.fields["amount"])
        due = parse_date(row.fields["vencimento"] if is_01 else row.fields["due_date"])
        display_number = (number.lstrip("0") or "0") if number else "ausente"
        labels.append(
            f"{'01' if is_01 else '02'}:{row.line} | nosso_numero={display_number} "
            f"| valor={brl(expected)} | vencimento={due:%d/%m/%Y}"
        )
        names.append(row.fields["cliente" if is_01 else "customer_name"])
        expected_values.append(expected)
        due_dates.append(due)

    def classify(index: int, matches: list[tuple[Row, Decimal]], method: str) -> None:
        paid = sum((amount for _, amount in matches), Decimal("0.00"))
        last_payment = max(parse_date(item.fields["data"]) for item, _ in matches)
        bank_lines = ", ".join(str(item.line) for item, _ in matches)
        detail = (
            f"{labels[index]} | recebido={brl(paid)} | data={last_payment:%d/%m/%Y} "
            f"| linha do extrato={bank_lines} | critério={method}"
        )
        if method == "nome":
            detail += f" | cliente={names[index]}"
        expected = expected_values[index]
        due = due_dates[index]
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

    unresolved: list[int] = []
    used_bank_lines: set[int] = set()
    for index, row in enumerate(sources):
        number = row.fields.get("nosso_numero", "")
        if not number:
            unresolved.append(index)
            continue
        if key_counts[number] > 1:
            results["CHAVE DUPLICADA NA ORIGEM"].append(labels[index])
            continue
        matched = credits.get(number, [])
        if not matched:
            unresolved.append(index)
            continue
        classify(
            index,
            [(item, money(item.fields["valor"])) for item in matched],
            "nosso_numero",
        )
        used_bank_lines.update(item.line for item in matched)

    available = [
        item
        for item in bank
        if item.fields["tipo"].upper() == "C" and item.line not in used_bank_lines
    ]
    pending = set(unresolved)
    allocations: dict[int, list[tuple[Row, Decimal]]] = defaultdict(list)

    def name_candidates(credit: Row) -> list[int]:
        return [
            index
            for index in pending
            if name_in_history(names[index], credit.fields["historico"])
        ]

    # Prefer a unique title with exactly the same value.
    for credit in available:
        amount = money(credit.fields["valor"])
        exact = [
            index
            for index in name_candidates(credit)
            if expected_values[index] == amount
        ]
        if len(exact) == 1:
            index = exact[0]
            allocations[index].append((credit, amount))
            pending.remove(index)
            used_bank_lines.add(credit.line)

    # One deposit may combine several titles of the same customer.
    for credit in available:
        if credit.line in used_bank_lines:
            continue
        candidates = name_candidates(credit)
        if not 2 <= len(candidates) <= 12:
            continue
        amount = money(credit.fields["valor"])
        combinations_found = [
            group
            for size in range(2, len(candidates) + 1)
            for group in combinations(candidates, size)
            if sum((expected_values[index] for index in group), Decimal("0.00"))
            == amount
        ]
        if len(combinations_found) == 1:
            for index in combinations_found[0]:
                allocations[index].append((credit, expected_values[index]))
                pending.remove(index)
            used_bank_lines.add(credit.line)

    # A remaining unique name match can be a partial or excess payment.
    for credit in available:
        if credit.line in used_bank_lines:
            continue
        candidates = name_candidates(credit)
        if len(candidates) == 1:
            index = candidates[0]
            allocations[index].append((credit, money(credit.fields["valor"])))
            used_bank_lines.add(credit.line)
            paid = sum((amount for _, amount in allocations[index]), Decimal("0.00"))
            if paid >= expected_values[index]:
                pending.remove(index)

    for index in unresolved:
        if allocations[index]:
            classify(index, allocations[index], "nome")
        elif sources[index].fields.get("nosso_numero", ""):
            results["PAGAMENTO NÃO LOCALIZADO"].append(labels[index])
        else:
            results["SEM CHAVE E SEM CORRESPONDÊNCIA POR NOME"].append(labels[index])
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
        "SEM CHAVE E SEM CORRESPONDÊNCIA POR NOME",
        "CHAVE DUPLICADA NA ORIGEM",
        "VALOR RECEBIDO MAIOR QUE O TÍTULO",
    )
    try:
        results = reconcile(args.data_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    print(
        "Regras: nosso_numero = documento; depois cliente = historico. Apenas tipo C."
    )
    for category in categories:
        items = results[category]
        print(f"\n{category} ({len(items)})")
        for item in items:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
