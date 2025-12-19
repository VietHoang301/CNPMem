from app import app, db, TuyenXe

def create_manual_routes():
    with app.app_context():
        db.create_all()
        
        # Danh sách 3 tuyến xe bạn đang có dữ liệu
        routes_data = [
            {
                "code": "01",
                "name": "Đà Nẵng - Hội An",
                "start": "Bến xe Trung tâm Đà Nẵng",
                "end": "Bến xe Hội An"
            },
            {
                "code": "03",
                "name": "Đà Nẵng - Ái Nghĩa",
                "start": "Bến xe Trung tâm Đà Nẵng",
                "end": "Bến xe Ái Nghĩa"
            },
            {
                "code": "04",
                "name": "Đà Nẵng - Tam Kỳ",
                "start": "Bến xe Trung tâm Đà Nẵng",
                "end": "Bến xe Tam Kỳ"
            }
        ]

        print("--- Đang tạo các tuyến xe ---")
        for r in routes_data:
            # Kiểm tra xem tuyến đã có chưa để tránh tạo trùng
            existing = TuyenXe.query.filter_by(maHienThi=r["code"]).first()
            if not existing:
                new_route = TuyenXe(
                    maHienThi=r["code"],
                    tenTuyen=r["name"],
                    diemBatDau=r["start"],
                    diemKetThuc=r["end"]
                )
                db.session.add(new_route)
                print(f"✅ Đã tạo tuyến {r['code']}: {r['name']}")
            else:
                print(f"⚠️ Tuyến {r['code']} đã tồn tại, bỏ qua.")
        
        db.session.commit()
        print("--- Hoàn tất! ---")

if __name__ == "__main__":
    create_manual_routes()