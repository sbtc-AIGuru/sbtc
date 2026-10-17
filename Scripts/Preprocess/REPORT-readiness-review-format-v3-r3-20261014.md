# Đánh giá mức sẵn sàng full: format-v3 r3 post_pack và reserve

Ngày: 14/10/2026. Phạm vi: hai output hiện có, chỉ dựa trên `data_final/test_20k.jsonl` và các shards tương ứng. Không chạy lại chunking, không sửa dữ liệu. Mục tiêu là chọn bản phù hợp để mở rộng, đồng thời nêu những lỗi audit cấu trúc không thể phát hiện.

## Kết luận

**Nếu phải chọn một trong hai để làm candidate chạy full theo từng đợt, chọn `format-v3 r3 reserve`.** Trên test20k, nó giữ cùng source/profile/exclusions như `post_pack`, audit hợp lệ, tăng overlap có ích và chỉ thêm khoảng0,70% chunks. Nó không làm sạch hơn TOC/quảng cáo hoặc giải quyết vấn đề thiếu ngữ cảnh của QA; các lỗi đó có ở cả hai output.

**Chưa đủ căn cứ để coi output nào là final retrieval corpus đã được nghiệm thu.** Nên chạy reserve trước trên một đợt pilot có audit và lấy mẫu theo host. Trước khi mở rộng toàn bộ, cần quyết định cách đưa câu hỏi vào chunk QA, đánh giá navigation/SEO còn sót và báo riêng record chỉ có title/crawl failure. Nếu downstream đã dùng parent title/question khi tạo embedding thì xác minh điều đó trước; trường metadata hiện có không tự động xuất hiện trong `chunk_text`.

Không có gold retrieval labels trong fixture này. Vì vậy `reserve` thắng theo các proxy cấu trúc của chunking, chưa được chứng minh tăng Precision/Recall/F2.

## Cách lấy mẫu và giới hạn kết luận

Đã đối chiếu tổng quan cả 20.000 dòng và mở/đọc source cùng output của **43 URL**: sáu URL cho từng profile có nhiều hơn một record (`narrative_article`, `research_abstract`, `qa`, `tcm_book`, `disease_drug_catalogue`, `generic`, `skipped`) và record duy nhất của `structured_list`. Trong mỗi nhóm, mẫu trải theo các phân vị độ dài nguồn và ưu tiên đa dạng host/ngôn ngữ. Với trang dài, review phần đầu nguồn và các child đầu/giữa/cuối cùng child ngắn/dài nhất; không đọc thủ công toàn bộ từng trang nhiều chục nghìn ký tự.

Đây là review phân tầng để tìm lỗi, không phải mẫu xác suất để ước lượng tỷ lệ lỗi toàn kho. `source_language` là prior do pipeline gán, không phải nhãn người xác minh. `test_20k` cũng chưa được chứng minh là đại diện ngẫu nhiên cho toàn bộ corpus mới.

## Toàn cảnh 20.000 record

| Profile/status ở reserve | Số record | Nguồn ngắn `<50` units | Số child | Child `<50` |
|---|---:|---:|---:|---:|
| narrative_article | 13.200 | 693 | 46.240 | 769 |
| research_abstract | 4.476 | 696 | 6.426 | 697 |
| qa | 1.800 | 7 | 8.306 | 546 |
| tcm_book | 240 | 1 | 813 | 10 |
| disease_drug_catalogue | 127 | 0 | 1.094 | 7 |
| generic | 54 | 54 | 54 | 54 |
| structured_list | 1 | 0 | 8 | 0 |
| skipped | 102 | — | 0 | 0 |

Theo các bucket của `source_units` trong 19.898 record OK: `<50` 1.451; `50–99` 1.726; `100–299` 6.377; `300–999` 5.608; `≥1.000` 4.736. Language prior: VI9.313, ZH3.876, EN4.475, und2.234. Tổng 20.000 bao gồm 102 skipped.

