#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--route-code", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--direction", choices=["DI", "VE"], default=None)
    args = p.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    from app import app, TuyenXe, TramDung  # noqa

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        tuyen = TuyenXe.query.filter_by(maHienThi=args.route_code).first()
        if not tuyen:
            raise SystemExit(f"[ERROR] Không tìm thấy tuyến maHienThi='{args.route_code}' trong DB local")

        q = TramDung.query.filter_by(tuyen_id=tuyen.maTuyen)
        if args.direction:
            q = q.filter_by(huong=args.direction)

        stops = q.all()

        def norm_dir(x):
            x = (x or "").strip().upper()
            return x if x else "DI"

        stops = sorted(stops, key=lambda s: (norm_dir(s.huong), int(s.thuTuTrenTuyen or 0)))

        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["route_code", "direction", "stop_order", "stop_name", "address", "lat", "lng"])
            for s in stops:
                w.writerow([
                    args.route_code,
                    norm_dir(s.huong),
                    int(s.thuTuTrenTuyen),
                    s.tenTram or "",
                    s.diaChi or "",
                    float(s.lat),
                    float(s.lng),
                ])

    print(f"[OK] Exported {len(stops)} stops -> {out_path}")


if __name__ == "__main__":
    main()
