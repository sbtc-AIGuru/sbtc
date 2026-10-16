# Đặc tả thay thế và tích hợp resource từ vựng y khoa VI/EN/ZH

**Trạng thái:** Đã duyệt và thực hiện pha thu thập/trích xuất read-only, tạo candidate staging ở run08. Chưa hoàn tất legal/semantic gate; chưa thay/xóa resource, chưa sửa analyzer hoặc nạp runtime.  
**Ngày khảo sát:** 15/10/2026  
**Phạm vi dự kiến:** Bộ resource và analyzer tại sbtc/Scripts/Retrieval; dữ liệu nguồn FHIR tại /home/tran-nhat-truong/Downloads/package

## 0. Kết quả triển khai T11 — 15/10/2026

Run canonical: [`artifacts/retrieval/medical-lexicon-staging/20261015-run-08/`](../../../artifacts/retrieval/medical-lexicon-staging/20261015-run-08/). Dùng [`SOURCE_CATALOG.md`](../../../artifacts/retrieval/medical-lexicon-staging/20261015-run-08/SOURCE_CATALOG.md), [`source_manifest.json`](../../../artifacts/retrieval/medical-lexicon-staging/20261015-run-08/source_manifest.json) và [`REPORT.md`](../../../artifacts/retrieval/medical-lexicon-staging/20261015-run-08/REPORT.md) làm báo cáo nguồn, kết quả parse và kiểm chứng.

| Ngôn ngữ | Unique normalized keys | Candidate theo bộ lọc chất lượng | Review | Loadable |
|---|---:|---:|---:|---:|
| VI | 47.058 | 43.746 | 3.312 | 0 |
| EN | 267.768 | 160.102 | 107.666 | 0 |
| ZH | 18.749 | 18.749 | 0 | 0 |

`Candidate` chỉ có nghĩa là qua heuristic lọc hình thức; không phải phê duyệt ngữ nghĩa, quyền tái phân phối hay cho phép nạp runtime. Vì vậy toàn bộ record vẫn `loadable=false`. Tổng unique là sau dedupe theo ngôn ngữ và normalized key; không cộng raw observations giữa nguồn để suy ra số unique.

| Nguồn thực sự đã trích | Kết quả nguồn chính | Giới hạn/trạng thái |
|---|---|---|
| VN Core FHIR 0.10.0, 8 CodeSystem được chọn | VI 10.758 observations; có English designation tường minh ở các resource hỗ trợ | Giữ copyright từng resource; CC-BY package không tự giải quyết quyền upstream; danh sách dài/có mã/đa thành phần được đưa review |
| VietBioNER train | 1.029 mention disease/symptom/procedure, 291 unique normalized VI keys | Surface được tái dựng từ token CoNLL; tất cả giữ review, không dùng validation/test |
| En-ViMedNER train | 27.013 file, 122.017 span; 42.770 unique VI keys | 0 malformed span/offset mismatch; chỉ lấy text span VI và semantic type code, không lấy UMLS concept name/definition hay split dev/test |
| VietENT-Text catalogue | 235 unique VI term/group pairs | Chỉ lấy catalogue, không lấy câu tổng hợp |
| NLM MeSH 2026 | 31.110 descriptor, 235.902 entry term; 267.012 normalized EN keys | 107.390 key ở review, phần lớn do dạng dấu phẩy/entry heading; phải giữ NLM acknowledgement/currentness notice |
| THUOCL medical | 18.749 ZH terms | Dùng `term`; DF chỉ audit, không dùng làm tần số Jieba; giữ citation |

PKU Medical Segmentation Dictionary đã được xác minh metadata CC0 và pin theo DOI/file ID, nhưng file endpoint chính thức trả HTTP 500; **không** thay bằng mirror. Vì vậy ZH output run08 hiện chỉ có THUOCL. SNOMED CT VN, LOINC VN, ICD-10 VN, CMeSH và VietMedCSS Meddict vẫn chưa lấy do artifact/quyền chưa qua gate. Chi tiết trạng thái từng nguồn ở manifest/catalog.

Kiểm chứng run08: SHA-256/kích thước mọi output khớp manifest; JSONL có 47.058/267.768/18.749 dòng đúng ngôn ngữ, đủ trường provenance, key duy nhất và 0 record loadable. Đã băm đối chiếu trực tiếp 27.013 file En-ViMedNER và 8 CodeSystem FHIR với manifest; tất cả khớp. `production_resources_modified=false`. Không chạy benchmark BM25; chưa có đường dẫn `data_final/test.jsonl` được chỉ định/tìm thấy trong khảo sát trước, và bước tích hợp còn chờ legal/semantic review.

Đây là staging candidate cho nguồn đã lấy được, không phải tập nguồn hoàn chỉnh và chưa sẵn sàng đưa vào production. Các run trước được giữ nguyên; run08 là bản canonical để tiếp tục rà soát.

## 1. Mục tiêu

Thay bộ từ điển hiện có trong sbtc/Resources bằng một bộ ba ngôn ngữ có nguồn, phiên bản, loại thuật ngữ và trạng thái quyền sử dụng truy vết được. Tích hợp có kiểm soát vào các bộ lọc từ hiện tại để giữ cụm y khoa tiếng Việt, tiếng Anh và tiếng Trung tốt hơn, đồng thời không làm tăng quá mức các lần khóa sai từ thông thường, câu dài hoặc từ nhập nhằng.

Từ điển chỉ hỗ trợ phân tích và tìm kiếm. Không sửa, dịch, tóm tắt hoặc viết lại văn bản tài liệu/chunk/query. Chuỗi nguồn của mỗi thuật ngữ phải được giữ nguyên bên cạnh khóa chuẩn hóa dùng nội bộ.

Mục tiêu của thay đổi là cải thiện token boundary và mức bao phủ thuật ngữ. Không tuyên bố cải thiện Recall/F2 của cuộc thi trước khi benchmark retrieval có nhãn được phép xác nhận.

## 2. Kết quả khảo sát hiện tại

### 2.1. Package tiếng Việt tại Downloads

Đã đọc metadata và các CodeSystem JSON trong /home/tran-nhat-truong/Downloads/package. Package có 1.356 file, khoảng 103,9 MB; package.json ghi:

- Tên: hl7.fhir.vn.core
- Phiên bản: 0.10.0
- Ngày build: 22/09/2026
- License cấp package: CC-BY-4.0
- Mô tả đây là bản nháp công khai do Omi HealthTech duy trì, chưa phải tiêu chuẩn được cơ quan nhà nước hoặc HL7 International phê duyệt.

License ở package không được xem là xác nhận tự động cho từng CodeSystem. Mỗi resource phải giữ copyright, nguồn, code, phiên bản và hash riêng. Những resource có nguồn thành phần khác hoặc ghi điều kiện sử dụng riêng phải qua rights gate trước khi thành loadable.

Các CodeSystem được trích trong run08, chỉ tính surface tiếng Việt theo quy tắc field/status của parser:

