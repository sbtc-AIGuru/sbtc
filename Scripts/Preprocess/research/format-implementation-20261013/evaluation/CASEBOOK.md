# Casebook trước–sau format chunking

Các trích đoạn dưới đây là source nguyên bản. Dấu cắt trong snippet chỉ để trình bày; file output chứa đầy đủ source slice.

## doc_id 7156587 — research_abstract

Abstract EN/ZH có vùng riêng, không overlap qua transition.

[Nguồn dòng 101](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:101) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:101) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000000.jsonl:101)

Chunks 4 → 4; sizes mới: [204, 176, 274, 279]

Languages: ['en', 'zh']; exclusions: []

Child đầu tiên mới:
```text
[Clinical and gastroscopic features of children with cyclic vomiting syndrome: an analysis of 63 cases].

OBJECTIVES: To study the clinical and gastroscopic features of children with cyclic vomiting syndrome.

METHODS: A retrospective analysis was performed on the medical data of 63 children with cyclic vomiting syndrome who were hospitalized and followed up in Beijing Tsinghua Changgung Hospital, School of Clinical Medicine, Tsinghua University from August 2019 to March 2022.

RESULTS: Among th
```

## doc_id 6954391 — research_abstract

Regression: title + abstract ngắn vẫn một chunk.

[Nguồn dòng 102](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:102) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:102) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000000.jsonl:102)

Chunks 1 → 1; sizes mới: [228]

Languages: ['en', 'und']; exclusions: []

Child đầu tiên mới:
```text
Novel Guarded Needle Trans-Scleral Biopsy for Uveal Melanoma: A Pilot Study.

INTRODUCTION: Trans-scleral biopsy of uveal melanoma (UM) poses an inherent risk of tumor and possibly retinal perforation. We describe a novel technique for trans-scleral biopsy of UM and evaluate its safety and efficacy in an initial cohort of patients.

METHODS: A retrospective, consecutive observational case series was conducted from October 14, 2019, to April 15, 2020, at Kaiser Permanente, San Francisco, CA among
```

## doc_id 7147848 — research_abstract

Biểu thức ES/CI có ngoặc được giữ nguyên.

[Nguồn dòng 243](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:243) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:243) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000000.jsonl:243)

Chunks 2 → 2; sizes mới: [159, 201]

Languages: ['en']; exclusions: []

Child đầu tiên mới:
```text
Effect of physical activity on the risk of frailty: A systematic review and meta-analysis.

OBJECTIVE: The relationship between physical activity (PA) and the risk of frailty has not reached a conclusive result. This systematic review with meta-analysis aimed to evaluate the effect of PA on the onset of frailty in the community-dwelling middle and older age adults by pooling data from cohort studies.

METHODS: A systematic literature search was performed via PubMed, Embase, and Web of Science up
```

## doc_id 6333519 — research_abstract

Tỷ lệ randomisation (1:1) và câu >50 units được giữ nguyên.

[Nguồn dòng 481](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:481) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:481) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000000.jsonl:481)

Chunks 3 → 2; sizes mới: [254, 288]

Languages: ['en', 'und']; exclusions: []

Baseline, đoạn cuối:
```text
to pegylated interferon were not eligible. A centralised randomisation used computer-generated lists of random permuted blocks of four with stratification by HBsAg titres (< or ≥2·25 log10 IU/mL) to allocate patients (1:
```

Bản mới, source quanh biểu thức:
```text
sts of random permuted blocks of four with stratification by HBsAg titres (< or ≥2·25 log10 IU/mL) to allocate patients (1:1) to receive a 48 week course of subcutaneous injections of 180 μg per week of pegylated interferon alfa-2a in addition to the nucleos(t)ide analogue regimen or to continue to receive nucleos(t)ide analogues only.
```

## doc_id 5714388 — research_abstract

$10,100 không bị cắt ở thousands separator.

[Nguồn dòng 676](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:676) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:676) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000000.jsonl:676)

Chunks 2 → 2; sizes mới: [184, 171]

Languages: ['en', 'und']; exclusions: []

Baseline, đoạn cuối:
```text
1.5% had very high TG levels (≥500 mg/dl). After adjustment, the patients with TG levels ≥500 mg/dl (severe hypertriglyceridemia) had significantly greater mean total costs ($8,567, 99% confidence interval $7,034 to $10,
```

