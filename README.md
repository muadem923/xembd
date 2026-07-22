# Chuối Chiên + Lương Sơn + Gà Vàng + Xôi Lạc Multi-Source Scanner v4.4.11

Bản v4.4.11 sửa riêng adapter **Lương Sơn**: gộp card trùng theo cặp đội + lịch, thử URL/card thay thế của cùng trận, và tự chuyển từ `catbee.io` sang `hygenie.io` khi trận gần giờ/đang live ở miền đầu quét ra 0 stream. Chuối Chiên, Gà Vàng, Xôi Lạc và định dạng `all_live.m3u` giữ nguyên.

## Điểm chính

- Một playlist tổng duy nhất: `all_live.m3u`.
- Nhóm nguồn qua `group-title`: `Chuối Chiên`, `Lương Sơn`, `Gà Vàng`, `Xôi Lạc`.
- Bốn scanner chạy trong process độc lập; mặc định tối đa 3 Chromium chạy đồng thời để không quá tải GitHub runner.
- Xôi Lạc quét từng `/link/N` để giữ nhiều BLV/kênh.
- Ưu tiên FLV/M3U8 có `wsSecret` còn hạn; hỗ trợ thời hạn decimal hoặc hexadecimal.
- Loại type/8/live2 không secret để tránh banner quảng cáo.
- URL signed bị runner 403 vẫn có thể được giữ nếu còn hạn và đã được browser quan sát.
- M3U giữ Referer, Origin, User-Agent bằng `#EXTHTTP` và `#EXTVLCOPT`.
- Token được kiểm tra lại ngay trước khi ghi playlist.
- Toàn bộ cơ chế Gà Vàng pending, logo và metadata từ v4.4.8 được giữ nguyên.

## Chạy toàn bộ

```bash
python -u main.py
```

## Chạy riêng Xôi Lạc

```bash
python -u sources/xoilac.py
```

Hoặc test riêng một trang trận:

```bash
python -u main.py --source xoilac "URL_TRẬN_XÔI_LẠC"
```

## Cấu hình Xôi Lạc quan trọng

```text
MULTI_SOURCE_MAX_WORKERS=3
XOILAC_HOME_URLS=https://xoilacz.io/,https://malaysiandigest.com/,https://altenergystocks.com/
XOILAC_SOURCE_WAIT_SECONDS=12
XOILAC_MAX_MATCHES=5
XOILAC_MAX_SOURCES_PER_MATCH=4
XOILAC_TOKEN_REFRESH_ATTEMPTS=2
XOILAC_MIN_TOKEN_SECONDS=600
XOILAC_SCAN_PAST_MINUTES=150
XOILAC_SCAN_FUTURE_MINUTES=240
XOILAC_VERIFY_STREAMS=1
XOILAC_WRITE_AUDIT_M3U=0
```

## File đầu ra

Sau khi `main.py` gộp xong, chỉ còn:

- `all_live.m3u`
- `all_live_debug.json`
- các state JSON của nguồn có delta scan

Playlist riêng của từng nguồn chỉ là file tạm và tự bị xóa.


## Sửa lỗi v4.4.10

- `save_state()` nhận thêm tham số tùy chọn `now`, hoàn toàn tương thích với lời gọi cũ.
- Unit test delta state dùng cùng một mốc thời gian cố định cho cả cập nhật và lưu state.
- Bổ sung test biên xác nhận chỉ xóa bản ghi cũ hơn 2 ngày, không xóa bản ghi đúng tại ngưỡng.
- Không thay đổi cửa sổ quét, cách lấy link, metadata, logo, BLV hoặc merger của bốn nguồn.

- Workflow giữ lịch tự chạy mỗi 30 phút bằng `cron: "*/30 * * * *"`, đồng thời vẫn hỗ trợ chạy tay.


## Sửa Lương Sơn v4.4.11

- Gộp card SEO/URL trùng theo hai đội và giờ thi đấu; các lượt tái đấu khác ngày/giờ không bị gộp.
- Không xóa URL thay thế: lưu tối đa các biến thể cùng trận và chỉ thử khi URL ưu tiên ra 0 stream.
- Nếu trận gần giờ/đang live vẫn 0 stream trên miền đầu, tự thu thập miền dự phòng và quét đúng trận tương ứng.
- Chỉ failover cho trận từ `-150` phút đến `+45` phút hoặc card có nhãn LIVE; trận còn xa không bị mở thêm Chromium.
- Khi miền dự phòng bắt được stream, giữ ID/trạng thái của trận gốc nhưng dùng Referer/Origin thật của miền đã phát.
- Debug ghi `variant_failover`, `variant_failover_attempts`, `domain_failover` hoặc `domain_failover_attempts`.

Cấu hình liên quan:

```text
HYGENIE_DOMAIN_STREAM_FAILOVER=1
HYGENIE_DOMAIN_FAILOVER_NEAR_MINUTES=45
HYGENIE_MATCH_VARIANT_FALLBACKS=2
```