| CodeSystem | Raw VI surfaces | Unique key trong source | Candidate quality | Review | Ghi chú |
|---|---:|---:|---:|---:|---|
| vn-drug-substance-cs | 959 | 919 | 925 | 34 | Tên hoạt chất; có designation và bản ghi bị loại theo status |
| vn-communicable-disease-cs | 81 | 81 | 75 | 6 | Có English designation tường minh riêng |
| vn-yhct-disease-catalog-cs | 4.150 | 464 | 4.147 | 3 | Nhiều code cùng display; dedupe surface nhưng giữ mapping code |
| vn-yhct-disease-cs | 470 | 461 | 0 | 470 | Mục có mã phân loại/phrase nên được giữ review |
| vn-yhct-examination-symptom-cs | 911 | 910 | 787 | 124 | Dấu hiệu/triệu chứng; phrase dài được review |
| vn-yhct-medicine-cs | 771 | 734 | 66 | 705 | Có designation; nhiều tên phối phương dài/đa thành phần |
| vn-yhct-symptom-cs | 3.252 | 823 | 3.039 | 213 | Trùng display cao; English designation được thống kê riêng |
| vn-yhct-treatment-method-cs | 164 | 164 | 163 | 1 | Có English designation riêng |

Parser run08 ghi 10.758 VI surface observations; unique union giữa 8 CodeSystem là 4.063 key (tổng unique riêng từng source là 4.556). English designation có 1.837 observations và 842 key. Một audit sơ bộ trước đó ghi 10.759/4.064 cho hai số VI; chênh lệch một mục chưa được truy nguyên tới record cụ thể, vì vậy dùng manifest/run08 làm số liệu thực thi và giữ sai khác này làm audit note. Đây là candidate strings, không phải thuật ngữ đã thẩm định, concept count hay quyền loadable.

Ví dụ dữ liệu cần phân loại trước khi dùng:

- “Atropin sulfat”, “Bệnh bại liệt”, “Sợ lạnh” là candidate thuật ngữ ngắn.
- “Đau tăng khi trời lạnh, ẩm” là mô tả lâm sàng có cấu trúc câu; không mặc nhiên đưa vào fixed-word list.
- “Diệp hạ châu, nhân trần, bồ công anh” là một display phối hợp nhiều vị thuốc; cần giữ như cụm/candidate riêng, không coi là tên một đơn vị từ.
- Display “Yêu thống — Đau cột sống thắt lưng [M54.5]” có mã trong chuỗi; phải giữ surface nguyên bản và trích code vào field riêng, không làm mất quan hệ giữa chúng.

Các trường hợp cần chặn hoặc giữ riêng:

- vn-icd10-cs.json trong bản local có content=not-present, không có concept[], dù metadata ghi count=16.052. Không trích được ICD-10 từ file local này. Khảo sát web sau đó tìm thấy danh mục ICD-10 Việt Nam 2026 trên CCMS và trang VN Core mô tả artifact riêng 16.052 mã; đây là nguồn bổ sung tiềm năng, nhưng phải pin đúng tệp máy đọc được, hash và quyền tái phân phối trước khi dùng. Không scrape giao diện CCMS làm nguồn tự động.
- vn-cls-cs có 2.964 records nhưng chứa notice về ánh xạ LOINC và 903 display trùng; hold đến khi rà quyền theo thành phần/field.
- vn-icd9-cm-cs có 3.882 records, ghi dựa trên CMS ICD-9-CM; giữ ngoài loadable cho tới khi quyền của dữ liệu gốc/biến thể được xác minh.
- vn-pathogen-cs có 382 records nhưng 4 mục là nhóm notSelectable, còn nhiều tên tác nhân ở dạng Latin/English; không gán cả file thành tiếng Việt. Chỉ nhận các tên sau khi phân loại ngôn ngữ và mục đích.
- vn-specialty-cs có 47 code do dự án gán; chỉ là nguồn phụ nếu thực sự hữu ích, không phải danh mục pháp quy.
- vn-tb-regimen-cs ở trạng thái draft; không đưa vào lần thay thế đầu.
- Không trích từ definition, narrative hoặc code như thể chúng là tên thuật ngữ. Chỉ lấy display và designation.value có language tường minh hoặc được người duyệt phân loại.

### 2.1.1. Nguồn tiếng Việt bổ sung đã khảo sát

| Nguồn | Quy mô/tín hiệu đã xác minh | Vai trò đề xuất | Trạng thái |
|---|---|---|---|
| VN Core FHIR: SNOMED CT VN supplement | Trang thuật ngữ ghi 76.066 mã dịch Việt từ 77.393 concept qua 3 đợt; phạm vi hiện mô tả gồm cấu trúc cơ thể, bất thường hình thái và dị ứng/phát hiện, không phải toàn bộ SNOMED hoặc đầy đủ danh mục bệnh | Nguồn ứng viên cho cụm giải phẫu, dị ứng và phát hiện; giữ mã SNOMED, designation, status, nguồn và phiên bản | Chưa loadable cho tới khi pin artifact và xác minh điều khoản SNOMED/điều khoản dữ liệu riêng |
| VN Core FHIR: LOINC VN supplement 2.78 | Trang thuật ngữ ghi 89.470 Vietnamese designations trên 104.054 mã LOINC; đây là bản 2.78, không phải LOINC hiện hành 2.82 | Nguồn ứng viên mạnh cho xét nghiệm, chỉ số và tên quan sát lâm sàng; không gộp code khác nhau chỉ vì label trùng | Chưa loadable cho tới khi pin artifact, ghi attribution và xác minh điều khoản LOINC/reuse |
| ICD-10 Việt Nam theo TT 06/2026/TT-BYT | CCMS cho tra cứu phân loại; VN Core mô tả artifact riêng 16.052 mã, gồm 15.844 hiện hành và 208 mã inactive | Nguồn bệnh danh/chẩn đoán có độ bao phủ cao; giữ phân biệt mã hiện hành/inactive và các thuộc tính dagger/asterisk | Chờ artifact có thể tải, đối soát nguồn văn bản ký và rights gate; không coi trang tra cứu là giấy phép tái phân phối |
| VietBioNER | Repository ghi CC BY 4.0; toàn bộ corpus có 2.026 mention bệnh/triệu chứng và 482 mention quy trình chẩn đoán theo bảng split; split train có 838 + 191 = 1.029 mention y khoa; số surface duy nhất chưa thống kê | Nguồn phụ tạo candidate đã gán nhãn cho bệnh, triệu chứng và thủ thuật; chỉ dùng train để sinh term; giữ span, split và provenance, rà mẫu trước khi thêm | Có thể đưa train vào candidate staging sau khi pin commit/hash, giữ attribution và kiểm tra điều khoản của nội dung gốc; giữ validation/test độc lập |
| En-ViMedNER | Dataset card khai báo CC BY 4.0; train có 2.635 abstract pairs, 27.013 sentence pairs và 122.017 aligned entity-mention pairs VI/EN; nhãn UMLS semantic type | Nguồn phụ để khai thác surface span tiếng Việt từ các entity pair train, mở rộng bệnh, triệu chứng và thực thể y sinh ngoài nguồn FHIR | Phần lớn corpus là silver-standard dịch/đối chiếu từ MedMentions/PubMed; chỉ 450 câu mini-test được mô tả là người rà. Không nhập tên/CUI/định nghĩa UMLS; kiểm tra điều khoản và provenance nội dung trước khi phân phối | Candidate-only sau khi pin revision/hash; chỉ trích surface VI trong train, không trích test/validation; rà mẫu theo type và độ dài |
| VietENT-Text | Dataset card khai báo CC BY 4.0; 20.908 câu tổng hợp, có catalogue 235 thuật ngữ ENT riêng với `term` và `group`, đối chiếu với ICD-10 Bộ Y tế | Bổ sung hẹp nhưng có cấu trúc cho tai-mũi-họng: bệnh, triệu chứng, thủ thuật, giải phẫu và thiết bị | Câu là dữ liệu tổng hợp, không đại diện văn phong bệnh nhân/bác sĩ thật; catalogue chỉ bao phủ ENT và có thể trùng ICD/FHIR | Có thể staging đúng 235 `term` từ catalogue; không khai thác câu tổng hợp để tạo phrase/alias; giữ group, attribution và provenance |
| VietMedCSS | Dataset card trên Hugging Face mô tả dữ liệu code-switch; nguồn từ điển Meddict gồm 3.203 thuật ngữ có thông tin bảo hộ quyền tác giả, và card yêu cầu kiểm tra quyền trước khi tái phân phối | Có thể hữu ích cho thuật ngữ y khoa Việt-Anh code-switch trong tương lai | Quyền của từ điển nguồn không được giải quyết chỉ bởi license của bản dataset; không có quyền tái phân phối term-level được xác nhận | Không trích term vào resource; giữ làm nguồn tham khảo cho đến khi có chấp thuận bằng văn bản |
| VietMed / MultiMed | Bài báo và repository tác giả mô tả corpus tiếng nói y khoa tiếng Việt, nhưng chưa xác định được artifact từ vựng độc lập cùng license tái phân phối rõ | Nguồn nghiên cứu tiềm năng cho cách diễn đạt lâm sàng và từ nói | Corpus chính là audio/transcript; chưa pin được file dictionary và quyền của từng thành phần | Chưa dùng để tạo term; chỉ khảo sát tiếp khi xác minh được artifact, license và provenance |
| “Towards a UMLS-Integratable Vietnamese Medical Terminology” | Bài nghiên cứu mô tả quy trình xây dựng thuật ngữ y khoa Việt có thể tích hợp UMLS | Hữu ích để lần theo nguồn thuật ngữ/đối chiếu và phương pháp | Chưa tìm thấy bộ từ máy đọc được kèm license tái sử dụng | Tài liệu tham khảo, không phải nguồn để trích term |
| Underthesea DI_Vietnamese-UVD | Tài liệu Underthesea liệt kê đây là từ điển tiếng Việt license “Open”, nhưng không phải từ điển chuyên ngành y | Chỉ dùng làm đối chiếu từ phổ thông/hard-negative hoặc phân tích tokenization; không nhập toàn bộ vào medical lexicon | Không phải nguồn term y khoa |

