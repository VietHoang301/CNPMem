#!/bin/bash
# 1. Tạo database và 3 tuyến xe mẫu
python create_my_routes.py
# ... các lệnh khác
python create_admin.py
# ...
# 2. Nạp trạm dừng từ CSV (Nếu file CSV của bạn nằm trong thư mục data)
# Lưu ý: Đảm bảo tên file CSV khớp chính xác với tên bạn đã upload lên GitHub
python scripts/seed_stops_from_csv.py --csv data/stops_tuyen_01.csv --route-code 01
python scripts/seed_stops_from_csv.py --csv data/stops_tuyen_03.csv --route-code 03
python scripts/seed_stops_from_csv.py --csv data/stops_tuyen_04.csv --route-code 04

# 3. Chạy web server
gunicorn app:app
