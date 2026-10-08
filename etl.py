"""ETL pipeline: raw Baku listings feed -> clean, validated table (CSV + SQLite).

Usage:  python etl.py
Each step is a small pure function so the notebook can show its effect.
"""
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

USD_AZN = 1.70
ROOT = Path(__file__).parent

DISTRICT_MAP = {  # ascii-folded lowercase stem -> canonical name
    "sebail": "Sabail", "sabail": "Sabail", "nesimi": "Nasimi", "nasimi": "Nasimi",
    "yasamal": "Yasamal", "nerimanov": "Narimanov", "narimanov": "Narimanov",
    "xetai": "Khatai", "khatai": "Khatai", "nizami": "Nizami",
    "bineqedi": "Binagadi", "binagadi": "Binagadi", "xezer": "Khazar", "khazar": "Khazar",
    "suraxani": "Surakhani", "surakhani": "Surakhani", "sabuncu": "Sabunchu",
    "sabunchu": "Sabunchu", "qaradag": "Garadagh", "garadagh": "Garadagh",
}
AZ_FOLD = str.maketrans("əƏıİöÖüÜçÇşŞğĞ", "eEiIoOuUcCsSgG")
YES = {"beli", "yes", "var", "1", "true", "new", "yeni tikili"}      # ascii-folded
NO = {"xeyr", "no", "yoxdur", "0", "false", "old", "kohne tikili"}

# plausibility rules used both for cleaning and for the validation report
RULES = {"area": (15, 400), "price_azn": (15_000, 3_000_000), "price_per_m2": (400, 9_000)}


def load_raw(path=ROOT / "data" / "raw_listings.csv") -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=True)


def norm_district(s):
    if not isinstance(s, str) or not s.strip():
        return np.nan
    key = s.strip().translate(AZ_FOLD).lower()
    key = re.sub(r"\s*(r\.|rayonu)$", "", key).strip()
    return DISTRICT_MAP.get(key, np.nan)


def parse_price(s):
    """'$41,765' | '117 500 AZN' | '77.8k AZN' | '188300 manat' | '343400' -> AZN float."""
    if not isinstance(s, str):
        return np.nan
    t = s.strip().lower()
    usd = t.startswith("$") or "usd" in t
    k = bool(re.search(r"\dk\b", t))
    num = re.sub(r"[^\d.]", "", t.replace(",", ""))
    if not num:
        return np.nan
    v = float(num) * (1000 if k else 1)
    return v * USD_AZN if usd else v


def parse_area(s):
    """'85 m²' | '85m2' | '98,7 kv.m' | '85' -> float m²."""
    if not isinstance(s, str):
        return np.nan
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)", s)
    return float(m.group(1).replace(",", ".")) if m else np.nan


def parse_bool(s):
    if not isinstance(s, str):
        return pd.NA
    t = s.strip().translate(AZ_FOLD).lower()  # fold first: "İ".lower() adds a combining dot
    return True if t in YES else False if t in NO else pd.NA


def parse_date(s):
    return pd.to_datetime(s, format="%d.%m.%Y", errors="coerce") if "." in str(s) \
        else pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")


def standardize(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({"listing_id": raw.listing_id.str.strip()})
    df["district"] = raw.district.map(norm_district)
    df["rooms"] = pd.to_numeric(raw.rooms, errors="coerce").astype("Int64")
    df["area"] = raw.area.map(parse_area)
    fl = raw.floor.str.extract(r"(\d+)\s*/\s*(\d+)").astype(float)
    df["floor"], df["total_floors"] = fl[0].astype("Int64"), fl[1].astype("Int64")
    df["new_building"] = raw.building.map(parse_bool).astype("boolean")
    for c in ["renovated", "title_deed", "metro_nearby"]:
        df[c] = raw[c].map(parse_bool).astype("boolean")
    df["listed_date"] = raw.listed_date.map(parse_date)
    df["price_azn"] = raw.price.map(parse_price).round(-1)
    df["price_was_usd"] = raw.price.fillna("").str.strip().str.startswith("$")
    return df


def deduplicate(df: pd.DataFrame):
    """Drop exact duplicate rows, then reposts (same flat, new id): keep the earliest listing."""
    n0 = len(df)
    df = df.drop_duplicates()
    n_exact = n0 - len(df)
    key = ["district", "rooms", "area", "floor", "total_floors", "price_azn"]
    df = df.sort_values("listed_date")
    dup = df.duplicated(key, keep="first") & df[key].notna().all(axis=1)
    return df[~dup].sort_index(), {"exact_duplicates": n_exact, "reposts": int(dup.sum())}


def flag_invalid(df: pd.DataFrame) -> pd.DataFrame:
    """Return a boolean frame: one column per failed rule (True = row breaks the rule)."""
    ppm = df.price_azn / df.area
    lo, hi = RULES["area"]; plo, phi = RULES["price_azn"]; mlo, mhi = RULES["price_per_m2"]
    return pd.DataFrame({
        "missing_key_field": df[["district", "rooms", "area", "price_azn"]].isna().any(axis=1),
        "area_out_of_range": ~df.area.between(lo, hi) & df.area.notna(),
        "price_out_of_range": ~df.price_azn.between(plo, phi) & df.price_azn.notna(),
        "price_per_m2_implausible": ~ppm.between(mlo, mhi) & ppm.notna(),
        "zero_rooms": df.rooms.eq(0).fillna(False).astype(bool),
        "floor_above_total": (df.floor > df.total_floors).fillna(False).astype(bool),
    }, index=df.index)


def transform(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["price_per_m2"] = (df.price_azn / df.area).round(0)
    df["first_floor"] = df.floor.eq(1)
    df["top_floor"] = df.floor.eq(df.total_floors) & df.total_floors.gt(1)
    df["listed_month"] = df.listed_date.dt.to_period("M").astype(str)
    return df


def run(write=True):
    raw = load_raw()
    std = standardize(raw)
    dd, dup_stats = deduplicate(std)
    flags = flag_invalid(dd)
    clean = transform(dd[~flags.any(axis=1)]).reset_index(drop=True)
    if write:
        clean.to_csv(ROOT / "data" / "clean_listings.csv", index=False)
        with sqlite3.connect(ROOT / "data" / "listings.db") as con:
            clean.assign(listed_date=clean.listed_date.dt.strftime("%Y-%m-%d")) \
                 .to_sql("listings", con, if_exists="replace", index=False)
    return raw, std, dd, flags, clean, dup_stats


if __name__ == "__main__":
    raw, std, dd, flags, clean, dup = run()
    print(f"raw {len(raw):,} -> dedup {len(dd):,} {dup} -> clean {len(clean):,}")
    print(flags.sum())