Bản mới, source quanh biểu thức:
```text
/dl (severe hypertriglyceridemia) had significantly greater mean total costs ($8,567, 99% confidence interval $7,034 to $10,100) than those with levels <150 mg/dl ($6,186, 99% confidence interval $6,058 to $6,314), 150 to 199 mg/dl ($6,449, 99% confidence interval $6,196 to $6,702), or 200 to 499 mg/dl ($6,376, 99% confidence interval $6,
```

## doc_id 5294437 — research_abstract

i.v. đi cùng tên thuốc Nytroglicerin nguyên bản.

[Nguồn dòng 2174](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:2174) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000002.jsonl:174) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000002.jsonl:174)

Chunks 3 → 3; sizes mới: [231, 257, 210]

Languages: ['en', 'und']; exclusions: []

Child đầu tiên mới:
```text
[Posterior reversible encephalopathy syndrome].

INTRODUCTION: Reversible Posterior Leukoencephalopathy Syndrome was introduced into clinical practice in 1996 in order to describe unique syndrome, clinically expressed during hypertensive and uremic encephalopathy, eclampsia and during immunosuppressive therapy [1]. First clinical investigations showed that leucoencephalopathy is major characteristic of the syndrome, but further investigations showed no significant destruction in white cerebral t
```

## doc_id 6480634 — research_abstract

11,6 và nội dung French/Spanish được giữ; không kế thừa en cho đoạn dài.

[Nguồn dòng 3333](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:3333) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000003.jsonl:333) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000003.jsonl:333)

Chunks 5 → 5; sizes mới: [273, 210, 175, 234, 174]

Languages: ['en', 'es', 'fr', 'und']; exclusions: []

Baseline, đoạn cuối:
```text
eint d’un DM nouveau a débuté; un traitement hypoglycémiant pendant le suivi. L’HbA1c médiane des participants ayant un DM connu, nouveau et pas de DM a été respectivement de 10,1% (intervalle interquartile [IQR] 8,3–11,
```

Bản mới, source quanh biểu thức:
```text
 participants ayant un DM connu, nouveau et pas de DM a été respectivement de 10,1% (intervalle interquartile [IQR] 8,3–11,6), 8,5% (IQR 6,7–11,5) et 5,6% (IQR 5,3–5,9) à la mise en route du traitement et de 8,7% (IQR 6,8–11,3), 7,1% (IQR 5,8–9,5) et de 5,3% (IQR 5,1–5,6) à l’achèvement du traitement (P < 0,001).
```

## doc_id 5180531 — research_abstract

Koes et al. đi cùng [33] reviewed, không đóng child ở tên tác giả viết tắt.

[Nguồn dòng 3733](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:3733) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000003.jsonl:733) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000003.jsonl:733)

Chunks 7 → 6; sizes mới: [231, 260, 278, 255, 278, 206]

Languages: ['en']; exclusions: []

Child đầu tiên mới:
```text
[Relevance of nerve blocks in treating and diagnosing low back pain--is the quality decisive?].

Diagnostic nerve blocks: The popularity of neural blockade as a diagnostic tool in painful conditions, especially in the spine, is due to features like the unspecific character of spinal pain, the irrelevance of radiological findings and the purely subjective character of pain. It is said that apart from specific causes of pain and clear radicular involvement with obvious neurological deficits and co
```

## doc_id 5846763 — research_abstract

Title dài 122 chars gắn với thân, không tạo child title riêng.

[Nguồn dòng 3754](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:3754) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000003.jsonl:754) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000003.jsonl:754)

Chunks 8 → 7; sizes mới: [286, 236, 277, 275, 239, 162, 196]

Languages: ['en']; exclusions: []

Child đầu tiên mới:
```text
Toxicology and carcinogenesis study of styrene-acrylonitrile trimer in F344/N rats (perinatal and postnatal feed studies).

UNLABELLED: Styrene-acrylonitrile trimer (SAN Trimer) is a mixture of isomers formed by the condensation of two moles of acrylonitrile and one mole of styrene and has a molecular weight of 210. The mixture is composed of two structural forms: 4-cyano-1,2,3,4-tetrahydro-a-methyl-1-naphthaleneacetonitrile (THNA, CAS No. 57964-39-3) and 4-cyano-1,2,3,4-tetrahydro-1-naphthalene
```

## doc_id 5467809 — research_abstract

Ngoặc lỗi nguồn không ghép xuyên hai abstract; có warning review.