Các nguồn lớn SNOMED/LOINC/ICD-10 có thể tăng mạnh coverage tiếng Việt, nhưng số mã không đồng nghĩa số surface duy nhất hoặc số term được phép phân phối. Khi quyền chưa rõ, converter chỉ được ghi nhận metadata/đếm schema; không được đưa các label này vào `base_vi.txt` hoặc runtime. VietBioNER chỉ bổ sung candidate y khoa theo nhãn `Symptom_and_Disease` và `DiagnosticProcedure`; bỏ các nhóm `Location`, `DateTime`, `Organisation` khỏi medical lexicon. En-ViMedNER chỉ lấy span tiếng Việt trong train làm candidate lexical; 122.017 là số aligned mention pairs, không phải số từ duy nhất hoặc số term đúng. Không nhập UMLS CUI/label/definition, không dùng validation/test để tránh rò đánh giá, và rà lỗi dịch/biên span vì corpus phần lớn là silver-standard. VietENT-Text chỉ lấy 235 mục `term` của catalogue ENT; không biến câu tổng hợp thành lexical resource. Không dùng PhoNER_COVID19 để tạo resource phân phối: upstream cấm phân phối dataset hoặc một phần của dataset ở cả dạng gốc lẫn đã sửa. VietMedCSS và VietMed chưa đủ điều kiện rights/artifact nên không trích term.

### 2.2. Resource hiện có trong sbtc/Resources

Thư mục hiện có đúng 5 file dữ liệu:

| File hiện tại | Bytes | SHA-256 | Định dạng/vai trò |
|---|---:|---|---|
| sbtc/Resources/base_vi.txt | 4.254.347 | 9ed71eaa46e70d6cf6eea003309b5827e1548a42c6786103e61824de675d39a0 | Một term mỗi dòng |
| sbtc/Resources/base_en.txt | 307.737 | 13f792ce3bceb23e036bed075b97cfaec35c8849b4f24a6d9db8958236fbf858 | Một term mỗi dòng |
| sbtc/Resources/base_zh.txt | 351.160 | 11a5dc93cf9c25ae63000a89adda6dc3783023452bdf4db110e2814209fb1010 | Một term mỗi dòng |
| sbtc/Resources/concepts_aligned_vi_en_zh.jsonl | 136.715 | a4841f80e2bb885d2d29bcc52aad5b5016c29ed0241cd830573d663b32ba1c8b | 856 concept IDs; triples/ICD chưa được xác minh |
| sbtc/Resources/medical_lexicon_vi_en_zh.sample.jsonl | 1.617 | cb8dca0592161f0265ee5f5077b8150e01fcedb91f65eeacb0babed53cc1b4a0 | 8 dòng mẫu; audit trước đó phát hiện ID/alias không đáng tin |

Bản curate trước ghi các base list có 154.122 VI, 12.955 EN và 21.736 ZH dòng; đây là resource chưa rõ provenance/license, chưa qua xác nhận ngữ nghĩa. Aligned concepts có 856 ID/839 triple khác nhau theo label; không thể coi là gold mapping.

Code hiện tại trong Retrieval chỉ đọc base_*.txt và hai file JSONL này qua curate_resources.py. Bộ BM25 đang chạy lấy resource runtime từ sbtc/Scripts/Retrieval/resources, là thư mục khác. Vì vậy thay sbtc/Resources một mình không tự thay lexicon đang nạp vào analyzer hoặc index. Phải cập nhật rõ importer/runtime ở bước tích hợp và chỉ rebuild index sau benchmark.

### 2.3. Kiểm tra benchmark

Trong lần quét hiện tại không thấy data_final/test.jsonl. Đặc tả không cho phép tự thay bằng file test khác hoặc dùng for_valid. Bộ synthetic công bằng medical_analyzer_cases.jsonl vẫn dùng cho regression analyzer; benchmark trên dữ liệu người dùng chỉ thực hiện nếu có đường dẫn test.jsonl đúng yêu cầu.

## 3. Nguồn mới được đánh giá

