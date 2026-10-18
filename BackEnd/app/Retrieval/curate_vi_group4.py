#!/usr/bin/env python3
"""
curate_vi_group4.py - Curated medical entities from Batches 009, 010, 011
Curated by Vietnamese Medical Curator (Biomedical NLP Specialist)
"""

import sys
sys.path.insert(0, ".")
from BackEnd.app.Retrieval.curate_worker import append_curated_terms

items_b9 = [
    # Batch 009
    {"term": "siêu âm túi mật", "class": "[PROC]", "source_id": 259510, "context": "Qua hình ảnh siêu âm, kích thước túi mật bình thường là bao nhiêu?"},
    {"term": "viêm túi mật", "class": "[DIS]", "source_id": 259510, "context": "viêm túi mật cấp tính do sỏi kẹt cổ túi mật gây phù nề thành túi mật"},
    {"term": "đau dây thần kinh sau zona", "class": "[DIS]", "source_id": 228968, "context": "biến chứng đau dây thần kinh sau zona kéo dài dai dẳng"},
    {"term": "zona ở mắt", "class": "[DIS]", "source_id": 228968, "context": "virus tấn công nhánh mắt dây thần kinh số 5 gây zona ở mắt mù lòa"},
    {"term": "biến chứng thần kinh đái tháo đường", "class": "[DIS]", "source_id": 250860, "context": "tê bì kiến bò đầu ngón tay chân do biến chứng thần kinh đái tháo đường"},
    {"term": "dị ứng đạm bò", "class": "[DIS]", "source_id": 261806, "context": "hội chứng dị ứng đạm sữa bò ở trẻ sơ sinh và trẻ nhỏ"},
    {"term": "viêm họng hạt", "class": "[DIS]", "source_id": 233383, "context": "viêm họng hạt là thể viêm họng mạn tính xuất hiện các nang lympho quá phát"},
    {"term": "cắt polyp đại tràng", "class": "[PROC]", "source_id": 244329, "context": "Cắt Polyp đại tràng qua nội soi ống mềm giúp phòng ngừa ung thư"},
    {"term": "polyp đại tràng", "class": "[DIS]", "source_id": 244329, "context": "khối polyp tuyến đại tràng có tiềm năng tiến triển ác tính"},
    {"term": "đại tràng", "class": "[ANA]", "source_id": 244329, "context": "đoạn đại tràng Sigma và trực tràng thường xuyên xuất hiện polyp"},
    {"term": "xét nghiệm máu lắng", "class": "[PROC]", "source_id": 248509, "context": "Xét nghiệm máu lắng (tốc độ máu lắng ESR) đánh giá phản ứng viêm"},
    {"term": "tốc độ máu lắng", "class": "[PROC]", "source_id": 248509, "context": "chỉ số tốc độ máu lắng tăng cao trong các bệnh lý viêm và tự miễn"},
    {"term": "xét nghiệm tinh dịch đồ", "class": "[PROC]", "source_id": 281347, "context": "Xét nghiệm tinh dịch đồ: Đánh giá số lượng và chất lượng tinh trùng"},
    {"term": "tinh dịch đồ", "class": "[PROC]", "source_id": 281347, "context": "tiêu chuẩn phân tích tinh dịch đồ theo hướng dẫn của WHO"},
    {"term": "viêm đường tiết niệu", "class": "[DIS]", "source_id": 252978, "context": "nhiễm khuẩn gây viêm đường tiết niệu, tiểu buốt, tiểu rắt"},
    {"term": "sốc nhiệt", "class": "[DIS]", "source_id": 243019, "context": "say nắng say nóng dẫn đến sốc nhiệt đột ngột tăng thân nhiệt trên 40 độ"},
    {"term": "thoái hóa khớp gối", "class": "[DIS]", "source_id": 267321, "context": "mòn lớp sụn chêm và hẹp khe khớp trong thoái hóa khớp gối"},
    {"term": "dịch khớp gối", "class": "[ANA]", "source_id": 267321, "context": "tràn dịch khớp gối gây sưng phù căng tức khớp"},
    {"term": "mụn rộp sinh dục", "class": "[DIS]", "source_id": 247255, "context": "mụn rộp sinh dục do virus Herpes Simplex HSV type 2 lây qua đường tình dục"},
    {"term": "herpes simplex", "class": "[DIS]", "source_id": 247255, "context": "virus Herpes Simplex gây loét trợt đau rát tại niêm mạc sinh dục"},
]

