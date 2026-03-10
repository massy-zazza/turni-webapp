from datetime import datetime, time
from io import StringIO
from pathlib import Path
import csv

import streamlit as st
from supabase import Client, create_client

from timesheet import load_csv, monthly_summary

SUPABASE_URL = st.secrets.get("SUPABASE_URL", "https://zuybwlgvjhmufqujpebo.supabase.co")
# Use the ANON public key from Supabase (NOT the publishable key)
SUPABASE_KEY = st.secrets["SUPABASE_ANON_KEY"]

DATA_FILE = Path("turni.csv")
DETAIL_FILE = Path("turni_calcolati.csv")
SUMMARY_FILE = Path("riepilogo_mensile.csv")
HISTORICAL_FILE = Path("guadagni_mensili_totali.csv")


@st.cache_resource
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _rows_to_results(rows: list[dict]):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["data", "inizio", "fine"])
    for row in rows:
        writer.writerow([row["data"], row["inizio"], row["fine"]])
    buffer.seek(0)

    tmp_path = Path("_tmp_turni_from_db.csv")
    tmp_path.write_text(buffer.getvalue(), encoding="utf-8")
    return load_csv(tmp_path)


def fetch_turni_rows() -> list[dict]:
    supabase = get_supabase()
    response = (
        supabase.table("turni")
        .select("id,data,inizio,fine,created_at")
        .order("data")
        .order("inizio")
        .execute()
    )
    return response.data or []


def append_shift(day_str: str, start_str: str, end_str: str):
    supabase = get_supabase()
    response = (
        supabase.table("turni")
        .insert(
            {
                "data": day_str,
                "inizio": start_str,
                "fine": end_str,
            }
        )
        .execute()
    )
    return response


def delete_shifts_for_month(year: int, month: int) -> int:
    supabase = get_supabase()
    month_prefix = f"{year:04d}-{month:02d}"
    rows = (
        supabase.table("turni")
        .select("id,data")
        .gte("data", f"{month_prefix}-01")
        .lt("data", f"{year + 1:04d}-01-01" if month == 12 else f"{year:04d}-{month + 1:02d}-01")
        .execute()
        .data
        or []
    )

    ids = [row["id"] for row in rows if str(row.get("data", "")).startswith(month_prefix)]
    if ids:
        supabase.table("turni").delete().in_("id", ids).execute()
    return len(ids)


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


def regenerate_outputs() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    db_rows = fetch_turni_rows()

    basic_turni_rows = [
        {
            "id": row["id"],
            "data": row["data"],
            "inizio": str(row["inizio"])[:5],
            "fine": str(row["fine"])[:5],
        }
        for row in db_rows
    ]

    results = _rows_to_results(basic_turni_rows) if basic_turni_rows else []
    detail_rows = [r.__dict__ for r in results]
    summary_rows = monthly_summary(results) if results else []

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

    save_csv(DETAIL_FILE, detail_rows, detail_fieldnames)
    save_csv(SUMMARY_FILE, summary_rows, summary_fieldnames)
    save_csv(HISTORICAL_FILE, historical_rows, historical_fieldnames)
    return basic_turni_rows, detail_rows, summary_rows, historical_rows


st.set_page_config(page_title="Turni lavoro", layout="wide")
st.title("Gestione turni lavoro")
st.caption("I turni sono salvati su Supabase.")

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
            st.success("Turno aggiunto correttamente")
            st.rerun()
        except Exception as e:
            st.error(f"Errore: {e}")

try:
    turni_rows, detail_rows, summary_rows, historical_rows = regenerate_outputs()
except Exception as e:
    st.error(f"Errore nel ricalcolo dei file o nel collegamento a Supabase: {e}")
    turni_rows, detail_rows, summary_rows, historical_rows = [], [], [], []

st.subheader("Turni inseriti")
if turni_rows:
    st.dataframe(turni_rows, use_container_width=True)
else:
    st.dataframe([], use_container_width=True)
    st.caption("Nessun turno inserito")

st.subheader("Dettaglio turni calcolati")
if detail_rows:
    st.dataframe(detail_rows, use_container_width=True)
else:
    st.dataframe([], use_container_width=True)
    st.caption("Nessun dettaglio disponibile")

st.subheader("Riepilogo mensile")
if summary_rows:
    st.dataframe(summary_rows, use_container_width=True)
else:
    st.dataframe([], use_container_width=True)
    st.caption("Nessun riepilogo disponibile")

st.subheader("Storico mensile totale")
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
    st.caption("Questo elimina tutti i turni del mese scelto dal database Supabase.")

if st.button("Azzera mese selezionato"):
    try:
        removed = delete_shifts_for_month(int(reset_year), int(reset_month))
        st.success(
            f"Eliminati {removed} turni di {month_names[int(reset_month)]} {int(reset_year)}"
        )
        st.rerun()
    except Exception as e:
        st.error(f"Errore nell'azzeramento: {e}")