| Ngôn ngữ | Nguồn | Giá trị | Hạn chế/điều kiện | Quyết định |
|---|---|---|---|---|
| VI | VN Core FHIR package 0.10.0 tại Downloads/package | Có CodeSystem thuốc, bệnh, triệu chứng, YHCT; có code và một số designation EN | Bản public draft; package-level CC-BY không giải quyết thay cho copyright/nguồn riêng từng resource; ICD-10 local chỉ có metadata | Nguồn chính tạo VI candidate; rights review theo từng CodeSystem |
| VI bổ sung | VN Core SNOMED CT VN supplement, LOINC VN 2.78, ICD-10 VN theo TT 06/2026 | Có thể thêm hàng chục nghìn nhãn lâm sàng, xét nghiệm và bệnh danh; có code chuẩn để truy xuất nguồn | Tệp phân phối, bản quyền nguồn gốc và điều khoản sử dụng khác nhau; không suy license từ việc trang FHIR công khai | Ưu tiên xin/pin artifact và xác minh quyền; chỉ nạp sau rights gate |
| VI bổ sung | VietBioNER (repository chính thức của corpus) | Nhãn span bệnh/triệu chứng và quy trình chẩn đoán tiếng Việt; CC BY 4.0 được ghi ở repository | Corpus nhỏ, tập trung văn bản xám lao; các entity span có thể dài hoặc đặc thù; cần rà quyền và attribution của nguồn văn bản | Nguồn candidate phụ sau khi pin commit, trích đúng hai loại y khoa và rà mẫu |
| VI bổ sung | En-ViMedNER (dataset card chính thức) | 122.017 aligned entity-mention pairs trong train; có span Việt-Anh và 21 nhóm semantic type | Silver-standard, thiên về abstract PubMed đã dịch; không coi 122.017 là unique term count; không nhập UMLS concept assets | Candidate-only từ surface VI train; review quality, license/provenance và attribution trước khi load |
| VI bổ sung | VietENT-Text (dataset card chính thức) | 235 thuật ngữ trong catalogue ENT, riêng khỏi 20.908 câu tổng hợp | Phạm vi chuyên khoa hẹp; câu tổng hợp không đại diện corpus tự nhiên | Thêm đúng `term` catalogue vào candidate; bỏ qua câu tổng hợp |
| VI chưa đủ điều kiện | VietMedCSS, VietMed, bài nghiên cứu VNU về thuật ngữ y khoa Việt | Có tín hiệu về từ vựng code-switch, tiếng nói lâm sàng và terminological resource | Chưa có quyền term-level/artifact standalone xác định rõ; ViMedCSS có cảnh báo quyền từ điển nguồn | Không trích terms cho tới khi xác minh rights và artifact |
| EN | NLM MeSH 2026, XML/RDF chính thức; thêm English designations đã khai báo trong các CodeSystem VN | Có descriptor/entry terms có quản lý phiên bản, hữu ích làm phrase và lexical variants | Chỉ dùng dữ liệu tiếng Anh trong MeSH; không lấy bản dịch MTMS theo điều khoản chung; giữ attribution và cảnh báo currentness theo NLM | Nguồn chính cho EN candidate sau khi pin file/hash và giữ notice |
| ZH | Peking University Open Research Data Platform, “Medical segmentation dictionary”, DOI 10.18170/DVN/SDM9GT, version 1.0 | Ghi 87.280 observations, gồm bệnh, triệu chứng, kiểm tra, thuốc, phẫu thuật/điều trị; mỗi term có category và source; điều khoản trang ghi CC0 | Phát hành 2018; cần kiểm tra cấu trúc/nguồn từng record sau tải, chất lượng theo corpus ViBioMIR và có cần account/access hay không | Nguồn chính tiếng Trung; pin DOI/version/file checksum và giữ category/source |
| ZH | THUOCL medical | README upstream ghi 18.749 mục medical; cho phép sử dụng miễn phí cho nghiên cứu và thương mại, yêu cầu trích dẫn THUOCL khi công bố kết quả; hữu ích bổ sung các cụm không có trong PKU | Cập nhật 2017; DF dựa trên Sina News/Sogou/web corpus và không phản ánh tần suất trong corpus ViBioMIR; file LICENSE MIT của repository không được diễn giải thay cho điều kiện data riêng trong README | **Nguồn chính tiếng Trung**, hợp nhất với PKU theo surface; bắt buộc pin commit/file hash, giữ attribution; không dùng DF gốc làm Jieba frequency |
| ZH giữ lại ngoài phạm vi | CMeSH/CUMLS | Nguồn phù hợp chuyên môn; CAMS mô tả CMeSH 2012 gồm MeSH Trung và chủ đề YHCT | Chưa thấy điều khoản tải lại/phân phối machine-readable rõ ràng | Không đưa vào resource cho đến khi quyền được xác nhận |

### 3.1. Ước lượng khối lượng candidate theo nguồn

Các con số dưới đây là quy mô nguồn trước khi gộp giữa nguồn; không phải số dòng loadable sau lọc:

| Ngôn ngữ | Nguồn chính trong lần thay thế | Quy mô đã thấy/ước tính | Ghi chú |
|---|---|---:|---|
| VI | 8 CodeSystem FHIR hiện có + train VietBioNER + train En-ViMedNER + VietENT-Text catalogue | 10.758 FHIR display/designation observations trong run parse; audit trước đó đếm 4.064 exact-normalized unique FHIR surfaces; tối đa thêm 1.029 VietBioNER mention, 122.017 En-ViMedNER aligned mention-pair rows và 235 VietENT terms trước gộp | Đây là số quan sát nguồn, không phải unique terms. Unique union chỉ biết sau parse/dedupe; En-ViMedNER dự kiến tăng candidate volume đáng kể nhưng phải qua silver-standard review; VietENT bổ sung chuyên khoa hẹp |
| VI mở rộng có điều kiện | VN Core SNOMED VI, LOINC VI, ICD-10 VN 2026 | Tối đa khoảng 181.588 label/code observations theo số trang công bố: 76.066 + 89.470 + 16.052 | Cộng số học với các nguồn VI hiện có thì khoảng 315.628 observations thô; đây là upper-bound quy ước vì đơn vị đếm khác nhau (display, mention pair, term, code/label), có trùng lặp và không phải unique/loadable. Chỉ xử lý sau khi pin artifact và rights gate |
| EN | MeSH 2026 preferred headings + entry terms và English designation tường minh từ FHIR | MeSH 2025 có 30.956 main headings làm mốc; 2026 exact count/entry-term surfaces phải đếm từ bản XML đã pin; hiện đã đếm 842 English FHIR surface duy nhất | Không đưa SCR, translation tables hoặc UMLS vào ước lượng này |
| ZH | PKU + THUOCL medical | 87.280 PKU observations + 18.749 THUOCL lines = tối đa 106.029 dòng nguồn trước gộp | Unique final, overlap hai nguồn, và số dòng loadable chỉ chốt sau parse, chuẩn hóa và rà sample; không cộng DF thành term |

Do đó không đặt trước một con số tổng “term sạch” khi chưa chạy converter. Báo cáo sau parse phải tách raw rows, exact-normalized surfaces, overlap giữa nguồn, candidate/review/rejected và loadable theo ngôn ngữ. Trang VN Core xác nhận các quy mô supplement nhưng không làm thay đổi rights gate. THUOCL được tính vào nguồn chính tiếng Trung ngay từ lượt parse đầu, không nằm ở nhánh thử nghiệm tùy chọn.

### 3.2. Kế hoạch lấy và xử lý dữ liệu theo ngôn ngữ

#### Tiếng Việt