[Nguồn dòng 4292](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4292) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:292) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:292)

Chunks 11 → 9; sizes mới: [250, 287, 284, 201, 268, 223, 249, 292, 224]

Languages: ['en', 'fr', 'und']; exclusions: []

Child đầu tiên mới:
```text
Chiropractic clinical practice guideline: evidence-based treatment of adult neck pain not due to whiplash.

OBJECTIVE: To provide an evidence-based clinical practice guideline for the chiropractic cervical treatment of adults with acute or chronic neck pain not due to whiplash. This is a considerable health concern considered to be a priority by stakeholders, and about which the scientific information was poorly organized.

OPTIONS: Cervical treatments: manipulation, mobilization, ischemic press
```

## doc_id 6248072 — structured_list

Entries O/P giữ record; đây là chương trình hội nghị, không phải full nghiên cứu.

[Nguồn dòng 4304](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4304) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:304) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:304)

Chunks 10 → 8; sizes mới: [233, 260, 283, 256, 300, 233, 294, 278]

Languages: ['en']; exclusions: []

Child đầu tiên mới:
```text
Proceedings of The 8th Romanian National HIV/AIDS Congress and The 3rd Central European HIV Forum : Sibiu, Romania. 5-7 May 2016.

O1 HIV-1 diversity in Bulgaria (current molecular epidemiological picture) Ivailo Alexiev, Reneta Dimitrova, Anna Gancheva, Asya Kostadinova, Mariyana Stoycheva, Daniela Nikolova, Ivaylo Elenkov O2 Knowledge, attitudes and practices of the general population on HIV/AIDS, hepatitis B and C in Romania Cătălin Tilișcan, Mioara Predescu, Bogdan Păunescu, Anca Streinu-Cer
```

## doc_id 7286850 — research_abstract

vs. giữ cùng vế so sánh laparoscopic theo sau.

[Nguồn dòng 4329](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4329) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:329) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:329)

Chunks 6 → 5; sizes mới: [252, 285, 279, 271, 209]

Languages: ['en']; exclusions: []

Child đầu tiên mới:
```text
Robotic-assisted single-site abdominal cerclage in the bicornuate uterus patient with cervical insufficiency.

OBJECTIVE: To demonstrate the surgical techniques for improving safety in robotic-assisted abdominal cerclage in patients with bicornuate uteri complicated by recurrent pregnancy loss and cervical insufficiency.

DESIGN: Stepwise demonstration with narrated video footage.

SETTING: An academic tertiary care hospital.

PATIENTS: Our patient is a 22-year-old G2P0020 with a history of recu
```

## doc_id 269380 — narrative_article

Cảm giác tội lỗi: đi cùng nội dung theo sau.

[Nguồn dòng 4580](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4580) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:580) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:580)

Chunks 9 → 8; sizes mới: [230, 286, 269, 279, 255, 224, 191, 192]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Tích cực độc hại (Toxic Positivity) là gì? Cách nhận diện và phòng tránh

Cụm từ “tích cực độc hại” có vẻ còn khá mới mẻ nhưng số đông mọi người đều từng nhiều hơn một lần thể hiện tư duy tích cực độc hại. Tích cực là điều tốt nhưng tích cực độc hại lại gây ra nhiều ảnh hưởng cả về thể chất và tinh thần. Biết cách nhận biết và tránh tích cực độc hại sẽ giúp chúng ta tiếp cận cảm xúc và sức khỏe tinh thần một cách lành mạnh hơn.

Đã khi nào bạn gặp phải một vấn đề tồi tệ, bạn chia sẻ cùng với ai 
```

## doc_id 218831 — narrative_article

Regression: câu đầy đủ, cuối tài liệu có dấu ! nguyên bản.

[Nguồn dòng 4583](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4583) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:583) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:583)

Chunks 5 → 5; sizes mới: [220, 274, 253, 273, 238]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Cách diệt chấy bằng máy sấy tóc có thực sự hiệu quả?

Trẻ em trong độ tuổi từ mầm non đến tiểu học dễ bị lây chấy từ bạn bè. Khi phát hiện bé có chấy, mẹ có thể áp dụng một số cách diệt chấy tại nhà. Trong đó diệt chấy bằng máy sấy tóc. Vậy cách diệt chấy bằng máy sấy tóc có thực sự hiệu quả?

Trẻ em trong độ tuổi từ mẫu giáo đến tiểu học rất dễ bị chấy do lây từ lớp học. Có nhiều cách trị chấy khác nhau, trong đó cách diệt chấy bằng máy sấy tóc được nhiều người truyền tai nhau. Tuy nhiên, cách 
```