items_b10 = [
    # Batch 010
    {"term": "nhồi máu cơ tim", "class": "[DIS]", "source_id": 205390, "context": "4 xét nghiệm chẩn đoán nhồi máu cơ tim cơ bản và phổ biến nhất hiện nay"},
    {"term": "troponin t", "class": "[PROC]", "source_id": 205390, "context": "xét nghiệm men tim Troponin T siêu nhạy hs-cTnT chỉ điểm tổn thương cơ tim"},
    {"term": "troponin i", "class": "[PROC]", "source_id": 205390, "context": "định lượng nồng độ Troponin I máu tăng cao sau cơn nhồi máu cấp"},
    {"term": "men tim", "class": "[ANA]", "source_id": 205390, "context": "sự phóng thích các enzym men tim CK-MB và Troponin vào tuần hoàn"},
    {"term": "điện tâm đồ", "class": "[PROC]", "source_id": 205390, "context": "ghi điện tâm đồ ECG 12 chuyển đạo phát hiện sóng ST chênh lên"},
    {"term": "sốt siêu vi", "class": "[DIS]", "source_id": 251004, "context": "Nguyên nhân, dấu hiệu, cách chữa sốt siêu vi phát ban ở người lớn"},
    {"term": "sốt siêu vi phát ban", "class": "[DIS]", "source_id": 251004, "context": "nhiễm virus gây sốt siêu vi phát ban dạng chấm đỏ toàn thân"},
    {"term": "thụ tinh trong ống nghiệm", "class": "[PROC]", "source_id": 266885, "context": "Tiên lượng thai lâm sàng trong thụ tinh ống nghiệm IVF"},
    {"term": "sảy thai", "class": "[DIS]", "source_id": 261950, "context": "Sảy thai và thai lưu có giống nhau không? Phân biệt dọa sảy thai"},
    {"term": "thai lưu", "class": "[DIS]", "source_id": 261950, "context": "thai chết lưu trong buồng tử cung trước khi chuyển dạ"},
    {"term": "otosan", "class": "[DRUG]", "source_id": 266131, "context": "Dung dịch xịt mũi người lớn Otosan Nasal Spray Forte"},
    {"term": "vôi răng", "class": "[DIS]", "source_id": 260120, "context": "Răng bị vôi đóng nhiều có nguy hiểm hay không? Lắng đọng mảng bám vôi răng"},
    {"term": "lấy cao răng", "class": "[PROC]", "source_id": 260120, "context": "phương pháp cạo vôi răng lấy cao răng bằng sóng siêu âm định kỳ"},
    {"term": "hoa đu đủ đực", "class": "[DRUG]", "source_id": 271066, "context": "Tìm hiểu về cách dùng hoa đu đủ đực chữa bướu cổ và ho mạn tính"},
    {"term": "ứ mật thai kỳ", "class": "[DIS]", "source_id": 208817, "context": "ngứa da lòng bàn tay bàn chân do hội chứng ứ mật thai kỳ trong gan"},
    {"term": "đo độ mờ da gáy", "class": "[PROC]", "source_id": 281258, "context": "siêu âm đo độ mờ da gáy thai 12 tuần sàng lọc hội chứng Down"},
    {"term": "tiểu đường tuýp 2", "class": "[DIS]", "source_id": 241655, "context": "Kiểm soát tiểu đường tuýp 2 hiệu quả qua chế độ sinh hoạt và ăn uống"},
    {"term": "đái tháo đường týp 2", "class": "[DIS]", "source_id": 241655, "context": "tình trạng kháng insulin ngoại vi dẫn đến đái tháo đường týp 2"},
    {"term": "ong mặt quỷ đốt", "class": "[DIS]", "source_id": 213752, "context": "Bị ong mặt quỷ đốt phải làm sao? Nguy cơ suy thận cấp và tan máu"},
    {"term": "sốc phản vệ", "class": "[DIS]", "source_id": 213752, "context": "nọc ong gây phản ứng dị ứng nặng sốc phản vệ độ 3 đe dọa tính mạng"},
    {"term": "viêm nang lông", "class": "[DIS]", "source_id": 275247, "context": "Trị viêm nang lông bằng đông y đúng cách, ngăn ngừa mụn mủ chân lông"},
    {"term": "mổ u nang buồng trứng", "class": "[PROC]", "source_id": 223944, "context": "Chi phí mổ u nang buồng trứng khi mổ hở và mổ nội soi"},
    {"term": "u nang buồng trứng", "class": "[DIS]", "source_id": 223944, "context": "khối u nang bì nang hoàng thể phát triển tại buồng trứng"},
    {"term": "tiểu đường thai kỳ", "class": "[DIS]", "source_id": 245836, "context": "Mẹ bầu mắc tiểu đường thai kỳ ăn nho được không?"},
    {"term": "đông trùng hạ thảo", "class": "[DRUG]", "source_id": 268482, "context": "vị thuốc đông trùng hạ thảo Cordyceps sinensis bồi bổ phế thận"},
    {"term": "vẹo ngón chân cái", "class": "[DIS]", "source_id": 278674, "context": "Vẹo ngón chân cái Hallux Valgus gây biến dạng vòm bàn chân"},
    {"term": "ngón chân cái", "class": "[ANA]", "source_id": 278674, "context": "khớp bàn ngón chân cái bị phì đại lệch trục ra ngoài"},
    {"term": "viêm cơ thang", "class": "[DIS]", "source_id": 279428, "context": "Viêm cơ thang là gì? Phương pháp điều trị đau cứng cơ thang vai gáy"},
    {"term": "cơ thang", "class": "[ANA]", "source_id": 279428, "context": "cơ thang lớn vùng lưng trên nối cổ gáy xuống giữa lưng"},
    {"term": "viêm bao quy đầu", "class": "[DIS]", "source_id": 228879, "context": "Dấu hiệu và triệu chứng của viêm bao quy đầu Balanitis"},
    {"term": "rối loạn lo âu lan tỏa", "class": "[DIS]", "source_id": 260963, "context": "Rối loạn lo âu lan tỏa GAD là gì? Nguyên nhân, triệu chứng và điều trị"},
    {"term": "trào ngược dạ dày", "class": "[DIS]", "source_id": 232306, "context": "Bị trào ngược dạ dày có nên ăn gạo lứt không?"},
    {"term": "trào ngược dạ dày thực quản", "class": "[DIS]", "source_id": 232306, "context": "dịch vị axit trào ngược dạ dày thực quản gây ợ chua nóng rát sau xương ức"},
    {"term": "viêm da mụn mủ truyền nhiễm", "class": "[DIS]", "source_id": 283609, "context": "Viêm da mụn mủ truyền nhiễm Ecthyma do liên cầu khuẩn"},
    {"term": "rong kinh", "class": "[DIS]", "source_id": 265144, "context": "Tại sao lại bị rong kinh? Nguyên nhân chu kỳ kinh kéo dài trên 7 ngày"},
    {"term": "rong huyết", "class": "[DIS]", "source_id": 265144, "context": "chảy máu tử cung bất thường không theo chu kỳ thành rong huyết"},
    {"term": "suy gan", "class": "[DIS]", "source_id": 214595, "context": "Biểu hiện, biến chứng và các giai đoạn của suy gan cấp và mạn"},
    {"term": "hôn mê gan", "class": "[DIS]", "source_id": 214595, "context": "bệnh não gan hôn mê gan do độc chất amoniac tích tụ trong máu"},
    {"term": "sâm alipas", "class": "[DRUG]", "source_id": 225541, "context": "Sâm Alipas chứa chiết xuất cây mật nhân Eurycoma longifolia"},
    {"term": "chàm sữa", "class": "[DIS]", "source_id": 244006, "context": "Lưu ý khi chăm sóc trẻ bị chàm sữa lác sữa tại nhà"},
    {"term": "viêm da nhiễm trùng", "class": "[DIS]", "source_id": 254952, "context": "Những loại viêm da nhiễm trùng thường gặp như chốc lở, nhọt"},
]