Mỗi run xử lý 20.000 input records, trong đó 19.898 OK, 102 skipped và 0 lỗi runtime. Hai audit đều 0 errors. Các con số này xác nhận tính toàn vẹn ID/source slice theo audit; chúng không có nghĩa crawl đã lấy được nội dung cho toàn bộ ID. 102 skipped là 100 crawl failures và hai lỗi placeholder. Trong 54 record profile `generic`, mọi nguồn chỉ có `<50` units và một child; sáu mẫu đọc đều chỉ chứa headline ngắn. Đáng để gắn cờ extraction/coverage khi chạy full, không nên coi chunking đã biến chúng thành bài viết đầy đủ.

## So sánh `post_pack` và `reserve` theo nhóm

`ideal` là tỷ lệ overlap 30–50 units giữa hai chunk cùng parent; `>50` là overlap lớn hơn dải mục tiêu. Đây là metric đóng gói nội bộ, không phải LCS với nhãn hoặc retrieval F2.

| Nhóm | Docs | Ideal post→reserve | Có overlap post→reserve | `>50` post→reserve | Children post→reserve |
|---|---:|---:|---:|---:|---:|
| narrative_article | 13.200 | 60,75→63,09% | 88,56→92,66% | 14,15→16,19% | 45.920→46.240 |
| research_abstract | 4.476 | 64,99→66,85% | 90,79→93,35% | 15,11→15,81% | 6.416→6.426 |
| qa | 1.800 | 42,69→46,26% | 76,85→85,54% | 21,65→25,87% | 8.220→8.306 |
| disease_drug_catalogue | 127 | 65,70→68,20% | 87,01→90,40% | 10,47→12,47% | 1.085→1.094 |
| tcm_book | 240 | 43,62→46,08% | 76,34→84,31% | 17,90→22,74% | 802→813 |
| structured_list | 1 | 50,00→50,00% | 83,33→83,33% | 16,67→16,67% | 8→8 |
| generic | 54 | Không có transition | — | — | 54→54 |

Tổng: **62.505→62.941 children (+436; +0,70%)**, output **322,30→322,95 MiB (+0,20%)**. Hai policy khác ranh giới chunk trên 1.454 docs. Chúng có chung cleaned source, profile và exclusions; không thấy lexical/order difference ở source đã clean. `reserve` tăng ideal overlap **2,42 điểm phần trăm** so với post và positive overlap **4,51 điểm**. Mặt trái: `>50` overlap tăng, nổi bật QA từ21,65% lên25,87%, và số chunk trùng ngữ cảnh có thể làm tăng gần-duplicate hits. Không có nhãn retrieval để quyết định đó làm precision giảm hay recall tăng ngoài proxy.

Không output nào có child trên500 units. Có23 child trên300, lớn nhất494; đây là giới hạn soft, không phải bug audit. Reserve còn2.083 child `<50`, post2.084; khác biệt không giải quyết các câu hỏi ngắn hoặc record nguồn ngắn.

## Review theo kiểu trang và URL đại diện

Các URL dưới đây được đọc từ nguồn lưu trong test20k và đối chiếu với child JSONL; kết quả reserve/post giống nhau về nội dung nguồn, khác nhau chủ yếu ở các trang phải pack lại. Mẫu đủ 6 URL cho mỗi nhóm lớn, trừ `structured_list` chỉ có đúng một record trong test20k.

### Narrative article — 13.200 records

Mẫu IDs: `663614`, `4171829`, `35278`, `558767`, `752224`, `3078711`.

- `752224` (Vinmec, VI) chia thành sáu đoạn 208–286 units; đoạn rau dớn và các công dụng đi cùng câu/paragraph, overlap thường ở vùng mục tiêu. Đọc ổn.
- `558767` (Sức khỏe & Đời sống, VI) giữ câu hỏi về thuốc ho và phần trả lời trong các đoạn liên tiếp; biên câu không cắt ý.
- `35278` (Báo Đà Nẵng) là bài ngắn một chunk, nhưng crawl text lặp tiêu đề và timestamp. Chunk giữ verbatim nên lặp này còn nguyên.
- `663614` trả về đúng một tiêu đề 9 units, không có bài viết. Đây là nguồn ngắn/thiếu nội dung, không phải lỗi pack.
- **Vấn đề đáng kể:** `3078711` (A+医学百科, ZH) là danh sách thuốc dài nhưng được gán narrative. Child đầu 247 units gồm breadcrumb “跳转到：导航, 搜索”, danh sách điều hướng và phân loại trước phần thuốc. TOC detector hiện dựa marker tường minh; mẫu wiki này không bị loại.
- Trên toàn output reserve, chuỗi marker chính xác `跳转到： 导航, 搜索` xuất hiện trong **598 docs**; `2个分类:` ở307 docs, `图书正文` ở172 docs, `药理学目录` ở7 docs. Đây là số doc có marker ứng viên, không khẳng định mọi occurrence đều nên bị xóa; sample3078711 xác nhận ít nhất một khối navigation thật còn trong chunk.