## doc_id 223012 — narrative_article

Câu dẫn dài kết colon phải đi cùng body.

[Nguồn dòng 4590](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4590) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:590) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:590)

Chunks 6 → 5; sizes mới: [238, 271, 247, 198, 198]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Chăm sóc não bộ tốt hơn với viên uống tăng tuần hoàn máu não Pikolin Ocavill

Trong số các sản phẩm thực phẩm chức năng chăm sóc sức khỏe não bộ trên thị trường hiện nay viên uống tăng tuần hoàn máu não Pikolin Ocavill đang được rất nhiều người tin dùng. Vậy sản phẩm này có tốt hay không?

Não bộ là cơ quan có vai trò quan trọng hàng đầu trong cơ thể. Suy giảm chức năng não bộ có thể gây ra rất nhiều hệ lụy xấu đối với con người. Chăm sóc sức khỏe của não bộ ngay từ bây giờ là điều hết sức quan 
```

## doc_id 244904 — narrative_article

Câu dẫn nguyên nhân ở trẻ không treo ở cuối child.

[Nguồn dòng 4596](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4596) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:596) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:596)

Chunks 6 → 5; sizes mới: [272, 294, 283, 260, 255]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Mách mẹ các món ăn vặt tăng cường hệ miễn dịch cho trẻ

Trẻ nhỏ có hệ miễn dịch kém thường bị ốm vặt và cơ thể không thể phát triển toàn diện. Các mẹ bỉm nên bổ sung các món ăn vặt tăng cường miễn dịch cho trẻ để con khỏe mạnh mỗi ngày.

Trẻ nhỏ có hệ miễn dịch kém thường dễ bị ốm vặt khiến sức khoẻ thêm suy yếu. Bên cạnh đó, bé cũng sẽ nhẹ cân và chiều cao kém phát triển hơn so với các bạn đồng trang lứa. Một số món ăn vặt tăng cường miễn dịch cho trẻ dưới đây nên được các mẹ bỉm bổ sung cho co
```

## doc_id 264212 — narrative_article

24.7mg không phải heading số thứ tự.

[Nguồn dòng 4605](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4605) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:605) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:605)

Chunks 8 → 6; sizes mới: [223, 281, 276, 285, 254, 276]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Tác dụng của cà chua đối với nam giới và những lưu ý khi sử dụng

Từ lâu cà chua đã được mệnh danh là một trong những thực phẩm cực tốt cho nam giới vì chứa nhiều dưỡng chất có lợi, đặc biệt là các chất chống oxy hóa. Tác dụng của cà chua đối với nam giới được khoa học chứng minh tính hiệu quả, thực tế.

Cà chua là thực phẩm giàu dinh dưỡng và được dùng nhiều trong chế biến món ăn của người Việt. Theo nhiều tài liệu y học và nghiên cứu cho thấy, tác dụng của cà chua đối với nam giới bao gồm tăng
```

## doc_id 279805 — disease_drug_catalogue

TOC/menu và title/date trùng có ledger; title giữ trong context metadata.

[Nguồn dòng 4881](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4881) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:881) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000004.jsonl:881)

Chunks 16 → 7; sizes mới: [139, 224, 274, 280, 297, 292, 163]

Languages: ['und', 'vi']; exclusions: ['duplicate_title_before_navigation', 'store_navigation', 'catalogue_header_context', 'repeated_field_toc', 'repeated_field_toc', 'related_articles_navigation']

Child đầu tiên mới:
```text
Xem video

Bác sĩ

Dương Bích Tuyền

Đã kiểm duyệt nội dung

Tốt nghiệp tại Đại học Y Dược Cần Thơ và sở hữu chứng chỉ Chuyên khoa I - Y học gia đình tại Đại học Y Dược TP. Hồ Chí Minh. Đồng thời có hơn 7 năm kinh nghiệm chuyên môn trong lĩnh vực khám sàng lọc tiêm chủng.

Xem thêm thông tin

