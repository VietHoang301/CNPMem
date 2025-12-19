# SmartBus (bus đô thị) — Flask + Jinja + SQLAlchemy + Leaflet + OSRM

SmartBus là web app demo cho bài toán **xe buýt đô thị**: quản lý tuyến/trạm/chuyến, tra cứu lộ trình theo **hướng DI/VE**, hiển thị **ETA dự kiến** (không GPS realtime), và quy trình **đăng ký/duyệt thẻ xe**.

## Tính năng chính

### Người dùng
- Xem danh sách tuyến và bản đồ tổng quan tuyến đang chọn.
- Xem chi tiết tuyến theo hướng `DI/VE`, danh sách trạm theo đúng thứ tự, ETA dự kiến cho từng trạm.
- Xem chi tiết chuyến, chi tiết trạm (trạm có thể liệt kê các chuyến sẽ đi qua).
- Đăng ký thẻ xe buýt (vé tháng/quý/năm) và theo dõi trạng thái.

### Admin
- Quản lý tuyến (thông tin hoạt động, tần suất, giá vé…).
- Quản lý trạm theo tuyến và hướng `DI/VE`.
- Quản lý chuyến theo tuyến (tự sinh chuyến theo tần suất/khung giờ + cho phép thêm/sửa/xóa).
- Quản lý thẻ xe (duyệt/kích hoạt/khóa…).

## Công nghệ
- Backend: Flask, SQLAlchemy (Flask-SQLAlchemy)
- DB local: SQLite (mặc định)
- Map: Leaflet
- Routing/ETA: OSRM (public server mặc định)

## Chạy local (Windows / macOS / Linux)

### 1) Yêu cầu
- Python **3.11+** (khuyến nghị)
- `pip`

### 2) Tạo môi trường ảo và cài dependency

Windows (PowerShell):
```powershell
cd smartbus
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux:
```bash
cd smartbus
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Chạy server
```bash
python app.py
```

Mở trình duyệt:
- `http://127.0.0.1:5000`

> Lần chạy đầu tiên sẽ tự tạo DB SQLite ở file `smartbus.db` (đang được `.gitignore`).

## Tài khoản mặc định (local)
- Với SQLite local, app tự tạo admin mặc định để demo:
  - Email: `admin@smartbus.local`
  - Password: `admin123`

> Khi deploy production (Postgres), admin **không** tự tạo trừ khi bạn set `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD`.

## Seed dữ liệu (tuyến/trạm)

### Seed danh sách tuyến (scrape TopDaNang)
Script: `scripts/seed_routes_topdanang.py` (cần internet)
```bash
python scripts/seed_routes_topdanang.py
```
Reset toàn bộ tuyến trước khi seed lại:
```bash
python scripts/seed_routes_topdanang.py --reset
```

### Seed trạm từ CSV
Script: `scripts/seed_stops_from_csv.py`
```bash
python scripts/seed_stops_from_csv.py --csv data/stops_tuyen_01.csv --route-code 01 --mode upsert
```

CSV format (header):
`route_code,direction,stop_order,stop_name,address,lat,lng`

### Export trạm ra CSV
Script: `scripts/export_stops_to_csv.py`
```bash
python scripts/export_stops_to_csv.py --route-code 01 --out data/stops_tuyen_01_export.csv
```

## Biến môi trường (ENV)

| ENV | Mặc định | Ý nghĩa |
|---|---|---|
| `DATABASE_URL` / `SQLALCHEMY_DATABASE_URI` | (trống) | Nếu trống → dùng SQLite `smartbus.db`. Khi deploy khuyến nghị Postgres. |
| `SECRET_KEY` | (có default trong code) | Bắt buộc set khi deploy (chuỗi random dài). |
| `DEFAULT_ADMIN_EMAIL` | (trống) | Tạo admin khi deploy (không nên dùng mặc định). |
| `DEFAULT_ADMIN_PASSWORD` | (trống) | Tạo admin khi deploy. |
| `OSRM_BASE_URL` | `https://router.project-osrm.org` | OSRM server. |
| `OSRM_PROFILE` | `driving` | Profile OSRM. |
| `OSRM_TIMEOUT` | `8` | Timeout gọi OSRM. |
| `OSRM_MAX_COORDS` | `70` | Giới hạn số điểm gửi OSRM (tránh timeout/413). |
| `BUS_SCHEDULE_HORIZON_MIN` | `360` | Tự sinh chuyến trong N phút sắp tới. |
| `BUS_OSRM_DURATION_FACTOR` | `1.25` | Nhân thời gian OSRM để mô phỏng bus chậm hơn xe hơi. |
| `BUS_STOP_DWELL_SEC` | `15` | Thời gian dừng mỗi trạm (ước tính). |
| `BUS_FALLBACK_SPEED_KMH` | `22` | Tốc độ fallback nếu OSRM lỗi. |

## Ghi chú về ETA (thực tế bus đô thị)
- ETA hiện tại là **ước tính** dựa trên: lịch chạy (headway) + thời gian di chuyển giữa trạm (OSRM) + thời gian dừng trạm.
- Dự án **không** có GPS realtime, vì vậy ETA có thể lệch so với thực tế.

## Deploy (Azure)
Hiện tại dự án ưu tiên chạy local. Khi sẵn sàng deploy Azure, xem hướng dẫn chi tiết tại:
- `DEPLOY.md`

Tóm tắt nguyên tắc:
- **Không** dùng SQLite trong production (Azure filesystem có thể không persistent).
- Dùng **Azure Database for PostgreSQL** và set `DATABASE_URL`.
- Khi dùng Postgres, bạn cần DB driver (`psycopg2-binary` hoặc `psycopg`). Nếu deploy báo thiếu module `psycopg2`/`psycopg`, hãy thêm driver vào `requirements.txt`.
- Set `SECRET_KEY` + `DEFAULT_ADMIN_EMAIL/PASSWORD`.
- Start command (App Service Linux): `gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000}`

## Troubleshooting nhanh
- Gặp lỗi thiếu cột / schema lộn xộn khi dev SQLite: thử dừng app và xóa file `smartbus.db` để tạo DB sạch (sau đó seed lại).
- Map/ETA không lên: kiểm tra internet/OSRM; hoặc set `OSRM_BASE_URL` về OSRM server của bạn.
