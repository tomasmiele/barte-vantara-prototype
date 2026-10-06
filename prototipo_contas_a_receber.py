"""Concilia títulos dos arquivos 01/02 com créditos do extrato 03.

Consolida títulos repetidos em 01/02 por CNPJ, vencimento e valor.
Títulos distintos do mesmo CNPJ e vencimento são classificados em conjunto.
Depois usa nosso_numero, nome e CNPJ/tax_id para procurar créditos no extrato.
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
from typing import Callable


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


def normalize_tax_id(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) == 14 else ""


def tax_id_in_history(tax_id: str, history: str) -> bool:
    """Find an entire 14-digit CNPJ, with or without punctuation, in historico."""
    if not tax_id:
        return False
    pattern = r"(?<!\d)(?:\d[\s./-]*){13}\d(?!\d)"
    return any(
        normalize_tax_id(match.group()) == tax_id
        for match in re.finditer(pattern, history)
    )


def reconcile(
    directory: Path, category_counts: Counter[str] | None = None
) -> dict[str, list[str]]:
    if category_counts is None:
        category_counts = Counter()
    paths = [input_file(directory, prefix) for prefix in ("01", "02", "03")]
    source_01, source_02, bank = (csv_rows(path) for path in paths)
    require_columns(
        paths[0], {"cliente", "cnpj", "nosso_numero", "vencimento", "valor"}
    )
    require_columns(paths[1], {"customer_name", "tax_id", "due_date", "amount"})
    require_columns(paths[2], {"documento", "historico", "tipo", "data", "valor"})

    credits: dict[str, list[Row]] = defaultdict(list)
    for row in bank:
        document = row.fields["documento"]
        if row.fields["tipo"].upper() == "C" and document:
            credits[document].append(row)

    sources = source_01 + source_02
    results: dict[str, list[str]] = defaultdict(list)
    references: list[list[str]] = []
    names: list[str] = []
    name_aliases: list[list[str]] = []
    tax_ids: list[str] = []
    expected_values: list[Decimal] = []
    due_dates: list[date] = []
    for row in sources:
        is_01 = row.source == paths[0].name
        expected = money(row.fields["valor"] if is_01 else row.fields["amount"])
        due = parse_date(row.fields["vencimento"] if is_01 else row.fields["due_date"])
        name = row.fields["cliente" if is_01 else "customer_name"]
        references.append([f"{'01' if is_01 else '02'}:{row.line}"])
        names.append(name)
        name_aliases.append([name])
        tax_ids.append(normalize_tax_id(row.fields["cnpj" if is_01 else "tax_id"]))
        expected_values.append(expected)
        due_dates.append(due)

    # Match rows across 01 and 02 one-to-one, so one receivable is reported once.
    source_01_by_signature: dict[tuple[str, date, Decimal], list[int]] = defaultdict(
        list
    )
    for index in range(len(source_01)):
        if tax_ids[index]:
            source_01_by_signature[
                (tax_ids[index], due_dates[index], expected_values[index])
            ].append(index)
    duplicates: set[int] = set()
    for index in range(len(source_01), len(sources)):
        if not tax_ids[index]:
            continue
        signature = (tax_ids[index], due_dates[index], expected_values[index])
        matching_01 = source_01_by_signature[signature]
        if matching_01:
            primary = matching_01.pop(0)
            duplicates.add(index)
            references[primary].extend(references[index])
            name_aliases[primary].append(names[index])

    active_indices = [index for index in range(len(sources)) if index not in duplicates]
    key_counts = Counter(
        sources[index].fields.get("nosso_numero", "") for index in active_indices
    )
    repeated_keys = sorted(
        number for number, count in key_counts.items() if number and count > 1
    )
    if repeated_keys:
        raise ValueError(
            "nosso_numero repetido após consolidar 01/02: " + ", ".join(repeated_keys)
        )
    labels: list[str] = []
    for index, row in enumerate(sources):
        number = row.fields.get("nosso_numero", "")
        display_number = (number.lstrip("0") or "0") if number else "ausente"
        labels.append(
            f"{' + '.join(references[index])} | nosso_numero={display_number} "
            f"| valor={brl(expected_values[index])} "
            f"| vencimento={due_dates[index]:%d/%m/%Y}"
        )

    same_company_due: dict[tuple[str, date], list[int]] = defaultdict(list)
    for index in active_indices:
        if tax_ids[index]:
            same_company_due[(tax_ids[index], due_dates[index])].append(index)
    distinct_cross_groups: dict[tuple[str, date], list[int]] = {}
    for (tax_id, due), indices in same_company_due.items():
        source_refs = [
            reference for index in indices for reference in references[index]
        ]
        if (
            any(reference.startswith("01:") for reference in source_refs)
            and any(reference.startswith("02:") for reference in source_refs)
            and len({expected_values[index] for index in indices}) > 1
        ):
            distinct_cross_groups[(tax_id, due)] = indices

    def group_label(indices: list[int]) -> str:
        expected = sum((expected_values[index] for index in indices), Decimal("0.00"))
        due = due_dates[indices[0]]
        source_refs = [
            reference for index in indices for reference in references[index]
        ]
        return (
            f"{' + '.join(source_refs)} | cnpj={tax_ids[indices[0]]} "
            f"| valor={brl(expected)} | vencimento={due:%d/%m/%Y}"
        )

    def classify(
        indices: list[int], matches: list[tuple[Row, Decimal]], methods: list[str]
    ) -> None:
        expected = sum((expected_values[index] for index in indices), Decimal("0.00"))
        due = due_dates[indices[0]]
        label = labels[indices[0]] if len(indices) == 1 else group_label(indices)
        paid = sum((amount for _, amount in matches), Decimal("0.00"))
        last_payment = max(parse_date(item.fields["data"]) for item, _ in matches)
        bank_lines = ", ".join(dict.fromkeys(str(item.line) for item, _ in matches))
        method = " + ".join(dict.fromkeys(methods))
        detail = (
            f"{label} | recebido={brl(paid)} | data={last_payment:%d/%m/%Y} "
            f"| linha do extrato={bank_lines} | critério={method}"
        )
        if len(indices) == 1 and "nome" in methods:
            detail += f" | cliente={names[indices[0]]}"
        if len(indices) == 1 and "cnpj/tax_id" in methods:
            detail += f" | cnpj={tax_ids[indices[0]]}"
        if paid < expected:
            category = "PAGAMENTO INCOMPLETO"
            description = f"{detail} | faltam={brl(expected - paid)}" + (
                " | crédito após vencimento" if last_payment > due else ""
            )
        elif paid > expected:
            category = "VALOR RECEBIDO MAIOR QUE O TÍTULO"
            description = f"{detail} | excedente={brl(paid - expected)}"
        elif last_payment > due:
            category = "PAGAMENTO ATRASADO"
            description = detail
        else:
            category = "PAGAMENTO EM DIA"
            description = detail
        results[category].append(description)
        category_counts[category] += len(indices)

    unresolved: list[int] = []
    used_bank_lines: set[int] = set()
    classified_by_key: set[int] = set()
    matched_payments: dict[int, list[tuple[Row, Decimal]]] = defaultdict(list)
    match_methods: dict[int, list[str]] = defaultdict(list)

    def record_match(
        index: int, matches: list[tuple[Row, Decimal]], method: str
    ) -> None:
        matched_payments[index].extend(matches)
        match_methods[index].append(method)

    for index in active_indices:
        if index in classified_by_key:
            continue
        row = sources[index]
        number = row.fields.get("nosso_numero", "")
        if not number:
            unresolved.append(index)
            continue
        matched = credits.get(number, [])
        if not matched:
            unresolved.append(index)
            continue
        group = distinct_cross_groups.get((tax_ids[index], due_dates[index]), [])
        if len(matched) == 1 and len(group) > 1:
            combined = sum(
                (expected_values[sibling] for sibling in group), Decimal("0.00")
            )
            other_keyed_credits = any(
                credits.get(sources[sibling].fields.get("nosso_numero", ""))
                for sibling in group
                if sibling != index
            )
            if (
                money(matched[0].fields["valor"]) == combined
                and not other_keyed_credits
                and all(sibling not in classified_by_key for sibling in group)
            ):
                for sibling in group:
                    record_match(
                        sibling,
                        [(matched[0], expected_values[sibling])],
                        "nosso_numero + grupo CNPJ/vencimento",
                    )
                classified_by_key.update(group)
                used_bank_lines.add(matched[0].line)
                continue
        record_match(
            index,
            [(item, money(item.fields["valor"])) for item in matched],
            "nosso_numero",
        )
        classified_by_key.add(index)
        used_bank_lines.update(item.line for item in matched)

    available = [
        item
        for item in bank
        if item.fields["tipo"].upper() == "C" and item.line not in used_bank_lines
    ]
    pending = set(unresolved)
    allocations: dict[int, list[tuple[Row, Decimal]]] = defaultdict(list)

    def name_candidates(credit: Row) -> list[int]:
        direct = {
            index
            for index in pending
            if any(
                name_in_history(alias, credit.fields["historico"])
                for alias in name_aliases[index]
            )
        }
        # Different-value titles with the same CNPJ and due date remain
        # separate, but may share one bank deposit equal to their sum.
        candidates = set(direct)
        for index in direct:
            if tax_ids[index]:
                candidates.update(
                    sibling
                    for sibling in same_company_due[(tax_ids[index], due_dates[index])]
                    if sibling in pending
                )
        return sorted(candidates)

    def allocate_candidates(
        candidate_rows: Callable[[Row], list[int]],
        pending_rows: set[int],
        found: dict[int, list[tuple[Row, Decimal]]],
    ) -> None:
        # Prefer a unique title with exactly the same value.
        for credit in available:
            if credit.line in used_bank_lines:
                continue
            amount = money(credit.fields["valor"])
            exact = [
                index
                for index in candidate_rows(credit)
                if expected_values[index] == amount
            ]
            if len(exact) == 1:
                index = exact[0]
                found[index].append((credit, amount))
                pending_rows.remove(index)
                used_bank_lines.add(credit.line)

        # One deposit may combine several titles of the same customer.
        for credit in available:
            if credit.line in used_bank_lines:
                continue
            candidates = candidate_rows(credit)
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
                    found[index].append((credit, expected_values[index]))
                    pending_rows.remove(index)
                used_bank_lines.add(credit.line)

        # A remaining unique match can be a partial or excess payment.
        for credit in available:
            if credit.line in used_bank_lines:
                continue
            candidates = candidate_rows(credit)
            if len(candidates) == 1:
                index = candidates[0]
                found[index].append((credit, money(credit.fields["valor"])))
                used_bank_lines.add(credit.line)
                paid = sum((amount for _, amount in found[index]), Decimal("0.00"))
                if paid >= expected_values[index]:
                    pending_rows.remove(index)

    allocate_candidates(name_candidates, pending, allocations)

    for index in unresolved:
        if allocations[index]:
            record_match(index, allocations[index], "nome")

    tax_pending = {index for index in unresolved if not allocations[index]}
    tax_allocations: dict[int, list[tuple[Row, Decimal]]] = defaultdict(list)

    def tax_candidates(credit: Row) -> list[int]:
        return sorted(
            index
            for index in tax_pending
            if tax_id_in_history(tax_ids[index], credit.fields["historico"])
        )

    allocate_candidates(tax_candidates, tax_pending, tax_allocations)
    for index in unresolved:
        if tax_allocations[index]:
            record_match(index, tax_allocations[index], "cnpj/tax_id")

    grouped_indices: set[int] = set()
    for indices in distinct_cross_groups.values():
        matches = [match for index in indices for match in matched_payments[index]]
        methods = [method for index in indices for method in match_methods[index]]
        if matches:
            classify(indices, matches, methods)
        else:
            results["PAGAMENTO NÃO LOCALIZADO"].append(group_label(indices))
            category_counts["PAGAMENTO NÃO LOCALIZADO"] += len(indices)
        grouped_indices.update(indices)

    for index in active_indices:
        if index in grouped_indices:
            continue
        if matched_payments[index]:
            classify([index], matched_payments[index], match_methods[index])
        else:
            results["PAGAMENTO NÃO LOCALIZADO"].append(labels[index])
            category_counts["PAGAMENTO NÃO LOCALIZADO"] += 1
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
        "VALOR RECEBIDO MAIOR QUE O TÍTULO",
    )
    category_counts: Counter[str] = Counter()
    try:
        results = reconcile(args.data_dir, category_counts)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    print(
        "01/02: mesmo CNPJ, vencimento e valor = um título; "
        "mesmo CNPJ/vencimento com valores diferentes = grupo."
    )
    print(
        "03: nosso_numero = documento; depois cliente ou CNPJ/tax_id em historico. "
        "Apenas tipo C."
    )
    for category in categories:
        items = results[category]
        print(f"\n{category} ({category_counts[category]})")
        for item in items:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