Viêm là một quá trình mà các tế bào bạch cầu của cơ thể bảo vệ cơ thể khỏi bị nhiễm trùng từ những tác nhân lạ bên ngoài như vi khuẩn hoặc virus. Tuy nhiên cũng có một số trường hợp hệ thống miễn dịch tấn c
```

## doc_id 211401 — narrative_article

37,5 độ C: baseline cắt ở comma; bản mới giữ câu.

[Nguồn dòng 5277](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:5277) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000005.jsonl:277) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000005.jsonl:277)

Chunks 4 → 3; sizes mới: [245, 228, 295]

Languages: ['und', 'vi']; exclusions: []

Baseline, đoạn cuối:
```text
hiêm trọng sau khi được bác sĩ khám sàng lọc kỹ lưỡng.

Theo hướng dẫn tại Quyết định 2470/QĐ-BYT ngày 14/6/2019 về khám sàng lọc trước tiêm chủng, trẻ em từ 1 tháng tuổi trở lên có thể được tiêm vắc xin nếu sốt dưới 37,
```

Bản mới, source quanh biểu thức:
```text


Trả lời

Được giải đáp bởi Bác sĩ Chuyên khoa 1 - Nguyễn Thu Hà

Nhiệt độ cơ thể bình thường ở trẻ dao động từ 36,5 - 37,5 độ C, nên nhiệt độ khoảng 37 độ C không được coi là sốt. Trong trường hợp này, trẻ vẫn đủ điều kiện để tiêm vắc xin nếu không có dấu hiệu bệnh lý nghiêm trọng sau khi được bác sĩ khám sàng lọc kỹ lưỡng.

Theo hướng 
```

## doc_id 283585 — narrative_article

Ngoặc MRSA qua anchors/newline giữ cùng atom.

[Nguồn dòng 5915](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:5915) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000005.jsonl:915) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000005.jsonl:915)

Chunks 2 → 2; sizes mới: [201, 209]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Viêm cầu thận sau nhiễm trùng (PIGN)

Viêm cầu thận sau nhiễm trùng (PIGN) là gì?

Viêm cầu thận sau nhiễm trùng (postinfection glomerulonephritis - PIGN) có thể xảy ra liên quan đến vi khuẩn, virus, nấm và ký sinh trùng khác. Mối liên quan điển hình của

viêm cầu thận

với nhiễm trùng đó là viêm cầu thận hậu nhiễm liên cầu trùng (thường phát triển sau

viêm họng nhiễm liên cầu khuẩn

tán huyết beta nhóm A).

Tuy nhiên, trong những thập kỷ gần đây, độ phổ biến của viêm cầu thận sau nhiễm trùng đ
```

## doc_id 263670 — narrative_article

Ngoặc tiêu chảy qua newline không tạo child bắt đầu bằng dấu đóng ngoặc.

[Nguồn dòng 8208](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:8208) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000008.jsonl:208) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000008.jsonl:208)

Chunks 8 → 7; sizes mới: [247, 283, 266, 271, 268, 213, 224]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Sữa mẹ để ngăn mát được bao lâu? Giải thích cho mẹ

Sữa mẹ để ngăn mát được bao lâu? Mẹ cùng Nhà Thuốc Long Châu giải đáp thắc mắc này ngay trong bài viết chi tiết dưới đây.

Để giữ sữa mẹ tươi lâu và tránh vi khuẩn, nhiều người thường đặt sữa vào tủ lạnh. Tuy nhiên, không phải ai cũng biết cách bảo quản sữa mẹ đúng cách và bảo quản được bao lâu là thích hợp. Vậy sữa mẹ để ngăn mát được bao lâu? Cùng

Nhà Thuốc Long Châu

tìm hiểu chi tiết trong bài viết này!

Sữa mẹ để ngăn mát được bao lâu?

Đ
```

## doc_id 259400 — narrative_article

2,2 không ăn G của Gợi ý vào numeric span.

[Nguồn dòng 8456](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:8456) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000008.jsonl:456) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000008.jsonl:456)

Chunks 6 → 5; sizes mới: [247, 291, 266, 257, 208]

Languages: ['und', 'vi']; exclusions: []

Child đầu tiên mới:
```text
Pound là gì? 1 pound bằng bao nhiêu kg?

“Pound” là một đơn vị đo khối lượng quen thuộc trong hệ thống đo lường Anh - Mỹ, thường xuyên xuất hiện trong các tài liệu quốc tế, hướng dẫn sử dụng, thực đơn dinh dưỡng, và đặc biệt phổ biến trong các bài viết về sức khỏe, thể hình. Vậy pound là gì, cách quy đổi ra sao và sử dụng như thế nào cho đúng?