| Source ID | Artifact và cách lấy | Trường được trích | Kiểm tra số lượng / lọc |
|---|---|---|---|
| `vi_vncore_fhir_0_10_0` | Đọc package đã có tại `/home/tran-nhat-truong/Downloads/package`; pin `package.json` và hash package/resource files. Parse 8 CodeSystem được liệt kê ở mục 2.1, đệ quy cả `concept` lồng nhau. | `concept.display`; `designation.value` chỉ khi `designation.language` xác định là tiếng Việt. Gắn `system`, `version`, `code`, `parent/path`, `status`, source file/hash và field path. | Audit package trước đó có 10.759 display/designation surfaces; parser run08 trích 10.758 theo status/field rules. Đối chiếu 4.064 surface chuẩn hóa duy nhất từ audit trước. Không lấy `definition`, `code`, narrative hay `notSelectable` làm term. Giữ display dài/list trong review; giữ mapping code khi surface trùng. |
| `vi_vietbioner_train` | Pin commit chính thức, lấy supervised train split từ repository VietBioNER; đọc file annotation/câu ở đúng split và giữ lại tên file/hash. | Surface span nguyên văn theo annotation offset; giữ entity label và offset để truy xuất lại câu nguồn. | Kiểm tra train có 838 `Symptom_and_Disease` + 191 `DiagnosticProcedure` = 1.029 mention. Bỏ `Location`, `DateTime`, `Organisation`; không đụng validation/test. Mọi span lỗi offset hoặc chỉ là ngữ cảnh câu chuyển sang review. |
| `vi_envimedner_train` | Pin Hugging Face dataset revision và các file Parquet/JSON tương ứng; chỉ đọc split `train`. | Trong mỗi JSON sentence record, lấy `data.vi_text` và các annotation `annotations[].result[]` có `from_name=vi_label`, `to_name=vi_text`; lấy `value.text`, `value.start`, `value.end`, `value.labels`. Xác minh `vi_text[start:end] == value.text`. | Đối chiếu 2.635 abstract pairs, 27.013 sentence pairs, 122.017 aligned entity-mention pairs. Giữ mã semantic type thô để phân tầng; đưa type chưa thuộc allowlist đã review vào review, không lấy validation/test hoặc bất kỳ UMLS CUI/name/definition nào. Rà mẫu riêng theo type, độ dài, dấu câu và lỗi dịch/span vì corpus chủ yếu silver-standard. |
| `vi_vietent_catalogue` | Pin revision/hash dataset VietENT-Text và catalogue `hotwords_catalogue_v2.txt` hoặc field catalogue trong Parquet; giữ nguyên source artifact dùng thực tế. | Chỉ lấy `term` và `group`; không lấy `text`, `label`, `quants` để sinh term. | Kiểm tra đúng 235 term và 17 nhóm theo dataset card; dữ liệu 20.908 câu là corpus synthetic, không phải 20.908 term. Exact duplicates gộp theo normalized key nhưng giữ category/source references. |
| `vi_snomed_vn`, `vi_loinc_vn`, `vi_icd10_2026` | Chỉ sau rights gate: lấy đúng artifact máy đọc được do VN Core/đơn vị phát hành cung cấp; ghi URL/file/version/terms/hash. Với ICD-10 phải pin artifact ban hành/được cấp phép; không scrape giao diện CCMS. | Chỉ Vietnamese designation/display, mã concept, status/active, version và trường phân cấp được tài liệu nguồn cho phép. | Dự kiến 76.066 SNOMED, 89.470 LOINC designations, 16.052 ICD entries; kiểm đếm sau tải. Giữ riêng 208 mã ICD inactive; không xuất nguồn này nếu quyền/notice chưa được xác minh. |

#### Tiếng Anh

| Source ID | Artifact và cách lấy | Trường được trích | Kiểm tra số lượng / lọc |
|---|---|---|---|
| `en_vncore_fhir_0_10_0` | Dùng cùng package FHIR đã pin ở source VI. | `designation.value` có `designation.language` là tiếng Anh; giữ code/resource/version và quan hệ với display cùng concept. | Audit hiện có 1.837 designation thô / 842 surface duy nhất. Không suy ngôn ngữ từ nội dung khi field language không có; field thiếu ngôn ngữ đưa vào review. |
| `en_mesh_2026` | Tải Descriptor XML production year 2026 trực tiếp từ NLM; ghi tên file, ngày tải, URL, license/notice và SHA-256. Không dùng bản dịch MeSH. | Main Heading (preferred term), Entry Terms và Descriptor UI/tree/category; lưu relation `preferred`/`entry_term` riêng. | Đếm descriptor và surface entry term trực tiếp từ XML đã pin. 30.956 main headings là số 2025 tham khảo, không dùng làm count của 2026. Bỏ Qualifier/SCR khỏi lượt đầu, trừ khi có quyết định riêng. Giữ điều khoản attribution NLM. |

#### Tiếng Trung

| Source ID | Artifact và cách lấy | Trường được trích | Kiểm tra số lượng / lọc |
|---|---|---|---|
| `zh_pku_medical_segmentation_v1` | Tải version 1.0 từ PKU Open Research Data Platform theo DOI 10.18170/DVN/SDM9GT; lưu file metadata, MD5 do nền tảng cung cấp và SHA-256 sau tải. | Parse file tab theo header thực tế; term, category, source là dữ liệu cần giữ. Không hard-code thứ tự cột trước khi xác minh header. | Đối chiếu 87.280 observations và 5 nhóm (bệnh, triệu chứng, xét nghiệm, thuốc, phẫu thuật/điều trị); báo raw rows, empty/malformed rows và unique terms riêng. |
| `zh_thuocl_medical` | Pin Git commit, tải `data/THUOCL_medical.txt`, snapshot README/điều kiện data và tính SHA-256. | Parse term và DF từ mỗi dòng; giữ DF trong provenance/audit, không dùng trực tiếp để đặt tần số Jieba. | Đối chiếu 18.749 dòng nguồn; báo dòng parse lỗi, term trùng và unique surface. Bắt buộc giữ citation/attribution mà README yêu cầu. |

#### Xử lý chung sau khi trích xuất

1. Ghi surface nguyên văn và mọi source reference trước khi chuẩn hóa. Chuẩn hóa khóa so sánh bằng NFKC, chữ thường/casefold phù hợp ngôn ngữ và gộp khoảng trắng; không bỏ dấu tiếng Việt, không stem, không dịch, không tự đổi giản thể/phồn thể, không sửa surface.
2. Gộp trùng chỉ theo `language + normalized_key`. Mỗi candidate giữ danh sách đầy đủ source IDs, code, category, version, field, hash và relation. Hai surface cùng key không mặc nhiên là synonym hoặc một concept.
3. Gán trạng thái riêng: `candidate`, `review`, `loadable`, `rejected`, `blocked_license`. Lý do lọc/review phải có mã lý do ổn định để thống kê lại được.
4. Chỉ từ `loadable` mới sinh compatibility `base_vi.txt`, `base_en.txt`, `base_zh.txt`; canonical source là JSONL có provenance. Không ghi đè nguồn hay `sbtc/Resources` trong bước lấy và audit.

### 3.3. Hồ sơ nguồn và số liệu phải giữ cho báo cáo

Mỗi lần lấy nguồn tạo một run directory mới, không tái sử dụng/ghi đè run cũ: `artifacts/retrieval/medical-lexicon-staging/<run_id>/`. Bắt buộc ghi `source_manifest.json`, `SOURCE_CATALOG.md`, raw source checksums, parser/config version, per-source audit counts, candidate JSONL, review sample và `REPORT.md`. Không chép nguyên dataset lớn vào repo nếu source terms/license không cho phép; chỉ lưu đường dẫn cache ngoại vi và manifest hash.

`source_manifest.json` ghi ít nhất: `source_id`, publisher/author, canonical URL/DOI, release/version/commit, artifact filename, split, date retrieved, license URL + text snapshot/notice, attribution, upstream-content caveat, file size/hash, parser version, extracted fields, counts và output hashes.

`SOURCE_CATALOG.md` là bảng người đọc có thể trích dẫn khi viết báo cáo. Mỗi source có tên, phạm vi/ngôn ngữ, số lượng upstream đã công bố, count đã parse, giấy phép/điều kiện, attribution, cách truy cập, trường dùng/bỏ, quyết định loadable và giới hạn đại diện. `REPORT.md` phải tách từng nguồn và từng ngôn ngữ, tối thiểu ghi: source rows, records đọc/lỗi, raw surfaces, filtered by reason, exact-normalized unique, cross-source overlap, candidate/review/rejected/blocked/loadable, file hashes và kích thước đầu ra. Count nguồn và count term cuối không được ghi chung một cột.

Kết quả dự kiến sau parse được đối chiếu với số tham khảo ở mục 3.1; mọi sai lệch phải có giải thích (version drift, split, duplicate policy, inactive terms hoặc malformed records), không sửa số cho khớp kỳ vọng.

