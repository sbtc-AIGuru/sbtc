#!/usr/bin/env python3
"""
curate_vi_group5.py - Curated medical entities from Batches 012, 013, 014
Curated by Vietnamese Medical Curator (Biomedical NLP Specialist)
"""

import sys
sys.path.insert(0, ".")
from BackEnd.app.Retrieval.curate_worker import append_curated_terms

items_b12 = [
    # Batch 012
    {"term": "nấm da tinea", "class": "[DIS]", "source_id": 248043, "context": "Nấm da Tinea là gì? Nguyên nhân và triệu chứng nấm da Tinea corporis"},
    {"term": "viêm khớp nhiễm trùng", "class": "[DIS]", "source_id": 258989, "context": "Phương pháp chẩn đoán và phác đồ điều trị viêm khớp nhiễm trùng sinh mủ"},
    {"term": "tăng huyết áp thai kỳ", "class": "[DIS]", "source_id": 273317, "context": "Tăng huyết áp thai kỳ cảnh báo nguy cơ tiền sản giật co giật"},
    {"term": "tiền sản giật", "class": "[DIS]", "source_id": 273317, "context": "hội chứng tiền sản giật nặng với protein niệu và phù toàn thân"},
    {"term": "protein niệu", "class": "[SYM]", "source_id": 273317, "context": "xuất hiện protein niệu trong nước tiểu của phụ nữ mang thai"},
    {"term": "gai gót chân", "class": "[DIS]", "source_id": 233714, "context": "Gai gót chân gây đau nhức thấu xương khi đặt chân xuống sàn"},
    {"term": "xương gót", "class": "[ANA]", "source_id": 233714, "context": "chồi xương gai mọc ra từ mặt dưới củ xương gót chân"},
    {"term": "nhau bám mặt trước", "class": "[DIS]", "source_id": 244660, "context": "Vị trí nhau bám mặt trước thành tử cung trong siêu âm sản khoa"},
    {"term": "thuyên tắc ối", "class": "[DIS]", "source_id": 266552, "context": "Thuyên tắc ối là tai biến sản khoa nguy kịch đe dọa tính mạng"},
    {"term": "nước ối", "class": "[ANA]", "source_id": 266552, "context": "dịch nước ối và tế bào biểu bì thai nhi tràn vào tuần hoàn mẹ"},
    {"term": "u xơ tuyến tiền liệt", "class": "[DIS]", "source_id": 277498, "context": "U xơ tuyến tiền liệt phì đại lành tính gây tiểu khó tiểu đêm"},
    {"term": "đốt viêm lộ tuyến cổ tử cung", "class": "[PROC]", "source_id": 226949, "context": "Đốt viêm lộ tuyến cổ tử cung bằng sóng cao tần hoặc laser"},
    {"term": "viêm lộ tuyến cổ tử cung", "class": "[DIS]", "source_id": 226949, "context": "tế bào tuyến lộ ra ngoài cổ tử cung bị viêm nhiễm tăng tiết dịch"},
    {"term": "huyết khối tĩnh mạch", "class": "[DIS]", "source_id": 237895, "context": "hình thành cục huyết khối tĩnh mạch gây tắc nghẽn dòng máu trở về tim"},
    {"term": "thuốc chống đông máu", "class": "[DRUG]", "source_id": 237895, "context": "dùng thuốc chống đông máu warfarin để ngăn ngừa huyết khối tái phát"},
    {"term": "warfarin", "class": "[DRUG]", "source_id": 237895, "context": "thuốc kháng vitamin K warfarin kiểm soát chỉ số INR"},
    {"term": "viêm loét dạ dày tá tràng", "class": "[DIS]", "source_id": 248841, "context": "Viêm loét dạ dày tá tràng gây cơn đau thượng vị âm ỉ lúc đói"},
    {"term": "tá tràng", "class": "[ANA]", "source_id": 248841, "context": "đoạn hành tá tràng thường là nơi dễ xuất hiện ổ loét sâu"},
    {"term": "cắt bao quy đầu", "class": "[PROC]", "source_id": 218200, "context": "Phẫu thuật cắt bao quy đầu điều trị hẹp hoặc nghẹt bao quy đầu"},
    {"term": "hẹp bao quy đầu", "class": "[DIS]", "source_id": 218200, "context": "tình trạng vòng thắt hẹp bao quy đầu không tuột xuống được"},
    {"term": "đau dây thần kinh tọa", "class": "[DIS]", "source_id": 229146, "context": "Cơn đau dây thần kinh tọa chạy dọc từ thắt lưng lan xuống đùi và cẳng chân"},
    {"term": "thần kinh tọa", "class": "[ANA]", "source_id": 229146, "context": "dây thần kinh tọa to nhất cơ thể chịu lực ép từ đĩa đệm thoát vị"},
]