Tại Việt Nam, đơn vị đo khối lượng được sử dụng phổ biến và chính thức là kilogram (kg), vốn thuộc hệ đo lường quốc tế SI (International System of Units)
```

## doc_id 4271202 — tcm_book

Giữ nguyên liệu/liều và quoted snippets; không xóa toàn tail theo 原文 →.

[Nguồn dòng 10581](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:10581) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000010.jsonl:581) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000010.jsonl:581)

Chunks 33 → 27; sizes mới: [233, 275, 280, 275, 297, 227, 277, 288, 255, 272, 238, 279, 279, 256, 256, 244, 295, 262, 297, 282, 228, 259, 271, 270, 297, 236, 278]

Languages: ['und', 'zh']; exclusions: ['book_pagination']

Child đầu tiên mới:
```text
产后述略

妇人之病，莫重于产后，因气血大亏，内而七情，外而六气，稍有感触，即足致病。且多疑似之症，毋徒以逐瘀为事，以致变端百出。读《金匮》书中，有用大黄等峻剂者，非古人立法之不善也，盖以古时禀气之足，或西北地土坚浓，人亦强壮，用之良善。至于吾地，体质柔弱，深闺娇养，岂能受此侵克，此看病之不可泥于古也。时人每谓产后不可补，恐其瘀阻，往往用苏木、红花等，行瘀为先务。设或血行不止，立见厥脱，急难措手，可不惧哉。丹溪云∶产后以大补气血为主，虽有他症以末治之。王肯堂云∶产后用下药者，百无一生。诚哉是言也。

《金匮要略》云∶新产妇人有三病∶一病痉，二病郁冒，三病大便难。
```

## doc_id 4265827 — tcm_book

Arrow lật trang exclude; nội dung B12 giữ nguyên.

[Nguồn dòng 13393](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:13393) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000013.jsonl:393) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000013.jsonl:393)

Chunks 2 → 2; sizes mới: [167, 217]

Languages: ['zh']; exclusions: ['book_pagination']

Child đầu tiên mới:
```text
脊髓亚急性合并变性

这是一种由于维生素B12缺乏所造成的脊髓变性，因为主要造成后束（主管深感觉）与侧束（主管运动）的变性，故称合并变性。事实上，本病还累及大脑，可以出现精神症状，也可以累及周围神经系统，引起多发性末梢神经炎。长期素食与胃切除手术是本病最常见的病因，补充维生素B12能使病情改善。