Nguồn chính thức được kiểm tra:

- NLM MeSH: https://www.nlm.nih.gov/databases/download/mesh.html
- Điều khoản NLM: https://www.nlm.nih.gov/databases/download/terms_and_conditions.html
- PKU dataset: https://doi.org/10.18170/DVN/SDM9GT
- PKU file metadata: https://opendata.pku.edu.cn/file.xhtml?fileId=4667&version=1.0
- THUOCL README/điều kiện dữ liệu: https://github.com/thunlp/THUOCL#开源协议
- THUOCL medical file: https://github.com/thunlp/THUOCL/blob/master/data/THUOCL_medical.txt
- THUOCL repository license (áp dụng cho code/docs, không thay thế mô tả điều kiện sử dụng từ điển trong README): https://github.com/thunlp/THUOCL/blob/master/LICENSE
- CMeSH source description: https://www.imicams.ac.cn/publish/default/yxzszzyjs1/
- VN Core terminology: https://fhir.hl7.org.vn/terminology
- ICD-10 Việt Nam 2026 CCMS: https://icd.kcb.vn/
- VietBioNER corpus và license: https://github.com/ptpuyen1511/VietBioNER
- En-ViMedNER dataset card, split, license và schema: https://huggingface.co/datasets/nhuvo/En-ViMedNER
- VietENT-Text dataset card và ENT term catalogue: https://huggingface.co/datasets/diepduclai/VietENT-Text
- VietMedCSS dataset card (không load trước khi làm rõ quyền của từ điển upstream): https://huggingface.co/datasets/tensorxt/ViMedCSS
- VietMed / MultiMed author repository (nguồn nghiên cứu, chưa có artifact từ điển đủ điều kiện): https://github.com/leduckhai/MultiMed/tree/master/VietMed
- “Towards a UMLS-Integratable Vietnamese Medical Terminology” (tài liệu nghiên cứu, chưa xác định artifact tái sử dụng): https://scholar.vnu.edu.vn/entities/publication/77a60272-bc5f-4ff5-a2e7-86fa36c7f9b3
- Underthesea resource list: https://undertheseanlp.github.io/underthesea/docs
- VN Core FHIR canonical: http://fhir.hl7.org.vn/core

Không dùng UMLS/SPECIALIST đầy đủ, RxNorm full, bản dịch MeSH, CMeSH, SNOMED hoặc danh mục ICD khác nếu chưa có quyền và nguồn máy đọc được được xác nhận.

## 4. Nguyên tắc dữ liệu

### 4.1. Tách ba chức năng

1. Segmentation term: cụm được cho phép giữ liền khi tách từ. Không có nghĩa hai cụm đồng nghĩa.
2. Normalization variant: biến thể chính tả/hình thái có quan hệ được ghi rõ. Luôn giữ literal surface.
3. Concept alias/anchor: chỉ dùng khi có concept ID/crosswalk có căn cứ và equivalence đã được nguồn hoặc người duyệt xác nhận. Không tự suy ra từ việc hai chuỗi cùng xuất hiện ở các file.

Không trộn ba loại trên vào một danh sách. Candidate chưa được duyệt không tự động vào loadable dictionary.

### 4.2. Trích xuất FHIR

- Đọc CodeSystem JSON read-only, đệ quy toàn bộ concept lồng nhau.
- Giữ resource id, canonical URL, version, status, code, parent/path, field nguồn, copyright, sourceOrdinal và hash file.
- Chỉ lấy display và designation.value; ghi nguyên văn. Designation chỉ mang nhãn VI/EN khi language trong dữ liệu ghi rõ. Không biến definition hoặc giá trị property thành term.
- Tôn trọng concept status, notSelectable và các cờ inactive/deprecated; record không selectable chỉ dùng kiểm tra, không vào segmentation.
- Deduplicate theo ngôn ngữ + khóa NFKC/lowercase/whitespace nhưng giữ mọi source refs/code liên quan. Không dedupe theo nghĩa.
- Giữ code ICD, drug code, identifier trong field riêng. Không tự nối code vào surface nếu nguồn không ghi như vậy.
- Chuỗi dài, câu mô tả, phủ định, nhóm tổ chức và list nhiều chất đi vào review class, không vào fixed_words tự động.
- Lưu surface gốc; chuẩn hóa chỉ tạo khóa để lookup. OpenCC, bỏ dấu, stem hoặc rewrite không được thay thế surface.

### 4.3. Trích xuất MeSH và nguồn tiếng Trung

- MeSH: pin production year 2026, XML/RDF exact file hashes, term IDs, descriptor/entry-term relation và English language. Không lấy translation files. Lưu notice bắt buộc của NLM, không gợi ý NLM endorse solution.
- PKU: pin DOI/version/file MD5 từ metadata và hash SHA-256 sau tải. Parse đúng ba biến theo metadata; giữ category/source. Không dùng file clinical case 100 questions làm lexicon.
- THUOCL medical là nguồn chính cùng PKU, không còn là nguồn phụ có điều kiện. Pin commit, SHA-256 của `data/THUOCL_medical.txt`, README/license snapshot và ngày lấy. Parse term cùng DF để audit; trong pack phân phối giữ term, provenance và citation theo README. Không coi file LICENSE MIT của code là license duy nhất của data; cũng không dùng DF gốc trực tiếp làm tần số Jieba vì corpus gốc không đại diện corpus ViBioMIR.
- Gộp PKU và THUOCL theo `language + normalized_key`, nhưng lưu tất cả source refs, category và surface variants. Không xóa dữ liệu gốc giữa các nguồn, không chuyển từ đồng hiện thành synonym, không để THUOCL DF quyết định độ ưu tiên segmentation. Mỗi nguồn được báo riêng số dòng thô, exact duplicate, unique surface và overlap.
- Nguồn tiếng Việt bổ sung: với VietBioNER, chỉ dùng split train và entity type được phép; với En-ViMedNER, chỉ dùng span VI từ train, bỏ CUI/label/definition UMLS và giữ validation/test độc lập; với VietENT-Text, chỉ dùng trường `term` trong catalogue ENT, không học term từ câu tổng hợp. Pin revision/hash, attribution và source refs; candidate En-ViMedNER phải được rà chất lượng vì phần lớn là silver-standard. Không trích VietMedCSS/VietMed cho tới khi có rights/artifact đủ rõ. Với SNOMED/LOINC/ICD-10 VN, chỉ xử lý artifact exact sau khi rights gate được thông qua; nếu chưa có quyền, chỉ lưu source metadata, không xuất labels loadable. Underthesea general dictionary không được trộn vào medical term pack.

### 4.4. Khi nào được tạo concept đa ngữ

- VI/EN cùng một CodeSystem code có thể được ghi thành cặp nếu display/designation thật sự cùng concept và status cho phép.
- ZH chỉ được nối vào concept khi có crosswalk chính thức có quyền sử dụng hoặc được người duyệt song ngữ xác nhận từng mapping.
- Không sinh ZH từ VI/EN bằng dịch máy trong bước xây dictionary.
- Nếu chưa có đủ mapping ZH đáng tin, aligned file mới có thể ít record hoặc rỗng. Đây là báo cáo thiếu coverage có chủ ý, không điền triple đoán.
- Không lấy các triple chưa xác minh trong file cũ làm seed mặc định cho resource mới.

## 5. Output đề xuất

### 5.1. Canonical resources

Sau khi hoàn tất quality/legal gates, bộ resource mới tại sbtc/Resources gồm:

