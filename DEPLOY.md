# Deploy SmartBus (gợi ý)

## Mục tiêu
- Chạy Flask qua WSGI (`gunicorn`)
- Dùng `DATABASE_URL` + `SECRET_KEY` từ env
- Tránh mất dữ liệu khi deploy (khuyến nghị Postgres)

## 0) Backup dữ liệu local (khuyên làm trước)
File dữ liệu local của bạn là `smartbus.db` (đang được `.gitignore`, nên **không** bị đẩy lên repo).

Backup nhanh (Windows):
```powershell
Copy-Item smartbus.db smartbus_backup_$(Get-Date -Format yyyyMMdd_HHmmss).db
```

Lưu ý: deploy lên web **không** tự xoá dữ liệu local trên máy bạn. Rủi ro “toang” thường xảy ra ở **production** nếu bạn dùng SQLite trên filesystem không persistent.

## 1) Chuẩn bị biến môi trường
Tối thiểu:
- `SECRET_KEY`: chuỗi ngẫu nhiên dài
- `DATABASE_URL`: khuyến nghị Postgres (Render/Railway thường cấp sẵn)

Khuyến nghị thêm (để an toàn):
- `DEFAULT_ADMIN_EMAIL`
- `DEFAULT_ADMIN_PASSWORD` (đặt mạnh, không dùng `admin123` khi deploy)

Tuỳ chọn:
- `OSRM_BASE_URL` (mặc định: `https://router.project-osrm.org`)
- `OSRM_PROFILE` (mặc định: `driving`)
- `OSRM_TIMEOUT` (mặc định: `8`)

## 2) Start command (production)
Repo đã có:
- `wsgi.py` (entrypoint)

Start command phổ biến:
```bash
gunicorn wsgi:app --bind 0.0.0.0:$PORT
```

## 3) Database: tránh “toang” khi deploy
### Khuyến nghị: Postgres
- Dễ backup/restore, phù hợp production.
- Chỉ cần set `DATABASE_URL` (app đã tự đọc).

### Nếu vẫn muốn SQLite
- Chỉ ổn khi nền tảng có **persistent disk/volume** gắn vào container.
- Nếu platform dùng filesystem ephemeral (deploy xong reset), `smartbus.db` sẽ bị mất.

## 4) Import dữ liệu lên production (tuỳ chọn)
Tuỳ mục tiêu demo:
- Demo nhanh: seed lại bằng CSV (`scripts/seed_stops_from_csv.py`).
- Muốn mang đúng dữ liệu local lên production: nên migrate sang Postgres (ưu tiên), tránh copy file `.db` lên host.

Bạn có thể bắt đầu bằng cách seed lại các tuyến/trạm (đủ để demo UI) rồi tính tiếp migration “xịn” sau.

## 5) Gợi ý nền tảng
### Render (dễ)
- Tạo Web Service từ repo
- Build: `pip install -r requirements.txt`
- Start: `gunicorn wsgi:app --bind 0.0.0.0:$PORT`
- Add Postgres + set `DATABASE_URL`, `SECRET_KEY`

### Railway (nhanh)
- Add Postgres plugin
- Set start command tương tự

---

## Deploy lên Azure (khuyến nghị)
Mục tiêu: **Azure App Service (Linux) + Azure Database for PostgreSQL (Flexible Server)** để dữ liệu không bị mất.

### A) Tạo PostgreSQL và lấy `DATABASE_URL`
1) Azure Portal → **Create a resource** → **Azure Database for PostgreSQL flexible server**.
2) Tạo server xong → vào **Databases** → tạo database (vd: `smartbus`).
3) Vào **Networking**:
   - Public access (hoặc private nếu bạn cấu hình VNet).
   - **Allow public access from your client IP** (để bạn seed/import từ máy local).
   - Có thể bật **Allow Azure services** nếu App Service truy cập theo kiểu public.
4) Vào **Connect** / **Connection strings** → copy thông tin host/user/password.
5) `DATABASE_URL` dạng (khuyên dùng SSL):
   ```
   postgresql://<USER>:<PASSWORD>@<HOST>:5432/<DBNAME>?sslmode=require
   ```
   Ví dụ host thường là: `<server-name>.postgres.database.azure.com`

### B) Tạo Web App (App Service) và cấu hình chạy Flask
1) Azure Portal → **Create a resource** → **Web App**.
2) Publish: **Code** (khuyên dùng cho dự án hiện tại).
3) Runtime stack: **Python 3.11**.
4) Tạo xong → vào Web App → **Configuration** → **Application settings** → Add:
   - `SECRET_KEY` (chuỗi random dài)
   - `DATABASE_URL` (ở bước A)
   - `DEFAULT_ADMIN_EMAIL`
   - `DEFAULT_ADMIN_PASSWORD` (đặt mạnh)
5) Vào **Configuration** → **General settings** → **Startup Command**:
   ```
   gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000}
   ```
6) Deploy code:
   - Cách dễ: **Deployment Center** → GitHub → chọn repo/branch → Save → chờ build.

### C) Seed dữ liệu lên Azure Postgres (chạy từ máy bạn)
Vì `scripts/seed_stops_from_csv.py` import `app.py`, bạn chỉ cần trỏ env về Azure Postgres rồi chạy seed:
```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
python scripts/seed_stops_from_csv.py --csv data/stops_tuyen_01.csv --route-code 01 --mode upsert
```

Gợi ý: tạo tuyến trước (Admin → Tuyến) rồi seed trạm sau.
