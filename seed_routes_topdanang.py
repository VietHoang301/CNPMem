# seed_routes_topdanang.py
import re
import sys
import unicodedata
from typing import List, Dict, Tuple

import requests
from bs4 import BeautifulSoup

# Import từ app của bạn
from app import app, db, TuyenXe

URL = "https://topdanang.com.vn/danh-sach-cac-tuyen-xe-buyt-da-nang-cap-nhat/"

# Các tuyến mà bài viết ghi rõ là tạm ngưng / dừng hoạt động
# (để tránh seed nhầm nếu bài viết có nhắc lại)
SUSPENDED = {"05", "07", "08", "11", "12", "R14"}

def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    # Chuẩn hoá mũi tên nếu bị dính
    s = s.replace("↔", " ↔ ")
    s = re.sub(r"\s+↔\s+", " ↔ ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_code(raw: str) -> str:
    raw = _norm_text(raw).upper()
    # numeric: pad 2 chữ số (6 -> 06, 9 -> 09)
    if raw.isdigit():
        return f"{int(raw):02d}"
    return raw

def split_endpoints(title: str) -> Tuple[str, str]:
    t = _norm_text(title)
    # Ưu tiên split theo ↔
    parts = [p.strip() for p in t.split("↔") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    # Fallback: split theo " - "
    parts = [p.strip() for p in re.split(r"\s*-\s*", t) if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    # Không tách được thì đẩy hết vào start/end giống nhau (đỡ crash)
    return t, t

def scrape_routes() -> List[Dict[str, str]]:
    resp = requests.get(URL, timeout=25)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    routes: List[Dict[str, str]] = []

    # Trên trang, mỗi tuyến thường bắt đầu bằng heading kiểu:
    # "Xe buýt Đà Nẵng - Tuyến 01" / "Tuyến số 6" / "Tuyến R17A" / "Tuyến TMF"
    for h3 in soup.find_all(["h3"]):
        head = _norm_text(h3.get_text(" ", strip=True))
        if "XE BUÝT ĐÀ NẴNG" not in head.upper() or "TUYẾN" not in head.upper():
            continue

        m = re.search(r"TUYẾN(?:\s*SỐ)?\s*([A-Z0-9]+)", head.upper())
        if not m:
            continue

        code = normalize_code(m.group(1))

        # Bỏ các tuyến bị bài viết ghi dừng/tạm ngưng
        if code in SUSPENDED:
            continue

        # Tên tuyến thường là heading kế tiếp (h4) hoặc đoạn text đầu tiên chứa ↔
        title = None
        for sib in h3.next_siblings:
            if getattr(sib, "name", None) in ("h3", "h2"):
                break
            if not hasattr(sib, "get_text"):
                continue
            txt = _norm_text(sib.get_text(" ", strip=True))
            if "↔" in txt or " - " in txt:
                title = txt
                break

        if not title:
            continue

        start, end = split_endpoints(title)

        routes.append({
            "maHienThi": code,
            "tenTuyen": title,
            "diemBatDau": start,
            "diemKetThuc": end,
        })

    # Dedup theo maHienThi (giữ bản đầu)
    uniq: Dict[str, Dict[str, str]] = {}
    for r in routes:
        uniq.setdefault(r["maHienThi"], r)

    # Sort cho đẹp
    def sort_key(x: str):
        # numeric trước, alpha sau
        if x.isdigit():
            return (0, int(x))
        return (1, x)

    return sorted(uniq.values(), key=lambda r: sort_key(r["maHienThi"]))

def main():
    reset = "--reset" in sys.argv

    data = scrape_routes()
    if not data:
        print("Không scrape được tuyến nào. Trang có thể đổi cấu trúc HTML.")
        sys.exit(1)

    with app.app_context():
        db.create_all()

        if reset:
            # Xoá toàn bộ tuyến hiện có (chỉ làm khi bạn muốn DB sạch)
            TuyenXe.query.delete()
            db.session.commit()

        inserted = 0
        updated = 0

        for r in data:
            obj = TuyenXe.query.filter_by(maHienThi=r["maHienThi"]).first()
            if obj:
                obj.tenTuyen = r["tenTuyen"]
                obj.diemBatDau = r["diemBatDau"]
                obj.diemKetThuc = r["diemKetThuc"]
                updated += 1
            else:
                obj = TuyenXe(**r)
                db.session.add(obj)
                inserted += 1

        db.session.commit()

    print(f"OK. Inserted={inserted}, Updated={updated}, Total={len(data)}")
    print("Các tuyến đã seed:", ", ".join([r["maHienThi"] for r in data]))

if __name__ == "__main__":
    main()