- terms_vi.jsonl
- terms_en.jsonl
- terms_zh.jsonl
- concepts_aligned_vi_en_zh.jsonl
- base_vi.txt, base_en.txt, base_zh.txt: compatibility view một surface mỗi dòng, chỉ gồm term có trạng thái loadable; được sinh deterministic từ JSONL, không phải nguồn sự thật.
- manifest.json: source/release/hash/license/attribution, tool/rule version, record counts theo ngôn ngữ/category/status, file hashes, review history, consumer version.
- README.md: nguồn, điều kiện, cách build/load, giới hạn coverage và cảnh báo.

Mỗi term JSONL có tối thiểu: term_id, language, surface, normalized_key, category, relation_type, status, source dataset/version/resource/code/field/hash, rights status/notice và review note. Source reference phải đủ để tìm lại record gốc.

Aligned concepts phải có concept ID source, labels per language, mapping evidence, reviewer/status và license references. Không được nạp candidate/review/blocked_license vào analyzer production.

### 5.2. Backup và chuyển đổi

Trước khi thay file hiện tại, sao lưu đúng 5 file nêu ở mục 2.2 tới artifacts/retrieval/resource-replacement-backup-20261015/ kèm SHA-256 và README. Sau đó chuẩn bị nguyên cây Resources mới ở thư mục staging ngoài Resources, xác minh đầy đủ, rồi chuyển cây mới vào vị trí đích. Nếu publish hoặc kiểm tra sau publish thất bại, khôi phục từ backup.

Đây là thao tác xóa/thay nội dung trong thư mục dữ liệu. Bước thực hiện chỉ được bắt đầu sau khi người dùng duyệt đặc tả có nêu đủ file và tác động. Không đụng nguồn gốc ở Downloads/package, corpus, chunk, index, data_final, for_valid hoặc resource runtime hiện hữu trong bước thay thế dữ liệu.

## 6. Tích hợp vào bộ tách từ hiện tại

- VI: tạo matcher segmentation riêng. Chỉ cụm loadable đã match trong văn bản hiện tại được truyền vào Underthesea fixed_words; không truyền toàn bộ candidate, và không biến term đơn/ngắn/nhập nhằng thành khóa cứng mặc định.
- ZH: nạp term loadable vào Jieba user dictionary một lần trên mỗi analyzer instance. Tần số của PKU/THUOCL không được dùng trực tiếp; hiệu chỉnh hoặc để mặc định theo behavior đo được. Giữ literal stream/broad tokenization để term mới không làm mất các âm tiết có ích.
- EN: không dùng MeSH như bộ tách từ. Dùng preferred/entry terms trong trường normalization hoặc match phrase có kiểm soát; giữ Lucene EnglishAnalyzer/Krovetz baseline cho đến khi paired evaluation cho thấy adapter mới có lợi.
- Aliases/concept anchors vẫn dùng loader và schema tách biệt. Chỉ aligned concepts đã xác minh mới được truyền cho query bridge/anchor.
- Fingerprint của từng resource manifest phải tham gia analyzer/index/query configuration. Query và document analyzer dùng cùng hash.
- Không sửa nội dung chunk hoặc token xuất thành chunk; không thay BM25 scoring, query translation, reranking hay output schema trong thay đổi này.
- Thay đổi analyzer làm token index khác đi; chỉ rebuild index sau khi kiểm thử trên tập được chỉ định và có quyết định riêng về rebuild. Không đụng index production trong bước thay resource.

## 7. Kế hoạch triển khai sau khi duyệt

| Giai đoạn | Công việc | Cổng kiểm tra |
|---|---|---|
| 1. Pin nguồn | Hash package/version FHIR; pin MeSH 2026, PKU, THUOCL medical, VietBioNER, En-ViMedNER và VietENT-Text; đánh giá artifact SNOMED/LOINC/ICD-10 bổ sung; ghi source URL/DOI/license/attribution/commit/revision/file hash | Thiếu notice/hash thì không xuất loadable; SNOMED/LOINC/ICD-10 chỉ load sau rights gate; THUOCL, VietBioNER, En-ViMedNER và VietENT giữ attribution/citation; source license không được mở rộng sang asset upstream không thuộc license đó |
| 2. Parse và audit | Converter streaming cho FHIR/MeSH/PKU; trích entity mention train từ VietBioNER/En-ViMedNER và riêng field catalogue VietENT; kiểm schema, encoding, hierarchy, language, status, duplicates, long phrases, collisions, entity type, split và span alignment | Mọi record đều có source ref; counts khớp split/catalogue; bỏ validation/test; không đưa text, UMLS concept assets hoặc câu tổng hợp vào term pack |
| 3. Candidate pack staging | Tạo canonical JSONL và compatibility base_*.txt trong artifacts staging; không sửa Resources gốc | JSONL hợp lệ, deterministic, manifest hash khớp, đầu vào không đổi |
| 4. Rà chất lượng | Stratified sample từng ngôn ngữ theo category, source (PKU/THUOCL riêng cho ZH; từng CodeSystem, VietBioNER, En-ViMedNER và VietENT riêng cho VI), length, entity type, split provenance và risk; đánh dấu positive, hard negative, ambiguous; không lấy fixture để tạo từ điển | Báo term chính xác, phrase quá dài, dịch/biên span lỗi, false lock, collisions theo ngôn ngữ và contribution/overlap từng source |
| 5. Quyết định loadable | Tách candidate/review/rejected/license-blocked; nguồn rights chưa rõ không vào base_*.txt | Không còn status thiếu quyền/provenance/review trong loadable |
| 6. Cập nhật importer | Sửa curate_resources.py và tài liệu resource contract để đọc JSONL canonical/manifest; compatibility text chỉ để hỗ trợ công cụ cũ | Không còn phụ thuộc vào medical_lexicon sample không đáng tin; lỗi schema rõ |
| 7. Analyzer ablation | So baseline với từng nguồn riêng và nguồn kết hợp trên bộ analyzer công bằng; cùng query/document analyzer hash | Không tăng lỗi contract/hard-negative; cải thiện phrase boundary có đo lường ở mỗi ngôn ngữ |
| 8. Benchmark dữ liệu test | Nếu người dùng chỉ đúng data_final/test.jsonl, chạy cùng corpus/query test baseline và candidate; không dùng for_valid hoặc thay tập ngầm | Báo cáo per-language/per-risk và paired differences; không suy diễn từ token count |
| 9. Thay Resources | Backup 5 file hiện tại; publish staging đã duyệt; kiểm SHA, record count, parser/load sau publish | Rollback được, nguồn cũ có hash backup, output mới đúng manifest |
| 10. Quyết định tích hợp runtime | Chỉ cập nhật runtime lexicon và rebuild index test nếu analyzer ablation đạt; production/full rebuild là bước riêng | Không có kết quả retrieval được khẳng định nếu chưa benchmark hợp lệ |

## 8. Ca kiểm thử và đánh giá

### 8.1. Dữ liệu và tính công bằng

- Dùng tests/fixtures/medical_analyzer_cases.jsonl hiện có làm regression baseline, không làm nguồn trích term.
- Mở rộng blind adjudication set cân bằng VI/EN/ZH: thuật ngữ y khoa nhiều token, từ thông thường nhập nhằng, mã/liều/đơn vị, Latin kề CJK, cụm phủ định, câu mô tả dài, biến thể chính tả và term ngoài từ điển.
- Chia theo category/source để tránh một nguồn hoặc một kiểu format chi phối.
- Chạy trên data_final/test.jsonl chỉ khi xác định được đúng file; lượt quét hiện không thấy file đó.
- Không dùng for_valid, qrels, query thi hoặc output benchmark để khai thác từ hoặc gán synonym.