**Đánh giá:** ranh giới câu và coverage tốt ở các bài có body; phần TOC/wiki chrome và title-only là điểm cần xử lý trước khi tin tưởng chất lượng toàn corpus. Reserve không sửa nội dung nhiễu, nhưng tăng overlap trên nhóm này 4,10 điểm positive.

### Research abstract — 4.476 records

Mẫu IDs: `6118192`, `6974953`, `5230447`, `5366556`, `7024104`, `5467809`.

- `7024104` (PubMed, EN) giữ summary/abstract hai chunk có overlap41 units; văn bản có diễn tiến mô tả rồi MRI/biopsy/kết luận, không cắt giữa câu.
- `5467809` (PubMed, EN và FR) giữ các section song ngữ; section tiếng Pháp riêng vẫn có ngữ cảnh, không bị dịch hay viết lại.
- `6974953`, `5230447` là abstract ngắn một chunk; hợp lý với nguồn ngắn.
- **Nguồn thiếu nội dung:** `6118192` chỉ có `Endotext` (1 unit) nhưng status/profile vẫn OK research. Toàn nhóm có696 docs `<50` units và53 docs `<20`; nhiều abstract thật có thể ngắn, nhưng record một từ cần gắn cờ kiểm tra nguồn.

**Đánh giá:** nhóm có cấu trúc nhất quán, câu và section rõ; reserve tăng ideal1,86 điểm, không thay chunk ở đa số mẫu. Cần quality flag cho tài liệu title-only/abstract-missing.

### QA — 1.800 records

Mẫu IDs: `1020418`, `2305713`, `2422171`, `1002419`, `1312847`, `1050305`.

- `1312847` và `1050305` giữ được nhiều lượt hỏi đáp trong chuỗi chunk; câu và câu trả lời không bị viết lại. Trang lớn `1050305` có37 chunks; reserve tạo lại biên ở một số vùng nhưng giữ body source.
- `2305713` có câu hỏi 14 units thành child riêng, kế tiếp là câu trả lời 115 units ở **parent khác**. `2422171` có cùng dạng: title question13 units và answer295 units.
- Trong toàn bộ reserve có **392/1.800 QA docs (21,8%)** có câu hỏi/title child `<50` units và chunk kế là answer ở parent khác. Policy reserve không thể nối qua ranh giới parent/role, nên tăng overlap trong các đoạn trả lời nhưng không đưa câu hỏi vào answer chunk.
- Sample `1020418` có câu hỏi trùng title và một câu trả lời ngắn trong cùng child; đây là trường hợp giữ đủ ngữ cảnh. Cần xử lý riêng trường hợp câu hỏi title-only tách parent.

**Đánh giá:** đây là vấn đề retrieval quan trọng nhất còn lại. Nếu consumer embed riêng `chunk_text`, nhiều answer hit không có câu hỏi. Cần xác minh có nối title/question vào văn bản embedding ở downstream không; metadata `title_span` chỉ có ích nếu được dùng. Reserve tăng ideal3,57 điểm, nhưng overlap `>50` cũng tăng4,22 điểm.

### TCM book — 240 records

Mẫu IDs: `4255965`, `4264018`, `4171795`, `4345384`, `4250543`, `4271202`.

