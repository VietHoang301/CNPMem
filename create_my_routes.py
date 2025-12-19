from app import app, db, TuyenXe

def create_manual_routes():
    with app.app_context():
        db.create_all()
        
        # Danh sách tuyến xe KÈM CẤU HÌNH THỜI GIAN
        routes_data = [
            {
                "code": "01",
                "name": "Đà Nẵng - Hội An",
                "start": "Bến xe Trung tâm Đà Nẵng",
                "end": "Bến xe Hội An",
                "hours": "05:30 - 17:50",  # Chạy từ 5h30 đến 17h50
                "freq": 20                # 20 phút/chuyến
            },
            {
                "code": "03",
                "name": "Đà Nẵng - Ái Nghĩa",
                "start": "Bến xe Trung tâm Đà Nẵng",
                "end": "Bến xe Ái Nghĩa",
                "hours": "05:30 - 17:00",
                "freq": 30                # 30 phút/chuyến
            },
            {
                "code": "04",
                "name": "Đà Nẵng - Tam Kỳ",
                "start": "Bến xe Trung tâm Đà Nẵng",
                "end": "Bến xe Tam Kỳ",
                "hours": "05:00 - 18:00",
                "freq": 15                # 15 phút/chuyến (Tuyến này đông khách)
            }
        ]

        print("--- Đang tạo/cập nhật các tuyến xe và lịch trình ---")
        
        for r in routes_data:
            # Tính toán sơ bộ số chuyến mỗi ngày để lưu vào DB (dùng để hiển thị)
            # Công thức ước lượng: (18h - 5h) * 60 phút / tần suất
            so_chuyen_uoc_tinh = int((13 * 60) / r["freq"])

            # Kiểm tra xem tuyến đã có chưa
            tuyen = TuyenXe.query.filter_by(maHienThi=r["code"]).first()
            
            if not tuyen:
                # TẠO MỚI nếu chưa có
                new_route = TuyenXe(
                    maHienThi=r["code"],
                    tenTuyen=r["name"],
                    diemBatDau=r["start"],
                    diemKetThuc=r["end"],
                    # Thêm các trường thời gian
                    thoiGianHoatDong=r["hours"],
                    tanSuatPhut=r["freq"],
                    soChuyenMoiNgay=so_chuyen_uoc_tinh
                )
                db.session.add(new_route)
                print(f"✅ Đã tạo MỚI tuyến {r['code']} (Tần suất: {r['freq']}p)")
            else:
                # CẬP NHẬT nếu đã có (Quan trọng: Để sửa giờ chạy mà không cần xóa DB)
                tuyen.thoiGianHoatDong = r["hours"]
                tuyen.tanSuatPhut = r["freq"]
                tuyen.soChuyenMoiNgay = so_chuyen_uoc_tinh
                # Cập nhật lại tên và điểm đầu cuối phòng khi bạn sửa đổi
                tuyen.tenTuyen = r["name"]
                tuyen.diemBatDau = r["start"]
                tuyen.diemKetThuc = r["end"]
                print(f"🔄 Đã CẬP NHẬT tuyến {r['code']} (Giờ: {r['hours']})")
        
        db.session.commit()
        print("--- Hoàn tất! ---")

if __name__ == "__main__":
    create_manual_routes()
