# Báo cáo rà soát `chunks_format_final`

Ngày rà soát: 14/10/2026  |  Strategy: `format`  |  Profile: `format-v1`  |  Cleaner: `verbatim-v4`

## Kết luận

**Output dùng được làm bản chunk thử nghiệm, nhưng chưa nên coi là corpus retrieval đã sạch/đạt nghiệm thu.** Điểm mạnh là ID/URL được giữ, chunk text lấy nguyên lát cắt từ source đã làm sạch, và phần lớn chunk nằm trong ngân sách. Các vấn đề cần xử lý trước khi đưa vào index chính là 52 chuỗi lỗi Crawl4AI đang được coi như nội dung, 1.267 chunk vượt 300 custom units (trong đó có chunk 10.959 units), một số profile bị nhận diện quá rộng và dữ liệu generic gần như chỉ là title/snippet/lỗi crawl.

Kết luận này dựa trên thống kê lại toàn bộ shard, kiểm tra 43 mẫu theo profile và đối chiếu những URL mà trình duyệt tra cứu được. Không đo Precision/Recall/F2 vì chưa dùng gold labels/query retrieval trong lần rà soát này.

## Phạm vi và cách kiểm tra

- Output: [`data_final/chunks_format_final/`](../../../data_final/chunks_format_final/), 1.221 shard, 22 GiB; checkpoint đánh dấu `done=true`.
- Input đối chiếu: [`data_final/final_data.jsonl`](../../../data_final/final_data.jsonl), 1.220.598 record, 5.247.820.535 bytes. SHA-256 tính lại khớp checkpoint: `46a828ab7b9e5ca28bc4094e51ce8849d2a889f01d4fa339504004bf0bdd4510`.
- Đọc và parse toàn bộ 1.221 shard: 1.220.598 record, 4.305.708 chunk, **0 lỗi JSON**; các số record/status/profile/chunk chính khớp checkpoint.
- Lấy mẫu seeded/stratified **7 URL cho mỗi profile có ít nhất 7 tài liệu** và toàn bộ **1 URL** của `structured_list`: tổng 43 mẫu, cân bằng source-language prior, dải source units và host khi nguồn cho phép.
- Với 43 mẫu, đối chiếu `doc_id`, URL, input line, raw hash, cleaned-source hash, `chunk_text == cleaned_source[start_char:end_char]` và coverage: **không phát hiện sai lệch**.
- Đã thử mở trực tiếp cả 43 URL bằng trình duyệt tra cứu web; 11 URL trả nội dung trang đủ để đọc, 32 URL không có nội dung dùng được do lỗi truy xuất/cache hoặc trang chỉ trả tiêu đề. Vì thế kiểm tra web trực tiếp có giới hạn; những trang không truy cập được được đánh giá bằng source đã lưu và chunk output, không suy ra rằng website hiện đang hỏng.

### Giới hạn cách đo độ dài

`source_units` và `unit_count` là custom units của chunker, **không phải số từ tiếng Việt, số token whitespace theo BTC, hay token của embedding model**. Các phần trăm bên dưới chỉ mô tả đơn vị nội bộ hiện tại. Chưa kiểm tra giới hạn token của model đích.

## Phân bố corpus

### Profile trang

| Profile | Số tài liệu thành công | Tỷ lệ | Số chunk |
|---|---:|---:|---:|
| `narrative_article` — Bài viết dạng narrative | 820,414 | 67.59% | 3,597,664 |
| `research_abstract` — Tóm tắt nghiên cứu | 240,323 | 19.80% | 277,407 |
| `qa` — Hỏi đáp | 130,952 | 10.79% | 269,665 |
| `disease_drug_catalogue` — Danh mục bệnh/thuốc | 14,848 | 1.22% | 130,025 |
| `tcm_book` — Sách/tri thức YHCT | 6,031 | 0.50% | 29,740 |
| `generic` — Không nhận diện được dạng cụ thể | 1,199 | 0.10% | 1,199 |
| `structured_list` — Danh sách bài hội nghị có cấu trúc | 1 | 0.00% | 8 |