- `4271202` giữ đoạn văn y học cổ và phần phương/đơn thuốc trong các child nhiều đơn vị; `4250543` giữ văn xuôi và các công thức thuốc có cấu trúc.
- `4255965` là mục từ ngắn 21 units nhưng bản thân mục từ đã hoàn chỉnh; không nên gộp với mục khác chỉ để đạt độ dài.
- `4345384` có hai child 207/264 units với overlap nguyên atom96 units. Đây là ví dụ >50 vẫn cần giữ vì biên nội dung không chia nhỏ phù hợp.
- Có6 child >300 units trong nhóm; vẫn dưới500. `4057861` là ví dụ 494 units liền mạch có numeric/abbreviation content, cần giữ nguyên span.

**Đánh giá:** các mẫu giữ nguyên văn và ranh giới chủ đề; một vài overlap dài là trade-off ngữ cảnh. Reserve tăng ideal2,46 điểm nhưng tỷ lệ >50 tăng4,84 điểm.

### Disease/drug catalogue — 127 records

Mẫu IDs: `4118235`, `2534385`, `283017`, `3705581`, `189365`, `565011`.

- `4118235` (thuốc tiêm địa long, ZH) giữ các trường chỉ định/liều/chống chỉ định cùng trong một chunk153 units.
- `189365` (Exforge, VI) chia các mục thuốc ở các đoạn 165–299 units, nội dung còn chỉ dẫn chỉ dùng theo bác sĩ.
- `2534385` (39.net, ZH) có bảng bệnh và thuốc, artifact link/TOC “详细>>”, danh sách bệnh và thuốc điều hướng. Chunking giữ cấu trúc bảng nhưng source crawl đã nhiễu.
- **Nhiễu quảng cáo rõ:** `3705581` (FamilyDoctor, ZH) có nội dung kỹ thuật phá thai bằng thuốc, đồng thời các child giữa trang chứa hàng loạt quảng cáo xếp hạng bệnh viện/đặt lịch khám không liên quan. Vì giữ văn bản nguồn verbatim, cả hai policy đưa phần đó vào chunks.
- `565011` (xạ đen, VI) là bài thảo dược với các tuyên bố công dụng, không phải monograph thuốc chuẩn dù có nhiều field thuốc. Profile routing phù hợp hơn sau sửa so với narrative, nhưng vẫn là ranh giới khái niệm cần thống nhất.

**Đánh giá:** cấu trúc chunks hợp lý ở monograph sạch; chất lượng source host không đồng đều. Cần template/host-level noise review, tuyệt đối không cắt bằng keyword y khoa đơn lẻ.

### Generic — 54 records

Mẫu IDs: `491960`, `508553`, `554421`, `550062`, `520253`, `532419`.

Cả sáu mẫu chỉ có một headline từ30–86 ký tự, được giữ thành một chunk7–20 units. Toàn bộ54 generic docs có nguồn `<50` units và đúng một child. Có headline hữu ích, nhưng không có nội dung để chunk retrieval. Gắn cờ extraction-limited và đo riêng; không lấy zero audit errors làm bằng chứng các bài đã crawl đủ.

### Structured list — 1 record

Chỉ có `6248072` (proceedings HIV, PubMed). Tám chunk `list_entry`, mỗi chunk giữ abstract/title/tác giả trong mục hội nghị; mẫu này không đủ để kết luận loại structured proceedings nói chung. Reserve không đổi số chunk ở record duy nhất.

### Skipped/crawl failures — 102 records

Mẫu sáu IDs: `319929`, `320772`, `2748577`, `662106`, `7209877`, `752936`. Chúng có text rỗng, status skipped và không tạo children. Đó là hành vi nhất quán giữa hai output, nhưng là mất coverage gốc cần cộng vào đánh giá crawl; không được báo cáo “20.000 tài liệu có nội dung đã chunk”.

## Các tiêu chí cần đạt trước khi gọi full output là sẵn sàng

