# Ví dụ thật được đọc và đối chiếu

Mỗi ví dụ lấy từ `data_final/test_20k.jsonl` hiện tại và baseline hybrid mới. `⟦CUT⟧` là ký hiệu minh họa trong báo cáo; không có trong source hoặc output. Các nhận xét đánh giá cấu trúc văn bản, không đánh giá tính đúng của lời khuyên y khoa.

## doc_id 7156587, chunk_order 1

Chunk trộn phần kết quả tiếng Anh với abstract tiếng Trung của cùng tài liệu; cần language_spans và profile nghiên cứu.

- Input: [dòng 101](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:101)
- URL: [https://pubmed.ncbi.nlm.nih.gov/36544416/](https://pubmed.ncbi.nlm.nih.gov/36544416/)
- Output: [shard dòng 101](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:101)
- Units: chunk 264, toàn document 772; offset [1047, 2293).

Đầu chunk:

```text
22 (35%) had chronic superficial gastritis or chronic non-atrophic gastritis alone, and 38 (60%) had other abnormal changes aside from chronic gastritis (16 children with reflux esophagitis, 12 with b
```

Cuối chunk và vị trí cắt:

```text
分析2019年8月—2022年3月在清华大学附属北京清华长庚医院住院及门诊随访的63例周期性呕吐综合征患儿的病例资料。结果: 63例患儿中，男30例，女33例；平均年龄6.11岁； ⟦CUT⟧ 平均病程2.57年；呕吐期平均4.04 d。伴随症状最常见的是精神萎靡或嗜睡（55/63，87%），其次是厌食（45/63，71%）、腹痛或腹部不适（40/63，63%）、便秘（19/63，30%）、流涎（12/63，19%）、恶心（11/63，17%）、头痛
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
结果: 63例患儿中，男30例，女33例；平均年龄6.11岁；平均病程2.57年；呕吐期平均4.04 d。伴随症状最常见的是精神萎靡或嗜睡（55/63，87%），其次是厌食（45/63，71%）、腹痛或腹部不适（40/63，63%）、便秘（19/63，30%）、流涎（12/63，19%）、恶心（11/63，17%）、头
```

## doc_id 6954391, chunk_order 0

Điểm tốt: toàn abstract ngắn 228 units nằm trong một chunk dù có nhiều nhãn mục. Không nên tách cứng từng nhãn thành chunk ngắn.

- Input: [dòng 102](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:102)
- URL: [https://pubmed.ncbi.nlm.nih.gov/34722488/](https://pubmed.ncbi.nlm.nih.gov/34722488/)
- Output: [shard dòng 102](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:102)
- Units: chunk 228, toàn document 228; offset [0, 1538).

Đầu chunk:

```text
Novel Guarded Needle Trans-Scleral Biopsy for Uveal Melanoma: A Pilot Study.

INTRODUCTION: Trans-scleral biopsy of uveal melanoma (UM) poses an inherent risk of tumor and possibly retinal perforation
```

Cuối chunk và vị trí cắt:

```text
 perforation and its associated complications while still obtaining adequate biopsy yield. ⟦CUT⟧ 
```

## doc_id 7147848, chunk_order 0

Sai biên trong nhóm thống kê: kết thúc ngay tại (ES:, tách tên thống kê khỏi giá trị.

- Input: [dòng 243](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:243)
- URL: [https://pubmed.ncbi.nlm.nih.gov/36454790/](https://pubmed.ncbi.nlm.nih.gov/36454790/)
- Output: [shard dòng 243](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:243)
- Units: chunk 219, toàn document 319; offset [0, 1410).

Đầu chunk:

```text
Effect of physical activity on the risk of frailty: A systematic review and meta-analysis.

OBJECTIVE: The relationship between physical activity (PA) and the risk of frailty has not reached a conclus
```

Cuối chunk và vị trí cắt:

```text
st level of PA was significantly associated with 37% (ES 0.63, 95% CI: 0.52-0.77, 49% (ES: ⟦CUT⟧  0.51, 95% CI: 0.41-0.63), and 30% (ES: 0.70, 95% CI: 0.65-0.75) reduced odds of frailty when pooling studies using criteria of ph
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
I2 = 70.0%, P-heterogeneity < 0.001) after pooling results from included studies. In stratified analysis by frailty assessment approach, the highest level of PA
```

## doc_id 6333519, chunk_order 0

Sai biên trong tỷ lệ 1:1: đoạn kết thúc ngay sau 1:, dù toàn biểu thức cần đi cùng nhau.

- Input: [dòng 481](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:481)
- URL: [https://pubmed.ncbi.nlm.nih.gov/28404133/](https://pubmed.ncbi.nlm.nih.gov/28404133/)
- Output: [shard dòng 481](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:481)
- Units: chunk 216, toàn document 542; offset [0, 1476).

Đầu chunk:

```text
Effect on HBs antigen clearance of addition of pegylated interferon alfa-2a to nucleos(t)ide analogue therapy versus nucleos(t)ide analogue therapy alone in patients with HBe antigen-negative chronic 
```

Cuối chunk và vị trí cắt:

```text
four with stratification by HBsAg titres (< or ≥2·25 log10 IU/mL) to allocate patients (1: ⟦CUT⟧ 1) to receive a 48 week course of subcutaneous injections of 180 μg per week of pegylated interferon alfa-2a in addition to the nu
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
Patients with contraindications to pegylated interferon were not eligible. A centralised randomisation used computer-generated lists of random permuted blocks o
```

## doc_id 5714388, chunk_order 0

Sai biên trong số tiền $10,100: dấu phẩy phân tách hàng nghìn bị coi là điểm cắt mệnh đề.

- Input: [dòng 676](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:676)
- URL: [https://pubmed.ncbi.nlm.nih.gov/21211599/](https://pubmed.ncbi.nlm.nih.gov/21211599/)
- Output: [shard dòng 676](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000000.jsonl:676)
- Units: chunk 210, toàn document 315; offset [0, 1395).

Đầu chunk:

```text
Patient characteristics and medical care costs associated with hypertriglyceridemia.

Hypertriglyceridemia is a lipid abnormality prevalent in 1/3 of the United States adult population. Our objective 
```

Cuối chunk và vị trí cắt:

```text
had significantly greater mean total costs ($8,567, 99% confidence interval $7,034 to $10, ⟦CUT⟧ 100) than those with levels <150 mg/dl ($6,186, 99% confidence interval $6,058 to $6,314), 150 to 199 mg/dl ($6,449, 99% confidenc
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
After adjustment, the patients with TG levels ≥500 mg/dl (severe hypertriglyceridemia) had significantly greater mean total costs ($8,567, 99% confidence interv
```

## doc_id 5846763, chunk_order 0

Tiêu đề PubMed 122 ký tự vượt ngưỡng 120, thành parent/chunk riêng 15 units dù toàn tài liệu 1.514 units.

- Input: [dòng 3754](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:3754)
- URL: [https://pubmed.ncbi.nlm.nih.gov/22837102/](https://pubmed.ncbi.nlm.nih.gov/22837102/)
- Output: [shard dòng 754](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000003.jsonl:754)
- Units: chunk 15, toàn document 1514; offset [0, 122).

Đầu chunk:

```text
Toxicology and carcinogenesis study of styrene-acrylonitrile trimer in F344/N rats (perinatal and postnatal feed studies).
```

Cuối chunk và vị trí cắt:

```text
udy of styrene-acrylonitrile trimer in F344/N rats (perinatal and postnatal feed studies). ⟦CUT⟧ 

UNLABELLED: Styrene-acrylonitrile trimer (SAN Trimer) is a mixture of isomers formed by the condensation of two moles of acrylon
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
UNLABELLED: Styrene-acrylonitrile trimer (SAN Trimer) is a mixture of isomers formed by the condensation of two moles of acrylonitrile and one mole of styrene a
```

## doc_id 6248072, chunk_order 1

PubMed dạng chương trình hội nghị O1/O2/P1...; cần profile danh mục bài, URL PubMed không đủ để quyết định format.

- Input: [dòng 4304](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4304)
- URL: [https://pubmed.ncbi.nlm.nih.gov/27356504/](https://pubmed.ncbi.nlm.nih.gov/27356504/)
- Output: [shard dòng 304](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:304)
- Units: chunk 211, toàn document 1949; offset [131, 1781).

Đầu chunk:

```text
O1 HIV-1 diversity in Bulgaria (current molecular epidemiological picture) Ivailo Alexiev, Reneta Dimitrova, Anna Gancheva, Asya Kostadinova, Mariyana Stoycheva, Daniela Nikolova, Ivaylo Elenkov O2 Kn
```

Cuối chunk và vị trí cắt:

```text
gović, Danica Srdić, Al Musalhi Khawla, Ivan Soldatović, Jelena Nikolić, Djordje Jevtović, ⟦CUT⟧  Devaki Nair O7 IP10 – a possible biomarker for the progression of HIV infection Aura Temereanca, Adelina Rosca, Luminita Ene, Ben
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
John Schneider, Vana Sypsa, Dimitrios Paraskevis, Angelos Hatzakis, Samuel R. Friedman, Georgios K. Nikolopoulos O6 Correlation of adipocytokine levels in diffe
```

## doc_id 269380, chunk_order 5

Câu dẫn Cảm giác tội lỗi: ở cuối parent, nội dung giải thích thuộc chunk kế tiếp; cần liên kết label với body.

- Input: [dòng 4580](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4580)
- URL: [https://nhathuoclongchau.com.vn/bai-viet/tich-cuc-doc-hai-toxic-positivity-la-gi-cach-nhan-dien-va-phong-tranh.html](https://nhathuoclongchau.com.vn/bai-viet/tich-cuc-doc-hai-toxic-positivity-la-gi-cach-nhan-dien-va-phong-tranh.html)
- Output: [shard dòng 580](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:580)
- Units: chunk 165, toàn document 1689; offset [4498, 5239).

Đầu chunk:

```text
Khi không được sống với cảm xúc thật của mình, cảm xúc dồn nén bên trong sẽ gây ra u uất và có thể dẫn đến những hậu quả khôn lường:

Gia tăng mức độ của cảm xúc tiêu cực:

Chúng ta thường được khuyến
```

Cuối chunk và vị trí cắt:

```text
cấp kéo theo này có thể khiến cho tinh thần của bạn ngày càng suy kiệt.

Cảm giác tội lỗi: ⟦CUT⟧ 

Tích cực độc hại sẽ khiến người ta cảm thấy tội lỗi vì chính cảm xúc của mình, đánh giá những cảm xúc “không tích cực” một cách 
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
Tích cực độc hại sẽ khiến người ta cảm thấy tội lỗi vì chính cảm xúc của mình, đánh giá những cảm xúc “không tích cực” một cách cực đoan trong khi nó cũng chỉ l
```

## doc_id 218831, chunk_order 0

Điểm tốt: bài Long Châu tạo 5 chunk từ 220–278 units, tất cả kết thúc bằng dấu hết câu, giữ nguyên source slice.

- Input: [dòng 4583](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4583)
- URL: [https://nhathuoclongchau.com.vn/bai-viet/cach-diet-chay-bang-may-say-toc-co-thuc-su-hieu-qua-66733.html](https://nhathuoclongchau.com.vn/bai-viet/cach-diet-chay-bang-may-say-toc-co-thuc-su-hieu-qua-66733.html)
- Output: [shard dòng 583](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:583)
- Units: chunk 220, toàn document 1105; offset [0, 968).

Đầu chunk:

```text
Cách diệt chấy bằng máy sấy tóc có thực sự hiệu quả?

Trẻ em trong độ tuổi từ mầm non đến tiểu học dễ bị lây chấy từ bạn bè. Khi phát hiện bé có chấy, mẹ có thể áp dụng một số cách diệt chấy tại nhà. 
```

Cuối chunk và vị trí cắt:

```text
ại cho những người khác trong gia đình. Chấy cắn hút máu gây cảm giác ngứa ngáy, khó chịu. ⟦CUT⟧  Khi trẻ gãi sẽ dẫn đến xước da đầu, nếu nặng có thể gây viêm nhiễm.

Có nên diệt chấy bằng máy sấy tóc không?

Diệt chấy bằng máy
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
Các bé mầm non đến tiểu học là đối tượng dễ có chấy nhất. Sau đó các bé có thể lây lại cho những người khác trong gia đình. Chấy cắn hút máu gây cảm giác ngứa n
```

## doc_id 264212, chunk_order 1

24.7mg bị nhận là heading theo regex số+dấu chấm. Chunk chưa cắt rời liều với vitamin C, nhưng parent boundary không đúng cấu trúc.

- Input: [dòng 4605](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4605)
- URL: [https://nhathuoclongchau.com.vn/bai-viet/tac-dung-cua-ca-chua-doi-voi-nam-gioi-va-nhung-luu-y-khi-su-dung.html](https://nhathuoclongchau.com.vn/bai-viet/tac-dung-cua-ca-chua-doi-voi-nam-gioi-va-nhung-luu-y-khi-su-dung.html)
- Output: [shard dòng 605](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:605)
- Units: chunk 182, toàn document 1442; offset [1123, 2015).

Đầu chunk:

```text
24.7mg

vitamin C

;

1499 IU

vitamin A

.

Tác dụng của cà chua đối với nam giới gồm tăng khả năng sinh sản, giảm nguy cơ ung thư tuyến tiền liệt,...

Ngoài những dưỡng chất nêu trên, cà chua còn cu
```

Cuối chunk và vị trí cắt:

```text
ăng sinh sản, đặc biệt là ở nam giới.

Tác dụng của cà chua đối với nam giới cụ thể là gì? ⟦CUT⟧  Ăn cà chua đều đặn với lượng thích hợp, nam giới có thể tăng đến hơn 70% khả năng sinh sản nhờ chất chống oxy hóa hỗ trợ phòng ng
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
Hoạt chất này khi được cung cấp đầy đủ và thường xuyên có thể phát huy công dụng tăng cường khả năng sinh sản, đặc biệt là ở nam giới.

Tác dụng của cà chua đối
```

## doc_id 279805, chunk_order 2

Chunk chỉ có Triệu chứng (2 units) trong tài liệu 2.034 units. Có bốn chunk như vậy.

- Input: [dòng 4881](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:4881)
- URL: [https://nhathuoclongchau.com.vn/bai-viet/viem-la-gi-nguyen-nhan-gay-viem-va-tac-dong-cua-viem-doi-voi-co-the.html](https://nhathuoclongchau.com.vn/bai-viet/viem-la-gi-nguyen-nhan-gay-viem-va-tac-dong-cua-viem-doi-voi-co-the.html)
- Output: [shard dòng 881](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000004.jsonl:881)
- Units: chunk 2, toàn document 2034; offset [1590, 1601).

Đầu chunk:

```text
Triệu chứng
```

Cuối chunk và vị trí cắt:

```text
iêm là gì? Nguyên nhân và cách điều trị bệnh viêm

12/08/2025

Tìm hiểu chung

Triệu chứng ⟦CUT⟧ 

Nguyên nhân

Nguy cơ

Phương pháp chẩn đoán & điều trị

Chế độ sinh hoạt & phòng ngừa

Tìm hiểu chung

Triệu chứng

Nguyên nhân

```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
Nguyên nhân

Nguy cơ

Phương pháp chẩn đoán & điều trị

Chế độ sinh hoạt & phòng ngừa

Tìm hiểu chung
```

## doc_id 211401, chunk_order 0

Sai biên trong số thập phân tiếng Việt 37,5: phần 5 độ C rơi sang vùng nguồn sau điểm cắt.

- Input: [dòng 5277](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:5277)
- URL: [https://nhathuoclongchau.com.vn/bai-viet/be-ham-hap-nong-khoang-37-do-co-tiem-chung-duoc-khong.html](https://nhathuoclongchau.com.vn/bai-viet/be-ham-hap-nong-khoang-37-do-co-tiem-chung-duoc-khong.html)
- Output: [shard dòng 277](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000005.jsonl:277)
- Units: chunk 206, toàn document 749; offset [0, 930).

Đầu chunk:

```text
Bé hâm hấp nóng khoảng 37 độ có tiêm chủng được không?

Rất nhiều cha mẹ thắc mắc liệu có nên tiêm vắc xin khi trẻ bị sốt hay không và việc tiêm này có ảnh hưởng gì đến tình trạng bệnh của trẻ hay khô
```

Cuối chunk và vị trí cắt:

```text
trước tiêm chủng, trẻ em từ 1 tháng tuổi trở lên có thể được tiêm vắc xin nếu sốt dưới 37, ⟦CUT⟧ 5 độ C. Điều này có nghĩa là nếu bé chỉ có nhiệt độ hâm hấp khoảng 37 độ C, vẫn có thể tiêm chủng được, nhưng cần có sự đánh giá t
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
Theo hướng dẫn tại Quyết định 2470/QĐ-BYT ngày 14/6/2019 về khám sàng lọc trước tiêm chủng, trẻ em từ 1 tháng tuổi trở lên có thể được tiêm vắc xin nếu sốt dưới
```

## doc_id 4265827, chunk_order 1

Phần mô tả sách ngắn vẫn bị nối với mũi tên lật trang và tên chương lân cận.

- Input: [dòng 13393](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:13393)
- URL: [https://zysjonline.com/books/jiatingyixuebaike_yiliaokangfu/191428/](https://zysjonline.com/books/jiatingyixuebaike_yiliaokangfu/191428/)
- Output: [shard dòng 393](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000013.jsonl:393)
- Units: chunk 197, toàn document 364; offset [196, 437).

Đầu chunk:

```text
国外现在有不少只吃素食的人，他们不发生维生素B12缺乏，因为他们平时吃大量的奶酪，奶酪中含有丰富的维生素B12。在国外，任何超级市场都有各种各样的奶酪供应，消费量很大，国内大多数人还不习惯吃奶酪，看来有加以宣传的必要。

有些老年人，既不是素食者，也没有接受过胃切除手术，但仍有可能发生维生素B12缺乏，主要是胃肠道吸收功能减退所致。如果出现神经精神症状，经血清维生素B12检测证实水平偏低，则应补充
```

Cuối chunk và vị trí cắt:

```text
，主要是胃肠道吸收功能减退所致。如果出现神经精神症状，经血清维生素B12检测证实水平偏低，则应补充维生素B12

←

遗传性共济失调

← → 方向键翻页

运动神经元疾病

→ ⟦CUT⟧ 
```

## doc_id 1067218, chunk_order 0

Q&A dài: marker 病情分析 nằm cuối chunk; marker/body câu trả lời cần nối với nhau, giữ câu hỏi qua metadata.

- Input: [dòng 15526](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:15526)
- URL: [http://www.120ask.com/question/14391538.htm](http://www.120ask.com/question/14391538.htm)
- Output: [shard dòng 526](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000015.jsonl:526)
- Units: chunk 246, toàn document 366; offset [0, 301).

Đầu chunk:

```text
糖尿病患者能怀孩子么？
健康咨询描述： 空腹血糖一直在十以上
曾经的治疗情况和效果： 用过胰岛素,现在用比格列酮和格列奇特缓释片
想得到怎样的帮助：想要孩子,可以么?今年38岁,了
您好：在血糖控制正常情况下,可以要孩子.正常的空腹血糖3.89-6.1 mmol/L,正常的餐后2小时血糖小于7.8mmol/L,目前您的血糖控制不佳,建议到专科医院调整治疗,并且在怀孕前3个月和怀孕期间必须要用胰岛素
```

Cuối chunk và vị trí cắt:

```text
药物和高糖毒性容易导致胎儿畸形或流产.另外,您38岁属于高龄产妇,注意事项较多,一定前往医院进行咨询,定期到有条件的妇产科进行母胎监护和必要的防治措施.祝您心想事成!

病情分析： ⟦CUT⟧ 
空腹血糖在十以上已经确诊糖尿病了.
指导意见：
你好,糖尿病人可以怀孕,就是必须把血糖控制在正常范围内.

可以生孩子的,建议停口服的降糖药,用胰岛素控制血糖,只要血糖基本控制在正常范围内,孩子是安全的

以上是对“糖尿病患者能怀孩子么？”这个问题的建议，希
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
一定前往医院进行咨询,定期到有条件的妇产科进行母胎监护和必要的防治措施.祝您心想事成!

病情分析：
空腹血糖在十以上已经确诊糖尿病了.
指导意见：
你好,糖尿病人可以怀孕,就是必须把血糖控制在正常范围内.

可以生孩子的,建议停口服的降糖药,用胰岛素控制血糖,只要血糖基本控制在正常范围内,孩子是安全的

以上是对“糖
```

## doc_id 1128713, chunk_order 0

Điểm tốt: Q&A ngắn 159 units giữ đủ mô tả vấn đề, bối cảnh và câu trả lời trong một chunk.

- Input: [dòng 15530](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:15530)
- URL: [http://www.120ask.com/question/2005063.htm](http://www.120ask.com/question/2005063.htm)
- Output: [shard dòng 530](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000015.jsonl:530)
- Units: chunk 159, toàn document 159; offset [0, 189).

Đầu chunk:

```text
我现在满身上长满了小红点,非常痒洗热水澡时
健康咨询描述： 我现在满身上长满了小红点,非常痒洗热水澡时,更痒爱抓,越抓越大.跟大豆一样.非常痒还抓破皮了,怎么办,求教您医师.
上班时候都没心事了.快速治疗.好让我好好上班
本次发病及持续时间:一星期多了非常困人.
以往诊断治疗经过及效果:有治疗过说什么.(麻疹)
建议口服赛庚啶、甲氰咪胍、维生素C、维生素B6，外用尤卓尔治疗。
```

Cuối chunk và vị trí cắt:

```text
速治疗.好让我好好上班
本次发病及持续时间:一星期多了非常困人.
以往诊断治疗经过及效果:有治疗过说什么.(麻疹)
建议口服赛庚啶、甲氰咪胍、维生素C、维生素B6，外用尤卓尔治疗。 ⟦CUT⟧ 
```

## doc_id 2335124, chunk_order 0

Bio bác sĩ chứa nhiều bệnh không phải nội dung của câu trả lời, hiện vẫn vào chunk đầu.

- Input: [dòng 15533](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:15533)
- URL: [https://ask.39.net/question/86124852.html](https://ask.39.net/question/86124852.html)
- Output: [shard dòng 533](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000015.jsonl:533)
- Units: chunk 225, toàn document 655; offset [0, 270).

Đầu chunk:

```text
肠系膜脂肪炎的症状

【医生信息】
赵英帅 主治医师 河南省人民医院 三甲 擅长： 擅长报告解读、幽门螺旋杆菌感染、高血压、高血脂、高尿酸、冠心病、糖尿病、胃肠炎、便秘、感冒、肺结节、甲状腺结节等疾病的综合诊疗 找医生

【医生回复】
肠系膜脂肪炎的症状包括腹痛、腹部压痛、发热、恶心呕吐以及腹泻。由于肠系膜脂肪炎可能引起严重并发症，建议及时就医以获得专业评估和治疗。

1.腹痛

腹痛是由于炎症刺
```

Cuối chunk và vị trí cắt:

```text
和治疗。

1.腹痛

腹痛是由于炎症刺激肠道壁和周围组织，导致平滑肌痉挛和神经反射性疼痛。此时局部血液循环受阻，缺血缺氧会加剧疼痛。腹痛通常位于上腹部或脐周，可能伴有阵发性加重。 ⟦CUT⟧ 

2.腹部压痛

腹部压痛是因为炎症引起的局部组织水肿和敏感度增加，在按压时会导致疼痛反应。压痛点一般集中在右下腹麦氏点处，但也可能是弥漫性的。

3.发热

发热主要是由感染引起的免疫系统反应，机体释放内源性致热原如白介素-1β等，这些物质作用于体温调节中
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
此时局部血液循环受阻，缺血缺氧会加剧疼痛。腹痛通常位于上腹部或脐周，可能伴有阵发性加重。

2.腹部压痛

腹部压痛是因为炎症引起的局部组织水肿和敏感度增加，在按压时会导致疼痛反应。压痛点一般集中在右下腹麦氏点处，但也可能是弥漫性的。

3.发热

发热主要是由感染引起的免疫系统反应，机体释放内源性致热原如白介素-1β
```

## doc_id 2996442, chunk_order 2

Chunk danh sách điều hướng, link liên quan và footer của wiki vẫn retrieval_eligible.

- Input: [dòng 17326](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:17326)
- URL: [https://www.a-hospital.com/w/%E4%B8%AD%E6%AF%92%E6%80%A7%E7%A5%9E%E7%BB%8F%E7%97%85](https://www.a-hospital.com/w/%E4%B8%AD%E6%AF%92%E6%80%A7%E7%A5%9E%E7%BB%8F%E7%97%85)
- Output: [shard dòng 326](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000017.jsonl:326)
- Units: chunk 216, toàn document 589; offset [459, 741).

Đầu chunk:

```text
瘦肉精中毒
强酸、强碱中毒
甲醇中毒
汽油中毒
汞中毒
铅中毒
铊中毒
镉中毒
氯气中毒
氰化物中毒
窒息性气体中毒
更多中毒急救知识

解毒
解毒药
导泻
洗胃
灌肠
血液透析
血液灌流

相关条目
毒理学
急救常识
有毒中药列表
毒素
毒性
致死量
半数致死量（LD50)
食品卫生
药物过量
水俣病

书摘
急性中毒的诊疗原则
食物中毒防制
中药毒性
中毒诊疗
常见毒物
具有肾毒性的中药
药物
```

Cuối chunk và vị trí cắt:

```text
毒性的中药
药物中毒与解救

出自A+医学百科 “中毒性神经病”条目 转载请保留此链接

关于“中毒性神经病 ”的留言： 订阅讨论RSS

目前暂无留言
添加留言
更多医学百科条目 ⟦CUT⟧ 
```

## doc_id 2531165, chunk_order 0

Trang bệnh/triệu chứng có nguyên đoạn mô tả lặp hai lần và link Markdown lỗi. Ghi duplicate spans, không gọi là lỗi packing thuần túy.

- Input: [dòng 17345](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:17345)
- URL: [https://jbk.39.net/zhengzhuang/jsgydswkqss/](https://jbk.39.net/zhengzhuang/jsgydswkqss/)
- Output: [shard dòng 345](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000017.jsonl:345)
- Units: chunk 211, toàn document 783; offset [0, 240).

Đầu chunk:

```text
进食过硬的食物口腔损伤

什么是 进食过硬的食物口腔损伤

临床上常见因进食过热或过硬的食物，在咀嚼或吞咽时摩擦损伤软腭、颊粘膜、或咽旁粘膜，可立即形成血疱，因此造成口腔损伤。患者此时感局部异样感或刺痛，张口即可见到此处粘膜血疱，为紫红色，疱壁薄，大小不拘，形态各异。破后疱膜覆盖其上，以后疱膜坏死、脱落而呈一边缘清楚的鲜红色溃疡面，其上有少许分泌物，周围粘膜充血，患者感烧灼样疼痛，说话、进食时疼痛
```

Cuối chunk và vị trí cắt:

```text
脱落而呈一边缘清楚的鲜红色溃疡面，其上有少许分泌物，周围粘膜充血，患者感烧灼样疼痛，说话、进食时疼痛加重。若损伤范围过大，则愈合慢，逐渐溃疡面上有肉芽组织生长，新鲜上皮覆盖后痊愈。 ⟦CUT⟧  创伤性溃疡是指口腔内残根残冠、牙齿的锐利边缘、错位牙、不良修复体等长期慢性机械损伤形成的溃疡;或由长期咬腮、咬颊、咬唇等自伤性不良习惯造成的溃疡。溃疡的形状与刺激因子完全契合。

详细>>[[起因] 进食过硬的食物口腔损伤是怎么引起的？](
详细>>[[详解
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
进食时疼痛加重。若损伤范围过大，则愈合慢，逐渐溃疡面上有肉芽组织生长，新鲜上皮覆盖后痊愈。 创伤性溃疡是指口腔内残根残冠、牙齿的锐利边缘、错位牙、不良修复体等长期慢性机械损伤形成的溃疡;或由长期咬腮、咬颊、咬唇等自伤性不良习惯造成的溃疡。溃疡的形状与刺激因子完全契合。

详细>>[[起因] 进食过硬的食物口腔损伤是怎么
```

## doc_id 3078554, chunk_order 12

Atom menu wiki 425 units; cùng nội dung lặp lại ở order 26. Cần định vai trò nav trước khi packing.

- Input: [dòng 17393](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/data_final/test_20k.jsonl:17393)
- URL: [https://www.a-hospital.com/w/%E6%B2%B3%E7%9B%B2%E7%97%87](https://www.a-hospital.com/w/%E6%B2%B3%E7%9B%B2%E7%97%87)
- Output: [shard dòng 393](/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Preprocess/research/format-audit-20261013/baseline_chunks/part-000017.jsonl:393)
- Units: chunk 425, toàn document 9140; offset [2902, 3361).

Đầu chunk:

```text
全色盲)·夜盲(先天性夜盲症)·失明/视力低下瞳孔瞳孔不均·强直性瞳孔·相对传入瞳孔缺陷·艾迪综合征·瞳孔缩小·散瞳症·睫状肌麻痹其他眼震眼部感染沙眼·盘尾丝虫病人体百科-眼和眼科疾病眼视觉眼球纤维膜葡萄膜视网膜房水晶状体玻璃体视神经眼睑结膜泪器眼眶眼镜眼睛症状流泪复视视力障碍畏光夜盲眼痛偏盲眼干眼睑下垂盲点红眼眼睑痉挛眼胀眼球突出视物变形虹视眼前发黑眼睑外翻眼充血眼屎多睁眼困难眼睛痒眼科疾病视力
```

Cuối chunk và vị trí cắt:

```text
显微镜检查检眼镜检查法眼压检查眼底荧光血管造影法眼电图视网膜电流图视诱发电位其它眼科医院列表眼科治疗眼科疾病的药品列表视目诊病《眼科学》《中医眼科学》ICD-10/H00-H59： ⟦CUT⟧ 眼及附器疾病出自A+医学百科 “盘尾丝虫病”条目

（重定向自河盲症）跳转到：导航,搜索A+医学百科>> 盘尾丝虫病盘尾丝虫病(河盲症)在非洲某些高发地区使20%以上的成年人失明；而在发达国家，这些疾病则已是不足挂齿的区区小事。盘尾丝虫病是致盲的重要原因，也是
```

Đầu chunk kế tiếp (có thể bắt đầu sớm hơn do overlap):

```text
眼及附器疾病出自A+医学百科 “盘尾丝虫病”条目
```