items_b13 = [
    # Batch 013
    {"term": "hội chứng ganser", "class": "[DIS]", "source_id": 237707, "context": "Hội chứng Ganser là gì? Rối loạn tâm thần phân ly với câu trả lời xấp xỉ"},
    {"term": "chụp mri ngực bụng chậu", "class": "[PROC]", "source_id": 270545, "context": "Tìm hiểu chi tiết về phương pháp chụp MRI ngực bụng chậu đa dãy"},
    {"term": "chụp cộng hưởng từ", "class": "[PROC]", "source_id": 270545, "context": "chụp cộng hưởng từ MRI không sử dụng tia xạ giúp chẩn đoán mô mềm rõ nét"},
    {"term": "ung thư gan", "class": "[DIS]", "source_id": 272286, "context": "Tổng hợp các loại sữa dành cho người bị ung thư gan nguyên phát"},
    {"term": "ung thư biểu mô tế bào gan", "class": "[DIS]", "source_id": 272286, "context": "ung thư biểu mô tế bào gan HCC phát triển trên nền xơ gan"},
    {"term": "suy tim mạn tính", "class": "[DIS]", "source_id": 283232, "context": "Suy tim mạn tính phân suất tống máu giảm gây khó thở khi gắng sức"},
    {"term": "suy tim sung huyết", "class": "[DIS]", "source_id": 283232, "context": "ứ trệ tuần hoàn ngoại vi gây suy tim sung huyết và phù hai chi dưới"},
    {"term": "nước mũi có mùi hôi", "class": "[SYM]", "source_id": 257015, "context": "Nước mũi có mùi hôi ở trẻ em là dấu hiệu viêm xoang hoặc dị vật mũi"},
    {"term": "dị vật mũi", "class": "[DIS]", "source_id": 257015, "context": "dị vật mũi bỏ quên trong hốc mũi gây viêm loét chảy mủ hôi thối"},
    {"term": "rung giật nhãn cầu", "class": "[SYM]", "source_id": 261196, "context": "Rung giật nhãn cầu nystagmus là các cử động lắc lư nhịp nhàng không tự chủ của mắt"},
    {"term": "nhãn cầu", "class": "[ANA]", "source_id": 261196, "context": "cấu trúc hình cầu của nhãn cầu nằm gọn trong ổ mắt"},
    {"term": "bệnh ghẻ ruồi", "class": "[DIS]", "source_id": 232539, "context": "Ghẻ ruồi: Nguyên nhân do ký sinh trùng cái ghẻ đào hầm dưới da"},
    {"term": "cái ghẻ", "class": "[DIS]", "source_id": 232539, "context": "ký sinh trùng cái ghẻ Sarcoptes scabiei đẻ trứng tạo đường hầm ngứa đêm"},
    {"term": "mụn đinh râu", "class": "[DIS]", "source_id": 247810, "context": "Mụn đinh râu sử dụng những loại kháng sinh nào? Nguy cơ nhiễm trùng tam giác mặt"},
    {"term": "tam giác mặt", "class": "[ANA]", "source_id": 247810, "context": "vùng tam giác mặt nguy hiểm từ gốc mũi xuống hai khóe miệng"},
    {"term": "viêm tắc xoang hang", "class": "[DIS]", "source_id": 247810, "context": "nặn mụn đinh râu sai cách đẩy vi khuẩn gây viêm tắc xoang hang não"},
    {"term": "u bã đậu mí mắt", "class": "[DIS]", "source_id": 276323, "context": "U bã đậu mí mắt có tái phát không? Phẫu thuật bóc nang bã đậu"},
    {"term": "u bã đậu", "class": "[DIS]", "source_id": 276323, "context": "u nang lành tính phát triển chậm do ứ trệ chất bã nhờn dưới da"},
    {"term": "khí hư màu xanh", "class": "[SYM]", "source_id": 241045, "context": "Khí hư màu xanh có bọt là dấu hiệu nhiễm trùng roi Trichomonas"},
    {"term": "trùng roi âm đạo", "class": "[DIS]", "source_id": 241045, "context": "ký sinh trùng trùng roi âm đạo Trichomonas vaginalis gây viêm âm đạo"},
    {"term": "trật khớp thái dương hàm", "class": "[DIS]", "source_id": 273883, "context": "Trật khớp thái dương hàm có nguy hiểm không? Lồi cầu trượt ra trước"},
    {"term": "nắn trật khớp thái dương hàm", "class": "[PROC]", "source_id": 273883, "context": "thủ thuật dùng ngón cái nắn trật khớp thái dương hàm đưa lồi cầu về ổ khớp"},
    {"term": "niềng răng trong suốt", "class": "[PROC]", "source_id": 256172, "context": "Những ưu nhược điểm của niềng răng trong suốt máng chỉnh nha"},
    {"term": "bơm tinh trùng vào buồng tử cung", "class": "[PROC]", "source_id": 271299, "context": "Tìm hiểu về phương pháp bơm tinh trùng vào buồng tử cung IUI"},
    {"term": "retinol", "class": "[DRUG]", "source_id": 231696, "context": "Dùng retinol bị lên mụn bùng phát mụn viêm (purging) xử trí như thế nào?"},
    {"term": "bệnh lao màng não", "class": "[DIS]", "source_id": 242642, "context": "Bệnh lao màng não điều trị bao lâu thì mới khỏi hẳn? Biến chứng dính màng não"},
    {"term": "áp xe quanh chóp răng", "class": "[DIS]", "source_id": 246823, "context": "Mọc mụn ở lợi chân răng là dấu hiệu ổ áp xe quanh chóp răng rò mủ"},
    {"term": "viêm giác mạc", "class": "[DIS]", "source_id": 279661, "context": "Viêm giác mạc có lây không? Tình trạng thâm nhiễm viêm giác mạc đục mờ"},
    {"term": "loét giác mạc", "class": "[DIS]", "source_id": 279661, "context": "viêm loét giác mạc do vi khuẩn nấm có nguy cơ thủng giác mạc mù vĩnh viễn"},
]