items_b11 = [
    # Batch 011
    {"term": "thủy đậu sau sinh", "class": "[DIS]", "source_id": 269325, "context": "Thủy đậu sau sinh là gì? Nguyên nhân, triệu chứng, cách chăm sóc"},
    {"term": "bệnh thủy đậu", "class": "[DIS]", "source_id": 269325, "context": "nhiễm virus varicella zoster gây sốt và mụn nước bọng đậu phỏng"},
    {"term": "ung thư máu", "class": "[DIS]", "source_id": 276844, "context": "Ung thư máu leukemia gây tăng sinh ác tính dòng bạch cầu non"},
    {"term": "viêm xoang dị ứng thời tiết", "class": "[DIS]", "source_id": 280271, "context": "Viêm xoang dị ứng thời tiết là gì? Phù nề sung huyết niêm mạc xoang"},
    {"term": "ung thư cổ tử cung", "class": "[DIS]", "source_id": 237241, "context": "Hình ảnh ung thư cổ tử cung qua từng giai đoạn IA đến IVB"},
    {"term": "cổ tử cung", "class": "[ANA]", "source_id": 237241, "context": "tổn thương sùi loét tại biểu mô vảy cổ tử cung"},
    {"term": "nấm lưỡi", "class": "[DIS]", "source_id": 248187, "context": "Nấm lưỡi gây hôi miệng: Triệu chứng mảng trắng bám trên gai lưỡi"},
    {"term": "bệnh loãng xương", "class": "[DIS]", "source_id": 212011, "context": "Bệnh loãng xương có chữa được không? Mất khối lượng và giòn xương"},
    {"term": "viêm niệu đạo", "class": "[DIS]", "source_id": 266741, "context": "Thắc mắc: Viêm niệu đạo có được quan hệ không?"},
    {"term": "niệu đạo", "class": "[ANA]", "source_id": 266741, "context": "niêm mạc niệu đạo bị lậu cầu hoặc Chlamydia tấn công gây tiết dịch mủ"},
    {"term": "xuất huyết não", "class": "[DIS]", "source_id": 216192, "context": "Các biện pháp dự phòng xuất huyết não, ngăn ngừa đột quỵ vỡ mạch máu"},
    {"term": "thuốc glucosamine", "class": "[DRUG]", "source_id": 263314, "context": "Sử dụng thuốc glucosamine loại nào tốt để tái tạo sụn khớp?"},
    {"term": "glucosamine", "class": "[DRUG]", "source_id": 263314, "context": "hợp chất amino monosaccharide cấu thành dịch hoạt dịch và sụn khớp"},
    {"term": "bệnh uốn ván", "class": "[DIS]", "source_id": 212765, "context": "Bệnh uốn ván biểu hiện như thế nào? Co giật và cứng cơ nhai"},
    {"term": "sún răng", "class": "[DIS]", "source_id": 274260, "context": "Trẻ bị sún răng, mòn men răng sữa ba mẹ nên làm gì?"},
    {"term": "đo chức năng hô hấp", "class": "[PROC]", "source_id": 245603, "context": "Máy đo chức năng hô hấp có vai trò đo dung tích sống FVC và FEV1"},
    {"term": "nổi mề đay", "class": "[DIS]", "source_id": 256549, "context": "Nổi mề đay quanh bụng thành từng mảng sẩn phù ngứa ngáy dữ dội"},
    {"term": "suy vỏ thượng thận", "class": "[DIS]", "source_id": 264157, "context": "Suy vỏ thượng thận là gì? Nguyên nhân gây suy vỏ thượng thận cấp"},
    {"term": "vỏ thượng thận", "class": "[ANA]", "source_id": 264157, "context": "vùng cầu, vùng bó, vùng lưới của vỏ thượng thận giảm bài tiết corticosteroid"},
    {"term": "gan nhiễm mỡ", "class": "[DIS]", "source_id": 216946, "context": "Các loại rau củ tốt cho người bệnh gan nhiễm mỡ thoái hóa mỡ gan"},
    {"term": "gãy xương gò má", "class": "[DIS]", "source_id": 278441, "context": "Vài nét về tình trạng gãy xương gò má và cung tiếp gò má"},
    {"term": "xương gò má", "class": "[ANA]", "source_id": 278441, "context": "xương gò má tạo nên cấu trúc nhô cao ở hai bên gò má mặt"},
    {"term": "đau bụng kinh", "class": "[DIS]", "source_id": 227892, "context": "Đau bụng kinh thống kinh do co bóp cơ tử cung khi hành kinh"},
    {"term": "cây thầu dầu tía", "class": "[DRUG]", "source_id": 246446, "context": "Mẹo sử dụng cây thầu dầu tía chữa bệnh trĩ teo búi trĩ"},
    {"term": "bệnh cao huyết áp", "class": "[DIS]", "source_id": 239681, "context": "Huyết áp bao nhiêu là cao? Những lưu ý cần biết về bệnh cao huyết áp"},
    {"term": "chọc hút trứng", "class": "[PROC]", "source_id": 261573, "context": "Sau khi chọc hút trứng bao lâu thì chuyển phôi?"},
    {"term": "chuyển phôi", "class": "[PROC]", "source_id": 261573, "context": "chuyển phôi nang ngày 5 vào buồng tử cung người mẹ"},
    {"term": "bệnh đậu mùa khỉ", "class": "[DIS]", "source_id": 282622, "context": "Bệnh đậu mùa khỉ Mpox là một bệnh lây truyền do virus đậu mùa khỉ"},
    {"term": "virus đậu mùa khỉ", "class": "[DIS]", "source_id": 282622, "context": "virus Orthopoxvirus gây bệnh đậu mùa khỉ sốt và nổi hạch"},
    {"term": "covid-19 kéo dài", "class": "[DIS]", "source_id": 232073, "context": "F0 không có triệu chứng sao bị Covid-19 kéo dài Long Covid?"},
    {"term": "lún dương vật ở trẻ", "class": "[DIS]", "source_id": 243862, "context": "Lún dương vật ở trẻ: Thân dương vật bị vùi lấp dưới lớp mỡ trước mu"},
    {"term": "dương vật", "class": "[ANA]", "source_id": 243862, "context": "thể hang thể xốp cấu tạo nên trục dương vật nam giới"},
    {"term": "chụp x-quang chân", "class": "[PROC]", "source_id": 253965, "context": "Những điều bạn cần biết về chụp X quang chân khảo sát gãy xương"},
    {"term": "chuyển phôi tươi", "class": "[PROC]", "source_id": 225308, "context": "Chuyển phôi tươi là gì? Chuyển phôi tươi hay chuyển phôi trữ tốt hơn"},
    {"term": "chuyển phôi trữ", "class": "[PROC]", "source_id": 225308, "context": "phôi được đông lạnh trữ ni tơ lỏng rã đông chuẩn bị niêm mạc chuyển phôi"},
    {"term": "hạ đường huyết lúc đói", "class": "[DIS]", "source_id": 236254, "context": "Hạ đường huyết lúc đói là gì? Nồng độ glucose máu tụt dưới 3.9 mmol/L"},
    {"term": "hạ đường huyết", "class": "[DIS]", "source_id": 236254, "context": "vã mồ hôi run tay run chân tim đập nhanh do hạ đường huyết"},
]

if __name__ == "__main__":
    all_items = items_b9 + items_b10 + items_b11
    print(f"Group 4: Curated {len(all_items)} candidate terms across batches 009, 010, 011.")
    append_curated_terms("vi", all_items)
