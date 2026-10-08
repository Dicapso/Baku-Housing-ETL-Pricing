"""Generate a deliberately MESSY synthetic feed of Baku apartment listings (seed 42).

The raw file mimics a scraped property-portal export: mixed currencies and number
formats, unit suffixes, inconsistent district spellings, mixed date formats,
reposted duplicates, missing values and fat-finger outliers.
"""
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(42)
N = 6000
USD_AZN = 1.70

# district -> (base AZN per m², weight, metro share, spelling variants)
DISTRICTS = {
    "Sabail":    (3300, 0.06, 0.70, ["Səbail", "Sabail", "sebail r.", "SƏBAİL"]),
    "Nasimi":    (2700, 0.13, 0.85, ["Nəsimi", "Nasimi", "nesimi r.", "NƏSİMİ", "Nəsimi rayonu"]),
    "Yasamal":   (2350, 0.13, 0.75, ["Yasamal", "yasamal r.", "YASAMAL", "Yasamal rayonu"]),
    "Narimanov": (2400, 0.11, 0.70, ["Nərimanov", "Narimanov", "nerimanov", "NƏRİMANOV"]),
    "Khatai":    (2050, 0.12, 0.60, ["Xətai", "Khatai", "xetai r.", "XƏTAİ"]),
    "Nizami":    (1750, 0.09, 0.55, ["Nizami", "nizami r.", "NİZAMİ"]),
    "Binagadi":  (1350, 0.12, 0.30, ["Binəqədi", "Binagadi", "bineqedi", "BİNƏQƏDİ"]),
    "Khazar":    (1150, 0.06, 0.05, ["Xəzər", "Khazar", "xezer r."]),
    "Surakhani": (1050, 0.07, 0.10, ["Suraxanı", "Surakhani", "suraxani"]),
    "Sabunchu":  (1100, 0.07, 0.20, ["Sabunçu", "Sabunchu", "sabuncu r."]),
    "Garadagh":  ( 950, 0.04, 0.00, ["Qaradağ", "Garadagh", "qaradag"]),
}
names = list(DISTRICTS)
w = np.array([DISTRICTS[d][1] for d in names]); w = w / w.sum()

district = rng.choice(names, N, p=w)
rooms = rng.choice([1, 2, 3, 4, 5], N, p=[0.14, 0.36, 0.32, 0.14, 0.04])
area = np.round(rooms * 26 + 18 + rng.normal(0, 9, N), 1).clip(25, 260)
new_building = rng.random(N) < np.where(np.isin(district, ["Sabail", "Nasimi"]), 0.45, 0.62)
total_floors = np.where(new_building, rng.integers(9, 25, N), rng.choice([4, 5, 9, 12], N, p=[.25, .45, .2, .1]))
floor = np.array([rng.integers(1, t + 1) for t in total_floors])
renovated = rng.random(N) < np.where(new_building, 0.55, 0.70)
title_deed = rng.random(N) < np.where(new_building, 0.62, 0.93)
metro = rng.random(N) < np.array([DISTRICTS[d][2] for d in district])
listed = pd.Timestamp("2026-01-01") + pd.to_timedelta(rng.integers(0, 273, N), unit="D")

# true hedonic price model (multiplicative)
ppm = np.array([DISTRICTS[d][0] for d in district], dtype=float)
mult = (1
        * np.where(new_building, 1.10, 1.0)
        * np.where(renovated, 1.12, 1.0)
        * np.where(title_deed, 1.09, 1.0)
        * np.where(metro, 1.07, 1.0)
        * np.where(floor == 1, 0.92, 1.0)
        * np.where((floor == total_floors) & (total_floors > 1), 0.95, 1.0)
        * (1 + 0.007 * (listed.month.values - 1))          # ~0.7%/month market drift
        * (area / 80) ** -0.08)                             # bigger flats cheaper per m²
price_azn = np.round(area * ppm * mult * rng.lognormal(0, 0.12, N), -2)

df = pd.DataFrame({
    "listing_id": [f"L{100000 + i}" for i in range(N)],
    "district": district, "rooms": rooms, "area": area, "floor": floor,
    "total_floors": total_floors, "new_building": new_building, "renovated": renovated,
    "title_deed": title_deed, "metro_nearby": metro, "listed": listed, "price_azn": price_azn,
})