Tổng: 1.213.768 record `ok`, 6.830 record `skipped` (`crawl_failed`), 0 runtime error; 4.305.708 chunk và 1.625.971 parent.

### Ngôn ngữ

`source_language` là prior theo domain/URL chứ không phải nhãn ngôn ngữ xác thực từ manifest. Đây là phân bố disjoint của prior:

| Domain prior | Tài liệu | Tỷ lệ trên `ok` |
|---|---:|---:|
| `vi` | 694,653 | 57.23% |
| `en` | 239,974 | 19.77% |
| `zh` | 194,675 | 16.04% |
| `und / không có prior` | 84,466 | 6.96% |

`content_language_spans` gắn được nhiều nhãn trong cùng tài liệu; số tài liệu có nhãn không cộng thành 100%: `vi` 710.220; `en` 244.426; `zh` 239.931; `und` 874.530; `es` 5.951; `fr` 1.194; `sr` 29. `und` là thiếu bằng chứng ngôn ngữ, không phải một ngôn ngữ. Mẫu có tài liệu đa ngữ và có `und` trong cùng chunk, vì vậy không nên dùng `source_language` hoặc `content_languages` hiện tại làm bộ lọc loại bỏ cứng.

### Độ dài tài liệu theo profile

| Profile | Median source units | P90 | P95 | Min–max | Nhận xét ngắn |
|---|---:|---:|---:|---:|---|
| `narrative_article` | 770 | 1,654 | 2,348 | 6–95,470 | Dải rộng; có bài rất ngắn và bài dài. |
| `research_abstract` | 207 | 312 | 357 | 1–33,214 | Phần lớn ngắn/trung bình; short abstract là bình thường. |
| `qa` | 229 | 626 | 795 | 10–21,268 | Một phần tư dưới 150 units; câu hỏi/trả lời ngắn khá phổ biến. |
| `disease_drug_catalogue` | 1,518 | 2,434 | 3,042 | 140–176,509 | Nhiều trang danh mục dài, nhưng có record dị dạng cực dài. |
| `tcm_book` | 556 | 2,538 | 3,698 | 21–33,211 | Từ đoạn sách ngắn tới chương dài. |
| `generic` | 14 | 20 | 22 | 5–81 | Cả 1.199 record đều dưới 150 units. |
| `structured_list` | 1,949 | 1,949 | 1,949 | 1,949–1,949 | Chỉ có 1 record trong corpus. |

### Độ dài chunk

| Custom units/chunk | Số chunk | Tỷ lệ |
|---|---:|---:|
| 0-49 | 58,966 | 1.37% |
| 50-99 | 64,740 | 1.50% |
| 100-149 | 98,999 | 2.30% |
| 150-219 | 795,098 | 18.47% |
| 220-300 | 3,286,638 | 76.33% |
| >300 | 1,267 | 0.03% |

Tổng **4,081,736 (94.80%)** chunk nằm trong 150–300 units. Có 222.705 chunk dưới 150 units (5.17%), trong đó có tài liệu vốn ngắn, vùng câu hỏi và ranh giới semantic cứng. Có 1.267 chunk trên 300 units (0.03%).

## Đánh giá thủ công

### Phần đang ổn

