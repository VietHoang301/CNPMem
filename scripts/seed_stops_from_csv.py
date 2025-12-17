#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seed stops into SmartBus database from CSV.

CSV columns (header required):
route_code,direction,stop_order,stop_name,address,lat,lng

- direction must be DI or VE
- route_code is your display code (e.g., "01") stored in TuyenXe.maHienThi (adjust if yours differs)

Usage:
  python seed_stops_from_csv.py --csv data/stops_tuyen_01.csv --route-code 01 --mode upsert
  python seed_stops_from_csv.py --csv data/stops_tuyen_01.csv --route-code 01 --mode replace

Behavior with bad/missing coords:
- Default: WARN + skip bad rows (so you can seed the rest)
- If you want to fail fast: add --strict-coords
"""

import argparse
import csv
import os
import sys
from typing import Any, Dict, List, Optional, Tuple


# Ensure project root is on PYTHONPATH when running from scripts/
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def fail(msg: str, code: int = 2) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


def load_app():
    """
    Try to import your Flask app + db + models.
    You may need to edit these imports to match your project.
    """
    # Try common patterns
    try:
        from app import app, db, TuyenXe, TramDung  # type: ignore
        return app, db, TuyenXe, TramDung
    except Exception:
        pass

    try:
        from app import app, db  # type: ignore
        from models import TuyenXe, TramDung  # type: ignore
        return app, db, TuyenXe, TramDung
    except Exception:
        pass

    fail("Không import được app/db/models. Hãy mở file này và chỉnh hàm load_app() theo cấu trúc project của bạn.")


def _s(v: Any) -> str:
    return ("" if v is None else str(v)).strip()


def parse_int(v: Any, *, line_no: int, field: str) -> int:
    try:
        return int(_s(v))
    except Exception:
        raise ValueError(f"Dòng {line_no}: {field} không hợp lệ: {v!r}")


def parse_float_optional(v: Any) -> Optional[float]:
    """
    - Returns None if empty
    - Accepts '16,0123' -> 16.0123
    """
    t = _s(v)
    if t == "":
        return None
    t = t.replace(",", ".")
    return float(t)


def validate_lat_lng(lat: float, lng: float) -> bool:
    return (-90.0 <= lat <= 90.0) and (-180.0 <= lng <= 180.0)


RowT = Tuple[str, str, int, str, str, float, float]


def read_csv(
    path: str,
    *,
    strict_coords: bool = False,
    skip_bad_rows: bool = True,
) -> List[RowT]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {"route_code", "direction", "stop_order", "stop_name", "address", "lat", "lng"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            fail(f"CSV thiếu cột. Cần: {sorted(required)}. Đang có: {reader.fieldnames}")

        rows: List[RowT] = []
        skipped = 0

        for i, row in enumerate(reader, start=2):
            rc = _s(row.get("route_code"))
            direction = _s(row.get("direction")).upper()
            if direction not in ("DI", "VE"):
                msg = f"Dòng {i}: direction phải DI/VE. Nhận '{direction}'."
                if strict_coords or not skip_bad_rows:
                    fail(msg)
                warn(msg + " -> bỏ qua dòng.")
                skipped += 1
                continue

            try:
                order = parse_int(row.get("stop_order"), line_no=i, field="stop_order")
            except ValueError as e:
                if strict_coords or not skip_bad_rows:
                    fail(str(e))
                warn(str(e) + " -> bỏ qua dòng.")
                skipped += 1
                continue

            name = _s(row.get("stop_name"))
            addr = _s(row.get("address"))
            if not name:
                msg = f"Dòng {i}: stop_name rỗng."
                if strict_coords or not skip_bad_rows:
                    fail(msg)
                warn(msg + " -> bỏ qua dòng.")
                skipped += 1
                continue

            # Coords
            lat_raw = row.get("lat")
            lng_raw = row.get("lng")

            try:
                lat = parse_float_optional(lat_raw)
                lng = parse_float_optional(lng_raw)
            except Exception:
                msg = f"Dòng {i}: lat/lng không parse được: {lat_raw!r}, {lng_raw!r}"
                if strict_coords or not skip_bad_rows:
                    fail(msg)
                warn(msg + " -> bỏ qua dòng.")
                skipped += 1
                continue

            if lat is None or lng is None:
                msg = f"Dòng {i}: thiếu lat/lng: {lat_raw!r}, {lng_raw!r}"
                if strict_coords:
                    fail(msg)
                warn(msg + " -> bỏ qua dòng (hãy geocode lại hàng này).")
                skipped += 1
                continue

            if not validate_lat_lng(lat, lng):
                msg = f"Dòng {i}: lat/lng ngoài phạm vi: {lat}, {lng}"
                if strict_coords or not skip_bad_rows:
                    fail(msg)
                warn(msg + " -> bỏ qua dòng.")
                skipped += 1
                continue

            rows.append((rc, direction, order, name, addr, lat, lng))

        # Sort to keep deterministic insertion order
        rows.sort(key=lambda x: (x[1], x[2]))  # (direction, stop_order)

        if skipped > 0:
            warn(f"Tổng dòng bị bỏ qua: {skipped} (do thiếu/sai dữ liệu).")

        return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="Path to CSV")
    ap.add_argument("--route-code", required=True, help="Route display code, e.g., 01")
    ap.add_argument("--mode", choices=["upsert", "replace"], default="upsert")
    ap.add_argument(
        "--strict-coords",
        action="store_true",
        help="Fail ngay khi gặp lat/lng thiếu hoặc sai (mặc định: cảnh báo + bỏ qua dòng lỗi).",
    )
    args = ap.parse_args()

    app, db, TuyenXe, TramDung = load_app()
    rows = read_csv(args.csv, strict_coords=args.strict_coords, skip_bad_rows=True)

    if not rows:
        fail("Không có dòng hợp lệ nào để seed (check lại CSV/lat/lng).")

    with app.app_context():
        # Find route by maHienThi (adjust if your schema differs)
        tuyen = TuyenXe.query.filter_by(maHienThi=args.route_code).first()
        if not tuyen:
            fail(
                f"Không tìm thấy tuyến có maHienThi='{args.route_code}'. "
                "Hãy tạo tuyến trước hoặc chỉnh truy vấn trong script."
            )

        tuyen_id = getattr(tuyen, "maTuyen", None) or getattr(tuyen, "id", None)
        if not tuyen_id:
            fail("Không lấy được tuyen_id (maTuyen/id). Hãy chỉnh script để map đúng PK của TuyenXe.")

        # Replace: delete existing stops for both directions
        if args.mode == "replace":
            for direction in ("DI", "VE"):
                TramDung.query.filter_by(tuyen_id=tuyen_id, huong=direction).delete()
            db.session.commit()

        upserted = 0
        inserted = 0

        try:
            for rc, direction, order, name, addr, lat, lng in rows:
                existing = TramDung.query.filter_by(
                    tuyen_id=tuyen_id,
                    huong=direction,
                    thuTuTrenTuyen=order
                ).first()

                if existing:
                    existing.tenTram = name
                    existing.diaChi = addr
                    existing.lat = lat
                    existing.lng = lng
                    upserted += 1
                else:
                    stop = TramDung(
                        tenTram=name,
                        diaChi=addr,
                        thuTuTrenTuyen=order,
                        lat=lat,
                        lng=lng,
                        huong=direction,
                        tuyen_id=tuyen_id
                    )
                    db.session.add(stop)
                    inserted += 1

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            fail(f"DB error: {e}")

        print(f"[OK] route={args.route_code} inserted={inserted} updated={upserted} mode={args.mode}")


if __name__ == "__main__":
    main()