1. **QA context:** quyết định câu hỏi/title được ghép vào chunk retrieval bằng source slice hợp lệ hay downstream thực sự dùng question/title metadata; kiểm lại nhóm392 ca. Không ghép QA qua doc/parent boundary tùy tiện.
2. **Navigation và template noise:** review rule bỏ wiki chrome trên các host có marker `跳转到： 导航, 搜索`, `目录`, `图书正文`, classification footer; thêm regression positive/negative. FamilyDoctor ad blocks và nội dung quảng cáo cần đánh giá theo host/source.
3. **Extraction completeness:** xuất danh sách all skipped, title-only/generic, source_units thấp, abstract rỗng; quyết định retry crawl hay giữ record short. Đo các mục này riêng theo host và ngôn ngữ.
4. **Full-scale pilot:** chạy reserve trên shard đầu/fresh output, audit từng shard, so host/profile/length/language distributions và review thêm5–10 URLs cho từng host lớn/nhạy cảm. Dừng mở rộng nếu bắt đầu có ID/URL/source-slice mismatch, lỗi runtime, lỗi audit hoặc tăng bất thường record chỉ-title/navigation.
5. **Retrieval acceptance:** đưa post và reserve qua cùng embedding/index/query set và gold labels; so recall, precision, F2, duplicate docs/hits. Nếu chưa có gold, giữ kết luận là structural proxy và không khẳng định điểm thi tăng.

## Đề xuất chọn output

- **Chọn `chunks_format_v3_r3_reserve_test20k` làm candidate cho bước mở rộng pilot.** Nó cải thiện overlap ở mọi nhóm đủ transition, đặc biệt QA/narrative, mà không làm đổi nguồn text/profile/exclusion.
- **Không kết luận reserve là final tốt hơn post_pack cho retrieval.** Overlap `>50` tăng và có khả năng trả nhiều hit gần trùng; QA title/answer split và nguồn có quảng cáo là hai rủi ro chưa được đo bằng gold.
- Nếu cần build full corpus ngay để có một candidate xử lý tiếp, dùng reserve và giữ output riêng versioned; chạy theo shard, có audit + gate trên. Chưa nên dùng kết quả full thẳng làm corpus cuối để nộp/chấm trước khi giải quyết hoặc chấp nhận rõ các ngoại lệ trên.

## Đường dẫn đã review