- **Bảo toàn ID và văn bản:** 43/43 mẫu khớp `doc_id`/URL/input line và hash nguồn; mọi `chunk_text` mẫu là source slice chính xác. Không có dấu hiệu chunker tự diễn đạt lại câu.
- **Bài narrative dài:** mẫu Vinmec (`doc_id=744228`) giữ title, đoạn dẫn và các mục nội dung; khi mở trang hiện tại, title và đoạn dẫn khớp ý/nội dung với output đã lưu. Mẫu VnExpress và Báo Hải Phòng cũng giữ đoạn văn/entry ở ranh giới tự nhiên.
- **Nghiên cứu có cấu trúc:** bài Sức khỏe Việt (`doc_id=566374`) có Objective/Methods/Results/Conclusion và output giữ được thứ tự abstract trước phần thân bài. Trang nguồn đang truy xuất được cũng cho thấy các phần này nối tiếp đúng thứ tự.
- **Danh sách hội nghị:** `doc_id=6248072` giữ 66 entry O/P thành 8 chunk, mỗi entry được gắn `list_entry`; trang PubMed mở được xác nhận đây là proceedings với danh sách tác giả/entry. Tuy nhiên đây chỉ là **một** tài liệu nên chưa đủ để khái quát chất lượng profile này.
- **QA:** các mẫu 120ask/cnkang giữ câu hỏi và phần trả lời cùng `doc_id`; chunk ngắn có lý do rõ, không thấy câu bị viết lại. Nhiều URL QA không truy cập được từ trình duyệt tra cứu nên đánh giá dựa chủ yếu trên bản crawl đã lưu.

### Vấn đề tìm thấy

#### 1. Nội dung lỗi crawler vẫn đi vào chunk (cao)

Có **52 tài liệu** chứa nguyên văn `Crawl4AI Error: This page is not fully supported...`; tất cả chỉ có 81 custom units. 29 record đang mang profile `generic`, 23 record mang profile `qa`; host gồm `www.120ask.com` (23), `hellobacsi.com` (16), `suckhoedoisong.vn` (9), `laodong.vn` (2), `youmed.vn` (1), `suckhoecongdongonline.vn` (1). Đây là lỗi nội dung nguồn/crawl được chunk thành dữ liệu thành công, không phải văn bản y khoa.

Ví dụ `doc_id=128520`, URL HelloBacsi “đi biển”: chunk duy nhất là thông báo Crawl4AI 81 units, trong khi trang web truy xuất được tiêu đề và nội dung bài viết thật. Một số trang HelloBacsi khác trong mẫu có cùng lỗi. Cần xử lý những record này ở bước kiểm tra crawl/cleaning trước indexing; không nên gửi thông báo lỗi như tài liệu y khoa.

#### 2. Có chunk quá lớn so với ngân sách (cao)