# ---------- make it messy ----------
def fmt_price(p):
    r = rng.random()
    if r < 0.18:   return f"${p / USD_AZN:,.0f}"                 # quoted in USD
    if r < 0.40:   return f"{p:,.0f} AZN".replace(",", " ")     # "125 000 AZN"
    if r < 0.50:   return f"{p / 1000:g}k AZN"                  # "125k AZN"
    if r < 0.60:   return f"{p:.0f} manat"
    return f"{p:.0f}"

def fmt_area(a):
    r = rng.random()
    if r < 0.35: return f"{a:g} m²"
    if r < 0.55: return f"{a:g}m2"
    if r < 0.70: return f"{a:g} kv.m".replace(".", ",", 1) if a % 1 else f"{a:g} kv.m"
    return f"{a:g}"

def fmt_bool(b, yes, no):
    if rng.random() < 0.04: return None
    return rng.choice(yes) if b else rng.choice(no)

raw = pd.DataFrame({
    "listing_id": df.listing_id,
    "district": [rng.choice(DISTRICTS[d][3]) for d in df.district],
    "rooms": df.rooms.astype(str),
    "area": [fmt_area(a) for a in df.area],
    "floor": [f"{f}/{t}" for f, t in zip(df.floor, df.total_floors)],
    "building": [fmt_bool(b, ["Yeni tikili", "new", "YENİ TİKİLİ"], ["Köhnə tikili", "old", "kohne tikili"]) for b in df.new_building],
    "renovated": [fmt_bool(b, ["Bəli", "yes", "var", "1"], ["Xeyr", "no", "yoxdur", "0"]) for b in df.renovated],
    "title_deed": [fmt_bool(b, ["var", "Bəli", "yes"], ["yoxdur", "Xeyr", "no"]) for b in df.title_deed],
    "metro_nearby": [fmt_bool(b, ["yes", "Bəli"], ["no", "Xeyr"]) for b in df.metro_nearby],
    "listed_date": [d.strftime("%d.%m.%Y") if rng.random() < 0.4 else d.strftime("%Y-%m-%d") for d in df.listed],
    "price": [fmt_price(p) for p in df.price_azn],
})

# missing values
for col, share in [("area", 0.015), ("rooms", 0.01), ("price", 0.008), ("district", 0.01)]:
    raw.loc[rng.random(N) < share, col] = None
# fat-finger outliers
idx = rng.choice(N, 25, replace=False); raw.loc[idx, "price"] = [f"{p * 10:.0f}" for p in df.price_azn[idx]]
idx = rng.choice(N, 12, replace=False); raw.loc[idx, "price"] = ["1", "100", "500", "1000"] * 3
idx = rng.choice(N, 15, replace=False); raw.loc[idx, "area"] = ["0", "8500", "1", "850 m²", "6"] * 3
idx = rng.choice(N, 8, replace=False);  raw.loc[idx, "rooms"] = "0"
idx = rng.choice(N, 10, replace=False); raw.loc[idx, "floor"] = [f"{t + 3}/{t}" for t in df.total_floors[idx]]  # floor > total
# reposts: same flat re-listed with new id (sometimes price tweaked) + a few exact dup rows
rep = raw.sample(300, random_state=1).copy()
rep["listing_id"] = [f"L{200000 + i}" for i in range(len(rep))]
rep["listed_date"] = (pd.to_datetime(df.listed[rep.index]) + pd.Timedelta(days=14)).dt.strftime("%Y-%m-%d").values
exact = raw.sample(60, random_state=2)
raw = pd.concat([raw, rep, exact]).sample(frac=1, random_state=3).reset_index(drop=True)
# whitespace noise
raw["district"] = raw.district.map(lambda s: f"  {s} " if isinstance(s, str) and rng.random() < 0.1 else s)

out = Path(__file__).parent / "raw_listings.csv"
raw.to_csv(out, index=False, encoding="utf-8")
print(f"Wrote {len(raw):,} raw rows -> {out}")