- Reserve: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v3_r3_reserve_test20k/`
- Post: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/chunks_format_v3_r3_test20k/`
- Test input: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl`
- Audit/evaluation gốc: `/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/tasks/chunking-next-improvements-20261014/results-r3/`

## Danh sách URL mẫu đã mở trong output

Mỗi URL dưới đây được đối chiếu source text và các chunk đầu/giữa/cuối trong JSONL. Đây là URL gốc lưu trong test20k, không phải xác nhận trang web hiện tại còn nguyên trạng.

### Narrative article

| doc_id | URL |
|---:|---|
| 663614 | https://tiemchunglongchau.com.vn/kien-thuc-tiem-chung/benh-bach-hau-la-can-benh-nhu-the-nao |
| 4171829 | https://zhongyibaodian.net/a/a-he/120887.html |
| 35278 | https://baodanang.vn/lap-15-doan-thanh-tra-ve-sua-tren-toan-quoc-3237599.html |
| 558767 | https://suckhoedoisong.vn/uong-thuoc-ho-khi-nao-thi-tot-169132230.htm |
| 752224 | https://www.vinmec.com/vie/bai-viet/tac-dung-cua-cay-rau-don-vi |
| 3078711 | https://www.a-hospital.com/w/%E6%B2%BB%E7%96%97%E5%86%85%E5%88%86%E6%B3%8C%E7%96%BE%E7%97%85%E5%92%8C%E4%BB%A3%E8%B0%A2%E7%96%BE%E7%97%85%E7%9A%84%E8%8D%AF%E5%93%81%E5%88%97%E8%A1%A8 |

### Research abstract

| doc_id | URL |
|---:|---|
| 6118192 | https://pubmed.ncbi.nlm.nih.gov/25905360/ |
| 6974953 | https://pubmed.ncbi.nlm.nih.gov/34908701/ |
| 5230447 | https://pubmed.ncbi.nlm.nih.gov/12561652/ |
| 5366556 | https://pubmed.ncbi.nlm.nih.gov/16140166/ |
| 7024104 | https://pubmed.ncbi.nlm.nih.gov/35332876/ |
| 5467809 | https://pubmed.ncbi.nlm.nih.gov/17549134/ |

### QA

| doc_id | URL |
|---:|---|
| 1020418 | http://www.120ask.com/question/11490446.htm |
| 2305713 | https://ask.39.net/question/64748620.html |
| 2422171 | https://ask.39.net/question/_am33c5.html |
| 1002419 | http://www.120ask.com/question/108498283.htm |
| 1312847 | http://www.120ask.com/question/590627.htm |
| 1050305 | http://www.120ask.com/question/13795832.htm |

### TCM book

| doc_id | URL |
|---:|---|
| 4255965 | https://zysjonline.com/books/fengshijinnangmilu/88951/ |
| 4264018 | https://zysjonline.com/books/huayanzhengchangzhijiyiyi/18270/ |
| 4171795 | https://zhongyibaodian.net/a/a-he/119177.html |
| 4345384 | https://zysjonline.com/books/yufangyixue/171710/ |
| 4250543 | https://zysjonline.com/books/dantaiyuan/122956/ |
| 4271202 | https://zysjonline.com/books/kechenyihua/161390/ |

### Disease/drug catalogue

| doc_id | URL |
|---:|---|
| 4118235 | https://zhongyibaodian.net/a/45377.html |
| 2534385 | https://jbk.39.net/zhengzhuang/xsefx/ |
| 283017 | https://nhathuoclongchau.com.vn/benh/nhiem-trung-tiet-nieu-355.html |
| 3705581 | https://www.familydoctor.com.cn/fuke/a/201709/2262364.html |
| 189365 | https://medlatec.vn/tin-tuc/nhung-dieu-can-luu-y-khi-dung-thuoc-huyet-ap-exforge-5/80mg |
| 565011 | https://suckhoeviet.org.vn/cay-xa-den-tong-quan-dac-diem-va-7-bai-thuoc-tri-benh-hay-10087.html |

### Generic / source ngắn

| doc_id | URL |
|---:|---|
| 491960 | https://suckhoedoisong.vn/benh-ngoai-da-o-nguoi-cao-tuoi-16951442.htm |
| 508553 | https://suckhoedoisong.vn/cum-da-day-gia-tang-dang-bao-dong-hau-covid-169220408093339535.htm |
| 554421 | https://suckhoedoisong.vn/top-8-cay-thuoc-va-bai-thuoc-chua-thieu-mau-co-tim-hieu-qua-169211213155720963.htm |
| 550062 | https://suckhoedoisong.vn/thong-tin-moi-nhat-ve-tinh-trang-4-benh-nhan-vu-lat-xe-o-tam-dao-169250427164653719.htm |
| 520253 | https://suckhoedoisong.vn/hoi-dap-cung-chuyen-gia-lam-dung-thuoc-giam-dau-se-doi-mat-voi-benh-nao-169240106195234585.htm |
| 532419 | https://suckhoedoisong.vn/ngu-dan-song-sot-sau-vu-tau-ca-bi-dam-chim-luc-ay-xac-dinh-chet-chu-khong-song-duoc-169250409105500121.htm |

### Skipped/crawl failure

| doc_id | URL |
|---:|---|
| 319929 | https://pmc-ecm-healthblog.beta.pharmacity.io/hoat-chat-isosorbid-mononitrat/ |
| 320772 | https://pmc-ecm-healthblog.beta.pharmacity.io/mat-thinh-giac-o-nguoi-cao-tuoi-nguyen-nhan-va-giai-phap-hieu-qua/ |
| 2748577 | https://www.120ask.com/question/21765376.htm |
| 662106 | https://thaythuocvietnam.vn/tieu-duong-buoi-sang-nen-an-gi/ |
| 7209877 | https://pubmed.ncbi.nlm.nih.gov/37051953/ |
| 752936 | https://www.vinmec.com/vie/bai-viet/tha-1-nam-chua-co-thai-co-phai-vo-sinh-vi |

### Structured list (toàn bộ nhóm trong test20k)

| doc_id | URL |
|---:|---|
| 6248072 | https://pubmed.ncbi.nlm.nih.gov/27356504/ |