Có 1.267 chunk vượt 300 units; 21 chunk vượt 2.000 units. Lớn nhất là `doc_id=4075884`, [`https://zhongyibaodian.net/a/154133.html`](https://zhongyibaodian.net/a/154133.html), profile `tcm_book`: một child có 10.959 units, `boundary_type=must_link_atom`, `oversized_reason=oversized_structural_atom`, đồng thời record có `damaged_bracket_review`. Nội dung dài 12.363 ký tự chứa nhiều mục bệnh/tiếng thổi tim tách bằng heading như “六、肺动脉瓣区收缩期杂音”, “九、三尖瓣区舒张期杂音”, “十、心底部连续性杂音”. Chunk không bị cắt giữa nội dung, nhưng ranh giới bảo vệ đã gom nhiều mục độc lập vào một chunk rất lớn; đây là rủi ro thực tế cho indexing và giới hạn token. Cần rà soát các atom dị thường và dùng ranh giới heading/list an toàn để chia nhỏ.

#### 3. Profile `disease_drug_catalogue` bị kích hoạt bởi heading phổ biến (trung bình–cao)

Trong 7 mẫu của profile này, 5 trang là bài giải thích sức khỏe thông thường: doc 669126 (ngộ độc nấm rơm), 744228 (hội chứng ruột kích thích), 98656 (bóc tách động mạch chủ), 276743 (ung thư cổ tử cung), 127377 (chăm sóc sau khoét chóp cổ tử cung). Chúng được phân loại `high` vì có các heading chung như “Nguy cơ”, “Nguyên nhân”, “Triệu chứng”, dù không phải catalogue trường bệnh/thuốc. Hai mẫu `jbk.39.net` symptom index và `zhongyibaodian.net` drug monograph phù hợp với catalogue. Hiện mẫu cho thấy tín hiệu heading đơn lẻ chưa đủ phân biệt một bài y khoa có mục lục với một record danh mục.

#### 4. Profile `research_abstract` nhận nhầm một số bài phổ thông (trung bình–cao)

Trong 7 mẫu có 3 ca không giống abstract nghiên cứu: `doc_id=763103` là bài hướng dẫn chế độ ăn cho người tiểu đường trên YouMed; `doc_id=1531406` là nội dung ca khám/xét nghiệm trên cnkang.com; `doc_id=2520938` là trang thông tin xét nghiệm. YouMed bị nhận diện do một nhãn “Outcomes” xuất hiện trong nguồn tham khảo, còn các nhãn kiểu “方法/结果” cũng có thể xuất hiện trên hướng dẫn xét nghiệm. Một nhãn lẻ ở phần thân/tài liệu tham khảo không đủ chứng cứ để biến cả bài thành abstract.

Ngoài ra, child đầu của YouMed (`doc_id=763103`) mang cả “Nội dung bài viết” và nhiều mục lục trước phần nội dung. Trang nguồn có mục lục rõ, nhưng để chúng trong chunk retrieval làm tăng nhiễu và tiêu tốn ngân sách. Nên kiểm soát TOC lặp riêng, đồng thời giữ lại section heading thực sự trong thân bài.

#### 5. Profile `generic` hầu như chỉ chứa mẩu quá ngắn (trung bình)

1.199/1.199 tài liệu `generic` có 5–81 source units, median 14; cả 7 mẫu đều chỉ có một chunk. Trong mẫu có ba trang chỉ lưu title, ba thông báo lỗi Crawl4AI và một đoạn ngắn tiếng Trung. Có thể vẫn có trang nguồn vốn chỉ là snippet, nhưng phân bố này cho thấy cần phân biệt “tài liệu ngắn thật” với “crawl thiếu nội dung” trước khi đưa vào index.

#### 6. Markdown/link hỏng và template còn sót (trung bình)

Checkpoint ghi 17.657 `incomplete_markdown_link` cleaning warnings. Mẫu `doc_id=2534375` còn fragment như `详细>>[[起因] 消瘦是怎么引起的？](\n` và link UI trong `chunk_text`; nội dung này không phải cú pháp plain text sạch và có thể giảm khả năng đối sánh token. Warning có ích để truy vết nhưng hiện chưa đồng nghĩa fragment đã được loại/khôi phục.

## Nhận xét theo yêu cầu

- **Phân bố độ dài:** nhìn ở histogram, khá cân bằng quanh 220–300 custom units; short chunk có lý do và chỉ chiếm 5,17% dưới 150 units. Tuy vậy outlier 10.959 units là ngoại lệ không nên chấp nhận cho index chuẩn.
- **Ngôn ngữ:** độ bao phủ domain prior gần đủ `vi/en/zh`, nhưng prior khác với ngôn ngữ thật. Nhãn `und` và tài liệu pha ngôn ngữ nhiều; cần dùng nội dung thật/metadata nguồn làm căn cứ khi xây filter.
- **Câu chữ và ranh giới:** trong mẫu, câu chữ được giữ nguyên; hầu hết chunk đọc được theo đoạn/mục. “Cắt ngu” không phải biểu hiện chính. Rủi ro chính là nguồn có mẩu lỗi, TOC/link UI còn sót, profile sai và atom quá lớn khiến chunk chứa nhiều mục độc lập.
- **Mức độ sẵn sàng:** phù hợp để tiếp tục làm candidate và phát triển kiểm tra chất lượng; **chưa nên index/nộp trực tiếp cả folder** khi chưa xử lý 52 lỗi crawl, rà chunk quá cỡ và giảm false-positive profile/TOC.

## Danh sách URL mẫu đã rà

Các URL dưới đây được chọn để xem nhiều host, prior ngôn ngữ và dải độ dài. Link “output row” mở record chunk tương ứng trong shard. 43 là cỡ mẫu đã xem; `structured_list` chỉ có một document trong toàn bộ corpus nên không thể lấy 5–10 URL.

### `disease_drug_catalogue` — 7 mẫu

| Doc ID | Ngôn ngữ prior / units | Số chunk | URL nguồn | Output row |
|---:|---:|---:|---|---|
| 2534375 | `zh` / 506 | 2 | [mở URL](https://jbk.39.net/zhengzhuang/xs/) | [part-001152.jsonl:L8](../../../data_final/chunks_format_final/part-001152.jsonl#L8) |
| 669126 | `vi` / 1,401 | 6 | [mở URL](https://tiemchunglongchau.com.vn/kien-thuc-tiem-chung/ngo-doc-nam-rom-dau-hieu-nhan-biet-nguyen-nhan-va-cach-xu-tri-an-toan) | [part-000650.jsonl:L123](../../../data_final/chunks_format_final/part-000650.jsonl#L123) |
| 744228 | `und` / 2,428 | 11 | [mở URL](https://www.vinmec.com/vie/bai-viet/hoi-chung-ruot-kich-thich-co-nguy-hiem-khong-vi) | [part-000718.jsonl:L385](../../../data_final/chunks_format_final/part-000718.jsonl#L385) |
| 4104408 | `zh` / 140 | 1 | [mở URL](https://zhongyibaodian.net/a/27222.html) | [part-001210.jsonl:L636](../../../data_final/chunks_format_final/part-001210.jsonl#L636) |
| 98656 | `und` / 587 | 3 | [mở URL](https://benhvienvietduc.org/nhan-biet-va-phong-tranh-benh-loc-dong-mach-chu.html) | [part-000098.jsonl:L74](../../../data_final/chunks_format_final/part-000098.jsonl#L74) |
| 276743 | `vi` / 2,377 | 9 | [mở URL](https://nhathuoclongchau.com.vn/bai-viet/ung-thu-co-tu-cung-co-chet-khong-dau-hieu-nhan-biet-va-cach-dieu-tri-44536.html) | [part-000271.jsonl:L945](../../../data_final/chunks_format_final/part-000271.jsonl#L945) |
| 127377 | `und` / 1,499 | 6 | [mở URL](https://hellobacsi.com/suc-khoe-phu-nu/van-de-phu-khoa-khac/sau-khi-khoet-chop-co-tu-cung-can-kieng-gi/) | [part-000126.jsonl:L677](../../../data_final/chunks_format_final/part-000126.jsonl#L677) |

### `generic` — 7 mẫu

| Doc ID | Ngôn ngữ prior / units | Số chunk | URL nguồn | Output row |
|---:|---:|---:|---|---|
| 499775 | `vi` / 19 | 1 | [mở URL](https://suckhoedoisong.vn/cach-mot-tinh-mien-nui-nhu-yen-bai-chu-dong-tu-tin-mua-sam-thuoc-vat-tu-y-te-169231105211333273.htm) | [part-000494.jsonl:L977](../../../data_final/chunks_format_final/part-000494.jsonl#L977) |
| 128520 | `und` / 81 | 1 | [mở URL](https://hellobacsi.com/suc-khoe/kien-thuc-suc-khoe/di-bien/) | [part-000127.jsonl:L820](../../../data_final/chunks_format_final/part-000127.jsonl#L820) |
| 4220158 | `zh` / 79 | 1 | [mở URL](https://zysjonline.com/articles/misc/63212/) | [part-001214.jsonl:L297](../../../data_final/chunks_format_final/part-001214.jsonl#L297) |
| 491094 | `vi` / 15 | 1 | [mở URL](https://suckhoedoisong.vn/be-gai-11-thang-tuoi-nguy-kich-vi-soc-mat-nuoc-tu-duong-tieu-hoa-169241101084233554.htm) | [part-000486.jsonl:L296](../../../data_final/chunks_format_final/part-000486.jsonl#L296) |
| 128090 | `und` / 81 | 1 | [mở URL](https://hellobacsi.com/suc-khoe-tinh-duc/ngua-thai/that-ong-dan-tinh-o-dau/) | [part-000127.jsonl:L390](../../../data_final/chunks_format_final/part-000127.jsonl#L390) |
| 517975 | `vi` / 11 | 1 | [mở URL](https://suckhoedoisong.vn/ha-noi-254-ca-mac-tay-chan-mieng-trong-mot-tuan-169250521092223625.htm) | [part-000513.jsonl:L177](../../../data_final/chunks_format_final/part-000513.jsonl#L177) |
| 128132 | `und` / 81 | 1 | [mở URL](https://hellobacsi.com/suc-khoe-tinh-duc/ngua-thai/xuat-tinh-ngoai-am-dao-co-that-su-giup-tranh-thai/) | [part-000127.jsonl:L432](../../../data_final/chunks_format_final/part-000127.jsonl#L432) |

### `narrative_article` — 7 mẫu

| Doc ID | Ngôn ngữ prior / units | Số chunk | URL nguồn | Output row |
|---:|---:|---:|---|---|
| 367151 | `vi` / 377 | 2 | [mở URL](https://suckhoecongdongonline.vn/dong-nai-ghi-nhan-2-truong-hop-mac-covid-19-nhiem-bien-the-omicron) | [part-000362.jsonl:L353](../../../data_final/chunks_format_final/part-000362.jsonl#L353) |
| 738284 | `und` / 3,133 | 14 | [mở URL](https://www.vinmec.com/vie/bai-viet/cham-soc-nguoi-benh-truoc-phau-thuat-tieu-hoa-vi) | [part-000712.jsonl:L441](../../../data_final/chunks_format_final/part-000712.jsonl#L441) |
| 861643 | `zh` / 1,813 | 8 | [mở URL](http://heart.39.net/a/2010129/1564349.html) | [part-000988.jsonl:L700](../../../data_final/chunks_format_final/part-000988.jsonl#L700) |
| 1717973 | `und` / 51 | 1 | [mở URL](http://www.cnkang.com/fuke/shuluanguanduse/587348.html) | [part-001089.jsonl:L536](../../../data_final/chunks_format_final/part-001089.jsonl#L536) |
| 52316 | `vi` / 4,423 | 19 | [mở URL](https://baohaiphong.vn/giao-luu-truc-tuyen-san-xuat-kinh-doanh-va-su-dung-thuc-pham-an-toan-330729.html) | [part-000051.jsonl:L734](../../../data_final/chunks_format_final/part-000051.jsonl#L734) |
| 3056447 | `zh` / 143 | 1 | [mở URL](https://www.a-hospital.com/w/%E6%81%AF%E7%B2%97) | [part-001169.jsonl:L44](../../../data_final/chunks_format_final/part-001169.jsonl#L44) |
| 702264 | `und` / 1,240 | 6 | [mở URL](https://vnexpress.net/cach-an-giup-nguoi-phu-nu-dao-nguoc-17-nam-lao-hoa-5048122.html) | [part-000679.jsonl:L810](../../../data_final/chunks_format_final/part-000679.jsonl#L810) |

### `qa` — 7 mẫu

| Doc ID | Ngôn ngữ prior / units | Số chunk | URL nguồn | Output row |
|---:|---:|---:|---|---|
| 2906812 | `zh` / 3,590 | 16 | [mở URL](https://www.120ask.com/question/603647.htm) | [part-001165.jsonl:L163](../../../data_final/chunks_format_final/part-001165.jsonl#L163) |
| 1727275 | `und` / 271 | 1 | [mở URL](http://www.cnkang.com/fuke/ziranliuchan/578192.html) | [part-001090.jsonl:L465](../../../data_final/chunks_format_final/part-001090.jsonl#L465) |
| 2264403 | `zh` / 143 | 2 | [mở URL](https://ask.39.net/question/49934058.html) | [part-001131.jsonl:L745](../../../data_final/chunks_format_final/part-001131.jsonl#L745) |
| 2540096 | `und` / 1,794 | 9 | [mở URL](https://test.pmphai.com/jeesitede/appcase/toPcDetail?sessionId=&knowledgeLibPrefix=case&id=9136) | [part-001152.jsonl:L979](../../../data_final/chunks_format_final/part-001152.jsonl#L979) |
| 1303140 | `zh` / 113 | 1 | [mở URL](http://www.120ask.com/question/559439.htm) | [part-001060.jsonl:L100](../../../data_final/chunks_format_final/part-001060.jsonl#L100) |
| 3508153 | `und` / 901 | 4 | [mở URL](https://www.cnkang.com/nxjk/201108/692848.html) | [part-001175.jsonl:L863](../../../data_final/chunks_format_final/part-001175.jsonl#L863) |
| 2342511 | `zh` / 391 | 3 | [mở URL](https://ask.39.net/question/86894811.html) | [part-001139.jsonl:L496](../../../data_final/chunks_format_final/part-001139.jsonl#L496) |

### `research_abstract` — 7 mẫu

| Doc ID | Ngôn ngữ prior / units | Số chunk | URL nguồn | Output row |
|---:|---:|---:|---|---|
| 834872 | `zh` / 449 | 2 | [mở URL](http://fk.39.net/a/210120/8609046.html) | [part-000986.jsonl:L879](../../../data_final/chunks_format_final/part-000986.jsonl#L879) |
| 6234329 | `en` / 112 | 1 | [mở URL](https://pubmed.ncbi.nlm.nih.gov/27188430/) | [part-000856.jsonl:L724](../../../data_final/chunks_format_final/part-000856.jsonl#L724) |
| 1531406 | `und` / 744 | 4 | [mở URL](http://www.cnkang.com/dise/403/434647.html) | [part-001081.jsonl:L819](../../../data_final/chunks_format_final/part-001081.jsonl#L819) |
| 566374 | `vi` / 5,452 | 27 | [mở URL](https://suckhoeviet.org.vn/kien-thuc-thai-do-thuc-hanh-ve-phong-va-xu-tri-phoi-nhiem-voi-vat-sac-nhon-trong-tiem-truyen-cua-sinh-vien-khoa-y-duoc-truong-dai-hoc-tra-vinh-11700.html) | [part-000561.jsonl:L467](../../../data_final/chunks_format_final/part-000561.jsonl#L467) |
| 763103 | `vi` / 2,570 | 15 | [mở URL](https://youmed.vn/tin-tuc/nhung-diem-can-luu-y-trong-che-do-an-o-nguoi-dai-thao-duong/) | [part-000737.jsonl:L260](../../../data_final/chunks_format_final/part-000737.jsonl#L260) |
| 2520938 | `zh` / 1,249 | 6 | [mở URL](https://jbk.39.net/jiancha/scjsjfsy/) | [part-001150.jsonl:L662](../../../data_final/chunks_format_final/part-001150.jsonl#L662) |
| 6345249 | `en` / 156 | 1 | [mở URL](https://pubmed.ncbi.nlm.nih.gov/28530453/) | [part-000867.jsonl:L772](../../../data_final/chunks_format_final/part-000867.jsonl#L772) |

### `structured_list` — 1 mẫu

| Doc ID | Ngôn ngữ prior / units | Số chunk | URL nguồn | Output row |
|---:|---:|---:|---|---|
| 6248072 | `en` / 1,949 | 8 | [mở URL](https://pubmed.ncbi.nlm.nih.gov/27356504/) | [part-000858.jsonl:L130](../../../data_final/chunks_format_final/part-000858.jsonl#L130) |

### `tcm_book` — 7 mẫu

| Doc ID | Ngôn ngữ prior / units | Số chunk | URL nguồn | Output row |
|---:|---:|---:|---|---|
| 4311999 | `zh` / 61 | 1 | [mở URL](https://zysjonline.com/books/tanhuodianxue/141411/) | [part-001218.jsonl:L60](../../../data_final/chunks_format_final/part-001218.jsonl#L60) |
| 4165101 | `zh` / 2,848 | 12 | [mở URL](https://zhongyibaodian.net/a/a-bu/62936.html) | [part-001213.jsonl:L493](../../../data_final/chunks_format_final/part-001213.jsonl#L493) |
| 4256582 | `zh` / 577 | 3 | [mở URL](https://zysjonline.com/books/fuchankexue/178423/) | [part-001215.jsonl:L513](../../../data_final/chunks_format_final/part-001215.jsonl#L513) |
| 4340961 | `zh` / 814 | 4 | [mở URL](https://zysjonline.com/books/yizongjinjian/84489/) | [part-001219.jsonl:L312](../../../data_final/chunks_format_final/part-001219.jsonl#L312) |
| 4135141 | `zh` / 13,959 | 60 | [mở URL](https://zhongyibaodian.net/a/68157.html) | [part-001211.jsonl:L920](../../../data_final/chunks_format_final/part-001211.jsonl#L920) |
| 4048853 | `zh` / 507 | 3 | [mở URL](https://zhongyibaodian.net/a/122400.html) | [part-001208.jsonl:L578](../../../data_final/chunks_format_final/part-001208.jsonl#L578) |
| 4380117 | `zh` / 1,089 | 5 | [mở URL](https://zysjonline.com/books/zhouhoubeijifang/12411/) | [part-001220.jsonl:L304](../../../data_final/chunks_format_final/part-001220.jsonl#L304) |

## Nguồn trang web đã mở

- [Vinmec — bài hướng dẫn chăm sóc trước phẫu thuật](https://www.vinmec.com/vie/bai-viet/cham-soc-nguoi-benh-truoc-phau-thuat-tieu-hoa-vi)
- [Vinmec — hội chứng ruột kích thích](https://www.vinmec.com/vie/bai-viet/hoi-chung-ruot-kich-thich-co-nguy-hiem-khong-vi)
- [Hello Bacsi — bài “Đi biển mùa hè”](https://hellobacsi.com/suc-khoe/kien-thuc-suc-khoe/di-bien/)
- [Hello Bacsi — bài “Sau khi khoét chóp cổ tử cung”](https://hellobacsi.com/suc-khoe-phu-nu/van-de-phu-khoa-khac/sau-khi-khoet-chop-co-tu-cung-can-kieng-gi/)
- [YouMed — bài chế độ ăn cho người tiểu đường](https://youmed.vn/tin-tuc/nhung-diem-can-luu-y-trong-che-do-an-o-nguoi-dai-thao-duong/)
- [Sức khỏe Việt — bài nghiên cứu sinh viên Y Dược Trà Vinh](https://suckhoeviet.org.vn/kien-thuc-thai-do-thuc-hanh-ve-phong-va-xu-tri-phoi-nhiem-voi-vat-sac-nhon-trong-tiem-truyen-cua-sinh-vien-khoa-y-duoc-truong-dai-hoc-tra-vinh-11700.html)
- [PubMed — proceedings HIV/AIDS congress](https://pubmed.ncbi.nlm.nih.gov/27356504/)

**Không chạy test suite**: đây là rà soát output đã có, không thay đổi code hay hành vi. Không chỉnh sửa `data_final/final_data.jsonl` hoặc bất kỳ shard nào trong `chunks_format_final`.