### 8.2. Kiểm tra bắt buộc

1. Parse/schema: JSONL UTF-8, field đầy đủ, không record rỗng, mã nguồn duy nhất được giữ.
2. Determinism: cùng source hashes/rule version tạo cùng output hashes.
3. Provenance: 100% term loadable có source version/record/code-or-line/field/hash/license/attribution/status.
4. Duplicate/collision: báo exact duplicate và một surface map tới nhiều code/concept; không xóa mapping khi gộp text.
5. Boundary: term đúng được giữ, hard negative không bị khóa sai; không giảm coverage âm tiết ngoài cụm.
6. Baseline regression: báo từng case đổi kết quả; không nới gold hoặc bỏ case để pass.
7. Per-language quality: phrase preservation, false-lock, OOV/term coverage và unmatched cases tách riêng theo VI/EN/ZH.
8. Runtime: cold load, warm throughput, p50/p95, peak RSS, file size và Jieba/Underthesea initialization cost.
9. Resource integrity: SHA nguồn trước/sau; SHA output trong manifest; rollback được.
10. Retrieval: chỉ kết luận Precision/Recall/F2 nếu có benchmark data/labels được phép. Cải thiện analyzer không tự động chứng minh cải thiện điểm thi.

### 8.3. Tiêu chí chấp nhận đề xuất

- 0 lỗi parse/schema/hash, 100% loadable provenance và quyền sử dụng được ghi rõ.
- Không có nguồn bị chặn quyền trong base_*.txt hoặc runtime analyzer.
- Không tăng contract mismatch/hard-negative false lock so với baseline; mọi thay đổi trên fixture đều được rà.
- Mỗi ngôn ngữ phải có cải thiện đo được ở ít nhất một nhóm thuật ngữ mục tiêu, không tụt nhóm còn lại. Nếu chưa đạt, giữ source ở candidate.
- Công bố count theo source/category/status và resource cost; không lấy tổng số từ làm chỉ số chất lượng.
- Aligned concepts chỉ có mapping verified; thiếu dữ liệu thì báo rõ, không tự dịch.
- Chỉ thay Resources sau khi candidate pack vượt gates; nếu một ngôn ngữ chưa có source loadable, dừng publish cả bộ ba ngôn ngữ để tránh thay một phần.

## 9. Rủi ro và đánh đổi

| Lựa chọn | Lợi ích | Đánh đổi/rủi ro | Giảm thiểu |
|---|---|---|---|
| Bổ sung VietBioNER, En-ViMedNER và VietENT-Text cho VI | Thêm span có nhãn cho disease/symptom/procedure, entity biomedical dịch Việt-Anh và catalogue ENT 235 term | En-ViMedNER chủ yếu silver-standard và có thể có lỗi dịch/span; VietBioNER thiên bệnh lao; VietENT-Text hẹp chuyên khoa và câu tổng hợp không phản ánh cách viết tự nhiên | Candidate-only, chỉ lấy train hoặc trường catalogue được phép; sample theo nguồn/type, ghi attribution và không dùng candidate làm alias/concept |
| Thay base VI 154k chưa rõ nguồn bằng nguồn có provenance | Có mã, category, nguồn và version rõ hơn; các corpus mới thêm span bệnh/triệu chứng/thủ thuật; VN Core supplements có thể mở rộng mạnh nếu rights pass | Bộ hiện đủ điều kiện staging có nhiều observations nhưng số unique/loadable chưa biết; nếu chưa mở được SNOMED/LOINC/ICD-10 thì coverage vẫn có thể thiếu cách gọi phổ thông | Báo count theo nguồn; giữ nguồn lớn ở rights-review, đối chiếu test công bằng; không tuyên bố bao phủ từ lóng |
| Dùng MeSH cho EN | Quản lý phiên bản và thuật ngữ y sinh chuẩn | Thiên về chuẩn hóa, thiếu cách hỏi khẩu ngữ; entry term không phải lúc nào cũng synonym tuyệt đối | Tách segmentation/normalization/alias; alias cần kiểm soát |
| Dùng PKU 87k cho ZH | Đúng mục đích phân đoạn, có category/source, CC0 và DOI | Cũ từ 2018; từ vựng có thể lệch nội dung corpus; access/hash phải kiểm chứng | Rà record, benchmark từng category, không dùng raw frequency |
| Dùng THUOCL làm nguồn chính cùng PKU | Thêm đến 18.749 candidate y tế và cụm từ; upstream README cho phép nghiên cứu/thương mại và yêu cầu citation khi công bố | Dữ liệu từ 2017; DF phản ánh corpus Sina/Sogou, không khớp corpus thi; LICENSE MIT của repo không thay thế điều khoản data trong README | Nạp vào candidate union chính, pin commit/file hash, giữ citation/provenance, bỏ DF khỏi Jieba frequency và đo contribution riêng |
| Giữ concept anchors thận trọng | Tránh alias sai kéo candidate nhiễu | Số concept aligned mới có thể ít hơn 839 triple cũ | Chỉ tạo mapping có bằng chứng; dùng lexical retrieval cho phần còn thiếu |
| Thay tại root Resources | Dọn bỏ dữ liệu cũ không provenance khỏi nguồn đang curate | Converter hiện phụ thuộc base_*.txt và file sample; có thể hỏng consumer nếu không migrate cùng lúc | Staging, sửa importer, backup, publish/rollback có manifest |

## 10. Ngoài phạm vi

- Không xóa gốc ở Downloads/package.
- Không sửa dữ liệu crawl, chunk, index, output submit, query hoặc bài nộp.
- Không đổi BM25 scoring, chiến lược top-k/fusion, dịch query, model, reranker hay API.
- Không dùng term dictionary để viết lại chunk/query.
- Không tải full UMLS/RxNorm/CMeSH hoặc nguồn có điều khoản chưa xác định vào resource.
- Không xóa/ghi đè sbtc/Scripts/Retrieval/resources/curated/20261015 hoặc resource runtime đang dùng.
- Không chạy full corpus hoặc rebuild production index trong pha này.

## 11. Quyết định đề nghị

Duyệt hướng sau:

1. Tạo candidate pack VI từ VN Core FHIR, train VietBioNER, train En-ViMedNER và catalogue term VietENT-Text; MeSH 2026 cho EN; hợp nhất PKU Medical Segmentation Dictionary + THUOCL medical làm nguồn chính ZH. SNOMED/LOINC/ICD-10 VN chỉ thêm sau khi pin đúng artifact và rights gate pass. VietMedCSS, VietMed và bài nghiên cứu VNU vẫn là nguồn chưa đủ điều kiện nạp.
2. Rà candidate, schema, provenance và benchmark analyzer công bằng trước.
3. Khi đủ ba ngôn ngữ loadable, backup đúng 5 file cũ, thay nội dung sbtc/Resources bằng bộ mới có JSONL provenance và compatibility base_*.txt.
4. Cập nhật importer resource để các file mới có đường đi tới analyzer; chỉ bật runtime/new index nếu ablation đạt.
5. Giữ nguyên file mẫu medical_lexicon_vi_en_zh.sample.jsonl trong backup, bỏ khỏi thư mục active Resources vì các record hiện không đủ tin cậy.

Đặc tả không cho phép xóa backup hay tuyên bố tăng F2. Bước triển khai cần được duyệt riêng sau khi người dùng xem đặc tả và danh sách tác động ở mục 2.2.