只有荤食中含有维生素B12，素食中不含这种维生素，所以长期素食者容易发生维生素B12的缺乏。
```

## doc_id 1067218 — qa

病情分析/指导意见 gắn body; answer có question_span nguồn.

[Nguồn dòng 15526](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:15526) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000015.jsonl:526) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000015.jsonl:526)

Chunks 2 → 2; sizes mới: [242, 124]

Languages: ['zh']; exclusions: []

Child đầu tiên mới:
```text
糖尿病患者能怀孩子么？
健康咨询描述： 空腹血糖一直在十以上
曾经的治疗情况和效果： 用过胰岛素,现在用比格列酮和格列奇特缓释片
想得到怎样的帮助：想要孩子,可以么?今年38岁,了
您好：在血糖控制正常情况下,可以要孩子.正常的空腹血糖3.89-6.1 mmol/L,正常的餐后2小时血糖小于7.8mmol/L,目前您的血糖控制不佳,建议到专科医院调整治疗,并且在怀孕前3个月和怀孕期间必须要用胰岛素控制血糖,因为口服降糖药物和高糖毒性容易导致胎儿畸形或流产.另外,您38岁属于高龄产妇,注意事项较多,一定前往医院进行咨询,定期到有条件的妇产科进行母胎监护和必要的防治措施.祝您心想事成!
```

## doc_id 1128713 — qa

Regression: QA ngắn vẫn một chunk đầy đủ.

[Nguồn dòng 15530](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:15530) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000015.jsonl:530) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000015.jsonl:530)

Chunks 1 → 1; sizes mới: [159]

Languages: ['zh']; exclusions: []

Child đầu tiên mới:
```text
我现在满身上长满了小红点,非常痒洗热水澡时
健康咨询描述： 我现在满身上长满了小红点,非常痒洗热水澡时,更痒爱抓,越抓越大.跟大豆一样.非常痒还抓破皮了,怎么办,求教您医师.
上班时候都没心事了.快速治疗.好让我好好上班
本次发病及持续时间:一星期多了非常困人.
以往诊断治疗经过及效果:有治疗过说什么.(麻疹)
建议口服赛庚啶、甲氰咪胍、维生素C、维生素B6，外用尤卓尔治疗。
```

## doc_id 2335124 — qa

Bio có marker đôi được exclude, câu trả lời vẫn index.

[Nguồn dòng 15533](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:15533) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000015.jsonl:533) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000015.jsonl:533)

Chunks 3 → 4; sizes mới: [9, 263, 210, 206]

Languages: ['zh']; exclusions: ['doctor_biography']

Child đầu tiên mới:
```text
肠系膜脂肪炎的症状
```

## doc_id 1138672 — qa

Lời người hỏi chào bác sĩ nằm trong question, không gán vào answer.

[Nguồn dòng 15592](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:15592) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000015.jsonl:592) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000015.jsonl:592)

Chunks 3 → 3; sizes mới: [203, 194, 164]

Languages: ['zh']; exclusions: []

Child đầu tiên mới:
```text
我是一名高三的学最近看过几个有关白血病的报告,心里总是害怕
健康咨询描述： 患者:男，19岁。
你好，医生，我是一名高三的学生，最近看过几个有关白血病的报告，心里总是害怕，总是怀疑自己是不是也.......我也不知道是不是心理因素，还是别的原因，身体感觉比较疲劳，没精神，饭后总要大便。还有前两个星期，自己的声带部位感觉不适，不能大声说话，但是声带不疼，曾经发烧，但是打了两天针有些好转，但是现在还有微弱的不适。请问这是怎么回事？？？谢谢
想得到怎样的帮助：是心理因素还是季节的缘故？
```

## doc_id 2996442 — narrative_article

Navigation/attribution/footer sau body được exclude theo layout.

[Nguồn dòng 17326](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:17326) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000017.jsonl:326) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000017.jsonl:326)

Chunks 3 → 1; sizes mới: [279]

Languages: ['zh']; exclusions: ['wiki_navigation_footer']

Child đầu tiên mới:
```text
中毒性神经病
跳转到： 导航, 搜索
A+医学百科 >> 中毒性神经病

中毒性神经病 是毒物引起周围神经损害的疾病，早年常称中毒性神经炎（toxic neurotis）。表现为单神经病和多发性神经病。单神经病如铅中毒的桡神经麻痹，三氯乙烯中毒的三叉神经麻痹。多发性神经病较多见，可在急、慢性中毒时发病，如铊中毒、丙硒酰胺、氯丙烯、砷及二硫化碳中毒等；但在磷酸邻甲苯酯、某些有机磷农药等中毒，多在中毒后2-3周发病，称为迟发性神经病。受累肢体体远端感觉异常，有针刺、蚁走、电灼、麻木等感觉，呈手套、袜套样分布。运动障碍也以远端为重，肌张力降低，腱反射减弱，肌肉萎缩；可伴有植物神经功能障碍。肌电图出现失神经电位及神经传导速度减慢。治疗除脱离接触、特效解药毒外，与一般神经炎治疗相似。
```

## doc_id 2531165 — disease_drug_catalogue

Hàng bảng bệnh–triệu chứng–khoa giữ cùng atom, không tự sinh cột.

[Nguồn dòng 17345](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:17345) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000017.jsonl:345) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000017.jsonl:345)

Chunks 4 → 3; sizes mới: [277, 227, 79]

Languages: ['zh']; exclusions: ['duplicate_rendered_paragraph']

Child đầu tiên mới:
```text
进食过硬的食物口腔损伤

什么是 进食过硬的食物口腔损伤