items_b14 = [
    # Batch 014
    {"term": "xơ cứng rải rác", "class": "[DIS]", "source_id": 283842, "context": "Xơ cứng rải rác Multiple Sclerosis là bệnh tự miễn phá hủy bao myelin thần kinh"},
    {"term": "bao myelin", "class": "[ANA]", "source_id": 283842, "context": "tổn thương viêm làm mất bao myelin dẫn truyền xung động thần kinh"},
    {"term": "rôm sảy", "class": "[DIS]", "source_id": 255185, "context": "Rôm sảy là bệnh da liễu thường gặp ở trẻ nhỏ mùa nắng nóng do bít tắc tuyến mồ hôi"},
    {"term": "tuyến mồ hôi", "class": "[ANA]", "source_id": 255185, "context": "ống bài xuất tuyến mồ hôi bị nghẽn tạo nên mụn nước rôm sảy"},
    {"term": "cơn co tử cung", "class": "[SYM]", "source_id": 226528, "context": "Cơn co tử cung đẩy thai nhi ra ngoài trong lúc mẹ bầu chuyển dạ"},
    {"term": "chuyển dạ", "class": "[ANA]", "source_id": 226528, "context": "giai đoạn chuyển dạ sinh con xuất hiện cơn co bóp tử cung đều đặn"},
    {"term": "u lympho không hodgkin", "class": "[DIS]", "source_id": 237474, "context": "Bệnh u lympho không Hodgkin (NHL) là một căn bệnh ung thư ác tính hệ lympho"},
    {"term": "hóa trị ung thư", "class": "[PROC]", "source_id": 237474, "context": "phác đồ đa hóa trị liệu kết hợp kháng thể đơn dòng trong điều trị ung thư"},
    {"term": "polyp cổ tử cung", "class": "[DIS]", "source_id": 259366, "context": "Polyp cổ tử cung có gây ung thư không? U nhú lành tính trong kênh cổ tử cung"},
    {"term": "bại não liệt tứ chi", "class": "[DIS]", "source_id": 230709, "context": "Điều trị cho trẻ bị bại não liệt tứ chi bằng vật lý trị liệu phục hồi chức năng"},
    {"term": "liệt tứ chi", "class": "[SYM]", "source_id": 230709, "context": "tổn thương thần kinh trung ương gây mất chức năng vận động và liệt tứ chi"},
    {"term": "nhiễm sán chó", "class": "[DIS]", "source_id": 252601, "context": "Nhiễm sán chó có lây từ người sang người không? Hội chứng ấu trùng di chuyển nội tạng"},
    {"term": "toxocara canis", "class": "[DIS]", "source_id": 252601, "context": "ấu trùng giun đũa chó Toxocara canis xâm nhập vào máu người"},
    {"term": "bổ phế nam hà", "class": "[DRUG]", "source_id": 234890, "context": "Giảm ho bằng thực phẩm bảo vệ sức khỏe Bổ phế Nam Hà XC"},
    {"term": "nốt thủy đậu", "class": "[SYM]", "source_id": 256782, "context": "Nốt thủy đậu như thế nào và cách xử trí hiệu quả để tránh sẹo lõm"},
    {"term": "thoái hóa cột sống thắt lưng", "class": "[DIS]", "source_id": 267728, "context": "Thoái hóa cột sống thắt lưng là vấn đề xương khớp thường gặp ở người già"},
    {"term": "liệt dây thần kinh số 6", "class": "[DIS]", "source_id": 282855, "context": "Liệt dây thần kinh số 6 (dây vận nhãn ngoài) gây lác trong và nhìn đôi song thị"},
    {"term": "dây thần kinh số 6", "class": "[ANA]", "source_id": 282855, "context": "dây thần kinh số VI chi phối duy nhất cơ thẳng ngoài nhãn cầu"},
    {"term": "song thị", "class": "[SYM]", "source_id": 282855, "context": "triệu chứng nhìn đôi một vật thành hai hình ảnh do liệt vận nhãn"},
    {"term": "quầng thâm mắt", "class": "[SYM]", "source_id": 243252, "context": "Loại bỏ quầng thâm mắt cực hiệu quả do thiếu ngủ và ứ trệ tuần hoàn tĩnh mạch"},
    {"term": "răng ê buốt", "class": "[SYM]", "source_id": 251614, "context": "Nguyên nhân răng ê buốt (răng nhạy cảm) do quá cảm ngà chân răng"},
    {"term": "quá cảm ngà", "class": "[DIS]", "source_id": 251614, "context": "lộ ống ngà răng khi tiếp xúc nóng lạnh chua ngọt gây buốt nhói"},
    {"term": "ngà răng", "class": "[ANA]", "source_id": 251614, "context": "lớp ngà răng nằm ngay dưới men răng chứa hàng ngàn ống ngà vi thể"},
    {"term": "bệnh bazodo", "class": "[DIS]", "source_id": 262560, "context": "So sánh bệnh bướu cổ và bệnh Bazodo Basedow cường giáp tự miễn"},
    {"term": "bướu cổ lồi mắt", "class": "[DIS]", "source_id": 262560, "context": "biểu hiện phì đại tuyến giáp kèm lồi mắt ác tính trong bệnh Basedow"},
    {"term": "cường giáp", "class": "[DIS]", "source_id": 262560, "context": "tăng tiết hormone tuyến giáp T3 T4 gây hội chứng nhiễm độc giáp"},
    {"term": "trà cà gai leo", "class": "[DRUG]", "source_id": 273506, "context": "Trà cà gai leo Kami tea hỗ trợ giải độc gan, hạ men gan hiệu quả"},
    {"term": "cà gai leo", "class": "[DRUG]", "source_id": 273506, "context": "vị thuốc cà gai leo Solanum hainanense chống viêm gan virus và xơ gan"},
    {"term": "ung thư tụy", "class": "[DIS]", "source_id": 222957, "context": "Chăm sóc bệnh nhân ung thư tụy giai đoạn cuối giảm đau đớn"},
    {"term": "tuyến tụy", "class": "[ANA]", "source_id": 222957, "context": "khối u ác tính thường xuất hiện ở vùng đầu tụy gây tắc mật vàng da"},
    {"term": "đau mắt hột", "class": "[DIS]", "source_id": 238084, "context": "Đau mắt hột Trachoma là bệnh viêm kết giác mạc do Chlamydia trachomatis"},
    {"term": "chlamydia trachomatis", "class": "[DIS]", "source_id": 238084, "context": "vi khuẩn nội bào Chlamydia trachomatis gây hột kết mạc và quặm mi"},
    {"term": "đốt mụn thịt", "class": "[PROC]", "source_id": 231319, "context": "Đốt mụn thịt bằng laser CO2 vi điểm loại bỏ u tuyến mồ hôi"},
    {"term": "mụn thịt", "class": "[DIS]", "source_id": 231319, "context": "các nốt u tuyến mồ hôi lành tính li ti quanh vùng mí mắt"},
    {"term": "lông mọc ngược", "class": "[DIS]", "source_id": 213608, "context": "Bị lông mọc ngược ở vùng kín gây viêm sưng nang lông và mụn nhọt"},
    {"term": "đồi mồi", "class": "[DIS]", "source_id": 275103, "context": "Trị chấm đồi mồi trên mặt do tăng sắc tố melanin theo tuổi tác"},
]

if __name__ == "__main__":
    all_items = items_b12 + items_b13 + items_b14
    print(f"Group 5: Curated {len(all_items)} candidate terms across batches 012, 013, 014.")
    append_curated_terms("vi", all_items)
