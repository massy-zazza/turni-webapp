from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List


BUSTA_RATE = 8.9759
FUORI_BUSTA_RATE = 10.0
FESTIVO_MULTIPLIER = 1.10
CONTRIBUTI_RATE = 13.09 / 137.33


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (Meeus/Jones/Butcher)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def italian_holidays(year: int) -> set[date]:
    """Main Italian public holidays, including Easter Monday."""
    pasqua = easter_sunday(year)
    pasquetta = pasqua + timedelta(days=1)
    return {
        date(year, 1, 1),   # Capodanno
        date(year, 1, 6),   # Epifania
        date(year, 4, 25),  # Liberazione
        date(year, 5, 1),   # Festa dei lavoratori
        date(year, 6, 2),   # Festa della Repubblica
        date(year, 8, 15),  # Ferragosto
        date(year, 11, 1),  # Ognissanti
        date(year, 12, 8),  # Immacolata
        date(year, 12, 25), # Natale
        date(year, 12, 26), # Santo Stefano
        pasqua,
        pasquetta,
    }


def parse_shift_day(day_s: str, time_s: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(f"{day_s} {time_s}", fmt)
        except ValueError:
            pass
    raise ValueError(f"Formato data/ora non valido: {day_s} {time_s}")


def overlap_hours(start: datetime, end: datetime, window_start_hour: int, window_end_hour: int) -> float:
    """Hours overlapped with [window_start_hour, window_end_hour) on the same day."""
    win_start = start.replace(hour=window_start_hour, minute=0, second=0, microsecond=0)
    win_end = start.replace(hour=window_end_hour, minute=0, second=0, microsecond=0)
    overlap_start = max(start, win_start)
    overlap_end = min(end, win_end)
    seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
    return seconds / 3600.0


@dataclass
class ShiftResult:
    data: str
    inizio: str
    fine: str
    ore_totali: float
    ore_19_22: float
    ore_fuori_fascia: float
    festivo: bool
    domenica: bool
    straordinario: bool
    tag: str
    paga_busta_lorda: float
    paga_fuori_busta: float
    lordo_busta_totale: float
    contributi_busta: float
    netto_busta: float
    guadagno_totale: float
    mese: str


def compute_shift(day_s: str, start_s: str, end_s: str) -> ShiftResult:
    start = parse_shift_day(day_s, start_s)
    end = parse_shift_day(day_s, end_s)

    if end <= start:
        raise ValueError(f"Il turno deve finire dopo l'inizio: {day_s} {start_s} -> {end_s}")

    total_hours = (end - start).total_seconds() / 3600.0

    day_date = start.date()
    weekday = day_date.weekday()  # Mon=0 ... Sun=6
    is_sunday = weekday == 6
    is_holiday = day_date in italian_holidays(day_date.year) or is_sunday
    multiplier = FESTIVO_MULTIPLIER if is_holiday else 1.0

    # Straordinario: ogni giorno diverso da venerdì/sabato/domenica
    # Fri=4, Sat=5, Sun=6
    is_straordinario = weekday not in {4, 5, 6}

    if is_straordinario:
        hours_19_22 = 0.0
        hours_outside = total_hours
    else:
        hours_19_22 = overlap_hours(start, end, 19, 22)
        hours_outside = total_hours - hours_19_22

    if is_straordinario and is_holiday:
        tag = "Straordinario • Festivo"
    elif is_straordinario:
        tag = "Straordinario"
    elif is_holiday:
        tag = "Festivo"
    else:
        tag = "Normale"

    pay_busta_lorda = hours_19_22 * BUSTA_RATE * multiplier
    pay_fuori = hours_outside * FUORI_BUSTA_RATE
    contributi_busta = pay_busta_lorda * CONTRIBUTI_RATE
    netto_busta = pay_busta_lorda - contributi_busta
    total_pay = netto_busta + pay_fuori

    return ShiftResult(
        data=day_s,
        inizio=start_s,
        fine=end_s,
        ore_totali=round(total_hours, 2),
        ore_19_22=round(hours_19_22, 2),
        ore_fuori_fascia=round(hours_outside, 2),
        festivo=is_holiday,
        domenica=is_sunday,
        straordinario=is_straordinario,
        tag=tag,
        paga_busta_lorda=round(pay_busta_lorda, 2),
        paga_fuori_busta=round(pay_fuori, 2),
        lordo_busta_totale=round(pay_busta_lorda, 2),
        contributi_busta=round(contributi_busta, 2),
        netto_busta=round(netto_busta, 2),
        guadagno_totale=round(total_pay, 2),
        mese=day_date.strftime("%Y-%m"),
    )


def load_csv(path: Path) -> List[ShiftResult]:
    results: List[ShiftResult] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"data", "inizio", "fine"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Mancano colonne nel CSV: {', '.join(sorted(missing))}")
        for idx, row in enumerate(reader, start=2):
            try:
                results.append(compute_shift(row["data"].strip(), row["inizio"].strip(), row["fine"].strip()))
            except Exception as e:
                raise ValueError(f"Errore alla riga {idx}: {e}") from e
    return results


def save_csv(path: Path, rows: Iterable[dict]) -> None:
    rows = list(rows)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

# Storico iniziale: febbraio 2026 caricato dai turni forniti dall'utente.
def update_historical_monthly_totals(path: Path, summary_rows: List[dict]) -> None:
    """Merge current monthly summary into a cumulative historical CSV, one row per month.

    The historical table is preloaded with February 2026 using the provided shifts:
    - ore totali: 25.50
    - lordo busta: 137.33
    - contributi: 13.09
    - netto busta: 124.24
    - fuori busta: 106.50
    - totale guadagno: 230.74
    """
    existing: dict[str, dict] = {
        "2026-02": {
            "mese": "2026-02",
            "ore_totali": 25.5,
            "tot_lordo_busta": 137.33,
            "tot_contributi_busta": 13.09,
            "tot_netto_busta": 124.24,
            "tot_fuori_busta": 106.5,
            "tot_guadagno": 230.74,
        }
    }

    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("mese") and row["mese"] != "TOTALE":
                    month_key = row["mese"]

                    # Mantieni le ore corrette se il file vecchio non le aveva
                    ore_val = row.get("ore_totali")
                    if ore_val in (None, "", 0, "0"):
                        ore_val = existing.get(month_key, {}).get("ore_totali", 0)

                    existing[month_key] = {
                        "mese": month_key,
                        "ore_totali": ore_val,
                        "tot_lordo_busta": row.get("tot_lordo_busta", 0) or 0,
                        "tot_contributi_busta": row.get("tot_contributi_busta", 0) or 0,
                        "tot_netto_busta": row.get("tot_netto_busta", 0) or 0,
                        "tot_fuori_busta": row.get("tot_fuori_busta", 0) or 0,
                        "tot_guadagno": row.get("tot_guadagno", 0) or 0,
                    }

    for row in summary_rows:
        month_key = row["mese"]
        existing[month_key] = {
            "mese": month_key,
            "ore_totali": row["ore_totali"],
            "tot_lordo_busta": row["tot_lordo_busta"],
            "tot_contributi_busta": row["tot_contributi_busta"],
            "tot_netto_busta": row["tot_netto_busta"],
            "tot_fuori_busta": row["tot_fuori_busta"],
            "tot_guadagno": row["tot_guadagno"],
        }

    ordered_rows = [existing[key] for key in sorted(existing)]

    # Calcolo totale guadagni e ore su tutti i mesi
    tot_ore_totali = sum(float(r["ore_totali"]) for r in ordered_rows)
    tot_lordo_busta = sum(float(r["tot_lordo_busta"]) for r in ordered_rows)
    tot_contributi_busta = sum(float(r["tot_contributi_busta"]) for r in ordered_rows)
    tot_netto_busta = sum(float(r["tot_netto_busta"]) for r in ordered_rows)
    tot_fuori_busta = sum(float(r["tot_fuori_busta"]) for r in ordered_rows)
    tot_guadagno = sum(float(r["tot_guadagno"]) for r in ordered_rows)

    ordered_rows.append({
        "mese": "TOTALE",
        "ore_totali": round(tot_ore_totali, 2),
        "tot_lordo_busta": round(tot_lordo_busta, 2),
        "tot_contributi_busta": round(tot_contributi_busta, 2),
        "tot_netto_busta": round(tot_netto_busta, 2),
        "tot_fuori_busta": round(tot_fuori_busta, 2),
        "tot_guadagno": round(tot_guadagno, 2),
    })

    save_csv(path, ordered_rows)


def monthly_summary(results: List[ShiftResult]) -> List[dict]:
    months = {}
    for r in results:
        m = months.setdefault(r.mese, {
            "mese": r.mese,
            "turni": 0,
            "ore_totali": 0.0,
            "ore_19_22": 0.0,
            "ore_fuori_fascia": 0.0,
            "tot_lordo_busta": 0.0,
            "tot_contributi_busta": 0.0,
            "tot_netto_busta": 0.0,
            "tot_fuori_busta": 0.0,
            "tot_guadagno": 0.0,
        })
        m["turni"] += 1
        m["ore_totali"] += r.ore_totali
        m["ore_19_22"] += r.ore_19_22
        m["ore_fuori_fascia"] += r.ore_fuori_fascia
        m["tot_lordo_busta"] += r.lordo_busta_totale
        m["tot_contributi_busta"] += r.contributi_busta
        m["tot_netto_busta"] += r.netto_busta
        m["tot_fuori_busta"] += r.paga_fuori_busta
        m["tot_guadagno"] += r.guadagno_totale

    out = []
    for key in sorted(months):
        row = months[key]
        for k in (
            "ore_totali",
            "ore_19_22",
            "ore_fuori_fascia",
            "tot_lordo_busta",
            "tot_contributi_busta",
            "tot_netto_busta",
            "tot_fuori_busta",
            "tot_guadagno",
        ):
            row[k] = round(row[k], 2)
        out.append(row)
    return out


def print_table(rows: List[dict], title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    if not rows:
        print("(vuoto)")
        return
    headers = list(rows[0].keys())
    widths = {h: len(h) for h in headers}
    for row in rows:
        for h in headers:
            widths[h] = max(widths[h], len(str(row[h])))

    header_line = " | ".join(h.ljust(widths[h]) for h in headers)
    sep = "-+-".join("-" * widths[h] for h in headers)
    print(header_line)
    print(sep)
    for row in rows:
        print(" | ".join(str(row[h]).ljust(widths[h]) for h in headers))


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python timesheet.py turni.csv")
        return 1

    input_path = Path(sys.argv[1]).expanduser().resolve()
    if not input_path.exists():
        print(f"File non trovato: {input_path}")
        return 1

    results = load_csv(input_path)
    detail_rows = [asdict(r) for r in results]
    summary_rows = monthly_summary(results)

    out_detail = input_path.with_name("turni_calcolati.csv")
    out_summary = input_path.with_name("riepilogo_mensile.csv")
    out_historical = input_path.with_name("guadagni_mensili_totali.csv")

    save_csv(out_detail, detail_rows)
    save_csv(out_summary, summary_rows)
    update_historical_monthly_totals(out_historical, summary_rows)

    print_table(detail_rows, "DETTAGLIO TURNI")
    print_table(summary_rows, "RIEPILOGO MENSILE")

    print(f"\nSalvati:")
    print(f"- {out_detail}")
    print(f"- {out_summary}")
    print(f"- {out_historical}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