临床上常见因进食过热或过硬的食物，在咀嚼或吞咽时摩擦损伤软腭、颊粘膜、或咽旁粘膜，可立即形成血疱，因此造成口腔损伤。患者此时感局部异样感或刺痛，张口即可见到此处粘膜血疱，为紫红色，疱壁薄，大小不拘，形态各异。破后疱膜覆盖其上，以后疱膜坏死、脱落而呈一边缘清楚的鲜红色溃疡面，其上有少许分泌物，周围粘膜充血，患者感烧灼样疼痛，说话、进食时疼痛加重。若损伤范围过大，则愈合慢，逐渐溃疡面上有肉芽组织生长，新鲜上皮覆盖后痊愈。 创伤性溃疡是指口腔内残根残冠、牙齿的锐利边缘、错位牙、不良修复体等长期慢性机械损伤形成的溃疡;或由长期咬腮、咬颊、咬唇等自伤性不良习惯造成的溃疡。
```

## doc_id 3078554 — narrative_article

Menu ICD dày và các render copy được exclude bằng marker+shape.

[Nguồn dòng 17393](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:17393) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000017.jsonl:393) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000017.jsonl:393)

Chunks 45 → 17; sizes mới: [268, 258, 252, 253, 244, 252, 236, 155, 49, 27, 135, 170, 245, 293, 285, 258, 163]

Languages: ['und', 'zh']; exclusions: ['icd_navigation', 'duplicate_rendered_paragraph', 'duplicate_rendered_paragraph', 'duplicate_rendered_paragraph', 'duplicate_rendered_paragraph', 'duplicate_rendered_paragraph', 'icd_navigation']

Child đầu tiên mới:
```text
盘尾丝虫病

盘尾丝虫病（重定向自河盲症）跳转到：导航,搜索A+医学百科>> 盘尾丝虫病盘尾丝虫病(河盲症)在非洲某些高发地区使20%以上的成年人失明；而在发达国家，这些疾病则已是不足挂齿的区区小事。盘尾丝虫病是致盲的重要原因，也是世界卫生组织列为重点防治的热带病之一。该病广泛流行于非洲和热带美洲。流行区居民在河边被蚋叮咬而感染。往往引起视力障碍以致失明，因此该病又称为“河盲症”。本病传播广泛，在流行区可造成5%—20％的成人失明，有人描述为“一串盲人扶肩走”的悲惨景象。盘尾丝虫微丝蚴可侵犯角膜。活的微丝蚴一般不致病，但是死亡后其周围形成小的浸润，浸润常从角膜下方开始，初起为点状角膜炎／此后逐渐呈绒毛状混浊。
```

## doc_id 4050109 — disease_drug_catalogue

Drug page sang catalogue; manufacturer/approval/package giữ record riêng.

[Nguồn dòng 17505](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:17505) · [Baseline](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000017.jsonl:505) · [Output mới](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-implementation-20261013/chunks-verified/part-000017.jsonl:505)

Chunks 150 → 116; sizes mới: [223, 282, 271, 234, 168, 157, 222, 234, 259, 223, 211, 248, 261, 246, 257, 209, 221, 270, 258, 257, 298, 261, 263, 262, 284, 255, 250, 263, 297, 293, 247, 220, 263, 293, 278, 257, 253, 289, 259, 266, 263, 251, 255, 293, 286, 250, 221, 284, 256, 289, 261, 249, 256, 293, 283, 254, 224, 292, 287, 259, 15, 157, 237, 168, 253, 266, 255, 286, 253, 225, 257, 252, 290, 277, 256, 261, 258, 263, 262, 254, 284, 290, 287, 228, 250, 257, 285, 288, 227, 249, 285, 263, 290, 243, 231, 259, 257, 288, 290, 249, 283, 256, 289, 254, 224, 288, 289, 256, 257, 250, 287, 292, 260, 248, 218, 183]

Languages: ['zh']; exclusions: ['drug_taxonomy_navigation', 'duplicate_rendered_paragraph', 'duplicate_rendered_paragraph', 'duplicate_rendered_paragraph', 'duplicate_rendered_paragraph', 'drug_taxonomy_navigation']

Child đầu tiên mới:
```text
阿司匹林肠溶片
阿司匹林肠溶片
中医宝典 > 药品百科 > 阿司匹林肠溶片
阿司匹林肠溶片 （AspirinEnteric-coated Tablets），商品名拜阿司匹灵 、拜阿司匹灵(阿司匹林) 。本品为非甾体抗炎药。临床可用于下列情况。 1、 镇痛、解热：可缓解轻度或中度的疼痛，如头痛、牙痛、神经痛、肌肉痛及月经痛，也用于感冒和流感等退热。本品仅能缓解症状，不能治疗引起疼痛和发热的病因，故需同时应用其他药物对病因进行治疗。 2、 抗炎、抗风湿：为治疗风湿热的常用药物，用药后可解热、使关节症状好转并使血沉下降，但不能去除风湿热的基本病理改变，也不能治疗和预防心脏损害及其他合并症。
```
