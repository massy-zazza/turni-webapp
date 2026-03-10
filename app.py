import csv
from pathlib import Path
from datetime import datetime, time
import streamlit as st

from timesheet import load_csv, monthly_summary

DATA_FILE = Path("turni.csv")
DETAIL_FILE = Path("turni_calcolati.csv")
SUMMARY_FILE = Path("riepilogo_mensile.csv")
HISTORICAL_FILE = Path("guadagni_mensili_totali.csv")


def ensure_csv_exists() -> None:
    if not DATA_FILE.exists():
        with DATA_FILE.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["data", "inizio", "fine"])


def append_shift(day_str: str, start_str: str, end_str: str) -> None:
    ensure_csv_exists()
    with DATA_FILE.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([day_str, start_str, end_str])


def read_csv_as_dicts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def save_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    rows = list(rows)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []

    with path.open("w", encoding="utf-8", newline="") as f:
        if not fieldnames:
            return
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if rows:
            writer.writerows(rows)


def delete_shifts_for_month(year: int, month: int) -> int:
    ensure_csv_exists()
    rows = read_csv_as_dicts(DATA_FILE)
    kept = []
    removed = 0

    prefix = f"{year:04d}-{month:02d}-"

    for row in rows:
        if row.get("data", "").startswith(prefix):
            removed += 1
        else:
            kept.append(row)

    with DATA_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["data", "inizio", "fine"])
        for r in kept:
            writer.writerow([r["data"], r["inizio"], r["fine"]])

    return removed


def delete_month_from_historical(year: int, month: int) -> None:
    if not HISTORICAL_FILE.exists():
        return

    rows = read_csv_as_dicts(HISTORICAL_FILE)
    month_key = f"{year:04d}-{month:02d}"

    kept = [r for r in rows if r.get("mese") not in (month_key, "TOTALE")]

    fieldnames = [
        "mese",
        "ore_totali",
        "tot_lordo_busta",
        "tot_contributi_busta",
        "tot_netto_busta",
        "tot_fuori_busta",
        "tot_guadagno",
    ]

    with HISTORICAL_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        if kept:
            writer.writerows(kept)


def regenerate_outputs() -> None:
    ensure_csv_exists()
    results = load_csv(DATA_FILE)
    detail_rows = [r.__dict__ for r in results]
    summary_rows = monthly_summary(results)

    detail_fieldnames = [
        "data",
        "inizio",
        "fine",
        "ore_totali",
        "ore_19_22",
        "ore_fuori_fascia",
        "festivo",
        "domenica",
        "straordinario",
        "tag",
        "paga_busta_lorda",
        "paga_fuori_busta",
        "lordo_busta_totale",
        "contributi_busta",
        "netto_busta",
        "guadagno_totale",
        "mese",
    ]

    summary_fieldnames = [
        "mese",
        "turni",
        "ore_totali",
        "ore_19_22",
        "ore_fuori_fascia",
        "tot_lordo_busta",
        "tot_contributi_busta",
        "tot_netto_busta",
        "tot_fuori_busta",
        "tot_guadagno",
    ]

    save_csv(DETAIL_FILE, detail_rows, detail_fieldnames)
    save_csv(SUMMARY_FILE, summary_rows, summary_fieldnames)
    # scrive lo storico solo dai mesi realmente presenti nei dati
    historical_fieldnames = [
        "mese",
        "ore_totali",
        "tot_lordo_busta",
        "tot_contributi_busta",
        "tot_netto_busta",
        "tot_fuori_busta",
        "tot_guadagno",
    ]

    historical_rows = [
        {
            "mese": row["mese"],
            "ore_totali": row["ore_totali"],
            "tot_lordo_busta": row["tot_lordo_busta"],
            "tot_contributi_busta": row["tot_contributi_busta"],
            "tot_netto_busta": row["tot_netto_busta"],
            "tot_fuori_busta": row["tot_fuori_busta"],
            "tot_guadagno": row["tot_guadagno"],
        }
        for row in summary_rows
    ]

    save_csv(HISTORICAL_FILE, historical_rows, historical_fieldnames)


st.set_page_config(page_title="Turni lavoro", layout="wide")
st.title("Gestione turni lavoro")

ensure_csv_exists()

with st.form("nuovo_turno"):
    st.subheader("Aggiungi turno")

    col1, col2, col3 = st.columns(3)

    with col1:
        data = st.date_input("Data", value=datetime.today().date())

    with col2:
        inizio = st.time_input("Ora inizio", value=time(17, 30), step=1800)

    with col3:
        fine = st.time_input("Ora fine", value=time(22, 30), step=1800)

    submitted = st.form_submit_button("Aggiungi turno")

    if submitted:
        try:
            append_shift(
                data.strftime("%Y-%m-%d"),
                inizio.strftime("%H:%M"),
                fine.strftime("%H:%M"),
            )

            regenerate_outputs()

            st.success("Turno aggiunto correttamente")
            st.rerun()

        except Exception as e:
            st.error(f"Errore: {e}")


try:
    regenerate_outputs()
except Exception as e:
    st.error(f"Errore nel ricalcolo dei file: {e}")


st.subheader("Turni inseriti")
turni_rows = read_csv_as_dicts(DATA_FILE)

if turni_rows:
    st.dataframe(turni_rows, use_container_width=True)
else:
    st.dataframe([], use_container_width=True)
    st.caption("Nessun turno inserito")


st.subheader("Dettaglio turni calcolati")
detail_rows = read_csv_as_dicts(DETAIL_FILE)

if detail_rows:
    st.dataframe(detail_rows, use_container_width=True)
else:
    st.dataframe([], use_container_width=True)
    st.caption("Nessun dettaglio disponibile")


st.subheader("Riepilogo mensile")
summary_rows = read_csv_as_dicts(SUMMARY_FILE)

if summary_rows:
    st.dataframe(summary_rows, use_container_width=True)
else:
    st.dataframe([], use_container_width=True)
    st.caption("Nessun riepilogo disponibile")


st.subheader("Storico mensile totale")
historical_rows = read_csv_as_dicts(HISTORICAL_FILE)

if historical_rows:
    st.dataframe(historical_rows, use_container_width=True)
else:
    st.dataframe([], use_container_width=True)
    st.caption("Nessuno storico disponibile")


st.subheader("Azioni rapide")

month_names = {
    1: "gennaio",
    2: "febbraio",
    3: "marzo",
    4: "aprile",
    5: "maggio",
    6: "giugno",
    7: "luglio",
    8: "agosto",
    9: "settembre",
    10: "ottobre",
    11: "novembre",
    12: "dicembre",
}

col1, col2, col3 = st.columns([1, 1, 2])

with col1:
    reset_year = st.number_input("Anno da azzerare", min_value=2020, max_value=2100, value=datetime.today().year, step=1)

with col2:
    reset_month = st.selectbox(
        "Mese da azzerare",
        options=list(month_names.keys()),
        format_func=lambda m: month_names[m].capitalize(),
    )

with col3:
    st.caption("Questo elimina tutti i turni del mese scelto e cancella il mese anche dallo storico.")

if st.button("Azzera mese selezionato"):
    try:
        removed = delete_shifts_for_month(int(reset_year), int(reset_month))
        delete_month_from_historical(int(reset_year), int(reset_month))
        regenerate_outputs()

        st.success(
            f"Eliminati {removed} turni di {month_names[int(reset_month)]} {int(reset_year)}"
        )

        st.rerun()

    except Exception as e:
        st.error(f"Errore nell'azzeramento: {e}")