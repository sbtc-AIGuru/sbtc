#!/usr/bin/env python3
"""
curate_vi_group3.py - Curated medical entities from Batches 006, 007, 008
Curated by Vietnamese Medical Curator (Biomedical NLP Specialist)
"""

import sys
sys.path.insert(0, ".")
from sbtc.Scripts.Retrieval.curate_worker import append_curated_terms

items_b6 = [
    # Batch 006
    {"term": "hội chứng cushing", "class": "[DIS]", "source_id": 282766, "context": "Hội chứng Cushing do nồng độ hormone cortisol tăng cao kéo dài"},
    {"term": "cortisol", "class": "[ANA]", "source_id": 282766, "context": "hormone glucocorticoid cortisol do vỏ tuyến thượng thận bài tiết"},
    {"term": "gai đốt cột sống", "class": "[DIS]", "source_id": 232217, "context": "Gai đốt cột sống uống thuốc gì nhanh khỏi bệnh nhất?"},
    {"term": "gai cột sống", "class": "[DIS]", "source_id": 232217, "context": "hình thành gai xương dọc các bờ thân đốt sống gây chèn ép tủy"},
    {"term": "cắt túi mật nội soi", "class": "[PROC]", "source_id": 222491, "context": "Cắt túi mật nội soi: Ưu điểm, chỉ định, chống chỉ định và quy trình thực hiện"},
    {"term": "túi mật", "class": "[ANA]", "source_id": 222491, "context": "túi mật dự trữ và cô đặc dịch mật từ gan chuyển xuống"},
    {"term": "sỏi túi mật", "class": "[DIS]", "source_id": 222491, "context": "chỉ định mổ nội soi cắt túi mật khi sỏi túi mật gây viêm tái phát"},
    {"term": "tế bào kupffer", "class": "[ANA]", "source_id": 266275, "context": "Tế bào kupffer là gì? Sự thật về thủ phạm gây ra các bệnh cho gan"},
    {"term": "cao ích mẫu", "class": "[DRUG]", "source_id": 277221, "context": "Uống Cao Ích Mẫu đẹp da có thật không? Các câu hỏi thường gặp về Cao Ích Mẫu"},
    {"term": "ích mẫu", "class": "[DRUG]", "source_id": 277221, "context": "vị thuốc ích mẫu Leonurus japonicus có tác dụng hoạt huyết điều kinh"},
    {"term": "rễ cây mú từn", "class": "[DRUG]", "source_id": 226672, "context": "Công dụng của rễ cây mú từn là gì? Những điểm cần lưu ý"},
    {"term": "sơ cứu đột quỵ não", "class": "[PROC]", "source_id": 240579, "context": "Khám phá 5 bước sơ cứu đột quỵ não đúng cách"},
    {"term": "đột quỵ não", "class": "[DIS]", "source_id": 240579, "context": "tai biến mạch máu não đột quỵ não do thiếu máu cục bộ hoặc xuất huyết não"},
    {"term": "sỏi đường mật trong gan", "class": "[DIS]", "source_id": 270456, "context": "Tìm hiểu cách điều trị sỏi đường mật trong gan"},
    {"term": "đường mật", "class": "[ANA]", "source_id": 270456, "context": "sỏi lắng đọng gây tắc nghẽn đường mật và nhiễm trùng đường mật ngược dòng"},
    {"term": "siêu âm đầu dò âm đạo", "class": "[PROC]", "source_id": 241799, "context": "Kinh nghiệm siêu âm đầu dò âm đạo kiểm tra tử cung phần phụ"},
    {"term": "sùi mào gà", "class": "[DIS]", "source_id": 267872, "context": "Thời gian ủ bệnh sùi mào gà bao lâu? Khi nào phát bệnh?"},
    {"term": "bệnh giang mai", "class": "[DIS]", "source_id": 228269, "context": "Dấu hiệu bệnh giang mai ở nam giới qua các giai đoạn"},
    {"term": "xoắn khuẩn giang mai", "class": "[DIS]", "source_id": 228269, "context": "xoắn khuẩn giang mai Treponema pallidum lây qua đường tình dục"},
    {"term": "máu loãng", "class": "[DIS]", "source_id": 250161, "context": "Người bị máu loãng kiêng ăn gì, nên ăn gì?"},
    {"term": "xuất huyết tiêu hóa", "class": "[DIS]", "source_id": 221504, "context": "Cách xử trí cầm máu xuất huyết tiêu hóa cấp"},
    {"term": "gãy xương mác", "class": "[DIS]", "source_id": 232450, "context": "Gãy xương mác là gì? Có cần bó bột không?"},
    {"term": "xương mác", "class": "[ANA]", "source_id": 232450, "context": "xương mác chạy song song ngoài xương chày ở cẳng chân"},
    {"term": "thắt trĩ bằng vòng cao su", "class": "[PROC]", "source_id": 254342, "context": "Những điều cần biết về phương pháp thắt trĩ bằng vòng cao su"},
    {"term": "bệnh trĩ", "class": "[DIS]", "source_id": 254342, "context": "trĩ nội và trĩ ngoại do giãn quá mức đám rối tĩnh mạch trĩ"},
    {"term": "tiêm uốn ván", "class": "[PROC]", "source_id": 233903, "context": "Nên tiêm uốn ván mũi 2 cách mũi 1 bao lâu?"},
    {"term": "uốn ván", "class": "[DIS]", "source_id": 233903, "context": "độc tố tetanospasmin của trực khuẩn uốn ván gây co cứng cơ liên tục"},
    {"term": "bisolvon", "class": "[DRUG]", "source_id": 214739, "context": "Bisolvon có dùng được cho bà bầu không?"},
    {"term": "bromhexine", "class": "[DRUG]", "source_id": 214739, "context": "Bisolvon chứa hoạt chất Bromhexine hydroclorid giúp làm loãng đờm"},
    {"term": "mụn nước zona", "class": "[SYM]", "source_id": 225685, "context": "Có nên chọc mụn nước zona không? Vì sao?"},
    {"term": "zona thần kinh", "class": "[DIS]", "source_id": 225685, "context": "tái hoạt virus Varicella Zoster dọc theo dây thần kinh cảm giác"},
    {"term": "cong vẹo cột sống", "class": "[DIS]", "source_id": 247577, "context": "Một số loại đai chống cong vẹo cột sống được chuyên gia khuyên dùng"},
    {"term": "sặc sữa", "class": "[DIS]", "source_id": 275014, "context": "Trẻ thường xuyên bị sặc sữa mẹ nên làm gì?"},
    {"term": "mệt mỏi mãn tính", "class": "[DIS]", "source_id": 224465, "context": "Chớ chủ quan với triệu chứng mệt mỏi mãn tính kéo dài"},
]

items_b7 = [
    # Batch 007
    {"term": "tiêm filler", "class": "[PROC]", "source_id": 269469, "context": "Tiêm filler: Công dụng và ưu, nhược điểm bạn nên biết"},
    {"term": "filler", "class": "[DRUG]", "source_id": 269469, "context": "chất làm đầy filler có thành phần chính là acid hyaluronic liên kết chéo"},
    {"term": "trễ kinh ra máu cục", "class": "[SYM]", "source_id": 218920, "context": "Cách điều trị trễ kinh ra máu cục ở phụ nữ"},
    {"term": "maxxhair", "class": "[DRUG]", "source_id": 235411, "context": "Maxxhair có dùng cho phụ nữ cho con bú không?"},
    {"term": "dị dạng tử cung", "class": "[DIS]", "source_id": 229866, "context": "Dị dạng tử cung: Ảnh hưởng như thế nào đến khả năng mang thai?"},
    {"term": "rễ cây sim", "class": "[DRUG]", "source_id": 246357, "context": "Mẹo dùng rễ cây sim chữa bệnh dạ dày không phải ai cũng biết"},
    {"term": "không dung nạp fructose", "class": "[DIS]", "source_id": 217700, "context": "Các vấn đề về việc cơ thể không dung nạp fructose bạn nên biết"},
    {"term": "chấm tàn nhang", "class": "[PROC]", "source_id": 223101, "context": "Chấm tàn nhang kiêng nước bao lâu?"},
    {"term": "lao tinh hoàn", "class": "[DIS]", "source_id": 255939, "context": "Những thông tin cơ bản về căn bệnh lao tinh hoàn ở nam giới"},
    {"term": "tinh hoàn", "class": "[ANA]", "source_id": 255939, "context": "vi khuẩn lao xâm nhập gây sưng đau và teo nhu mô tinh hoàn"},
    {"term": "estrogen", "class": "[DRUG]", "source_id": 277831, "context": "Uống thuốc Estrogen có hại không? Những điều cần biết"},
    {"term": "đa nang buồng trứng", "class": "[DIS]", "source_id": 227282, "context": "Đa nang buồng trứng có nên uống sữa ong chúa không?"},
    {"term": "sữa ong chúa", "class": "[DRUG]", "source_id": 227282, "context": "sữa ong chúa chứa nhiều axit amin và hormone tự nhiên"},
    {"term": "lao phổi", "class": "[DIS]", "source_id": 272430, "context": "Tổng hợp quá trình điều trị lao phổi bằng phác đồ DOTS"},
    {"term": "bàn chân xoay trong", "class": "[DIS]", "source_id": 209571, "context": "Bàn chân xoay trong ở trẻ: Cách nhận biết và điều trị hiệu quả"},
    {"term": "trật khớp cùng đòn", "class": "[DIS]", "source_id": 283376, "context": "Trật khớp cùng đòn do đứt dây chằng cùng đòn và quạ đòn"},
    {"term": "khớp cùng đòn", "class": "[ANA]", "source_id": 283376, "context": "khớp nối giữa đầu ngoài xương đòn và mỏm cùng vai"},
    {"term": "vắc xin rota", "class": "[DRUG]", "source_id": 278297, "context": "Vắc xin Rota có mấy loại? Những lưu ý khi sử dụng vắc xin Rota"},
    {"term": "rotavirus", "class": "[DIS]", "source_id": 278297, "context": "virus rota gây viêm dạ dày ruột cấp tính và mất nước nặng ở trẻ"},
    {"term": "đặt catheter tĩnh mạch ngoại biên", "class": "[PROC]", "source_id": 227748, "context": "Đặt catheter tĩnh mạch ngoại biên là gì? Đối tượng cần đặt"},
    {"term": "catheter tĩnh mạch ngoại biên", "class": "[PROC]", "source_id": 227748, "context": "ống thông luồn vào tĩnh mạch ngoại vi để truyền dịch và thuốc"},
    {"term": "penicillin", "class": "[DRUG]", "source_id": 257536, "context": "Penicillin là kháng sinh gì? Các triệu chứng dị ứng penicillin"},
    {"term": "dị ứng penicillin", "class": "[DIS]", "source_id": 257536, "context": "phản vệ dị ứng thuốc penicillin biểu hiện mày đay, khó thở"},
    {"term": "huyết khối tĩnh mạch sâu", "class": "[DIS]", "source_id": 239825, "context": "Huyết khối tĩnh mạch sâu là bệnh gì? Cách phòng ngừa"},
    {"term": "tĩnh mạch sâu", "class": "[ANA]", "source_id": 239825, "context": "cục máu đông hình thành trong hệ tĩnh mạch sâu chi dưới"},
    {"term": "xét nghiệm sàng lọc trước sinh", "class": "[PROC]", "source_id": 281635, "context": "Xét nghiệm sàng lọc trước sinh bao gồm Double test, Triple test, NIPT"},
    {"term": "gai cột sống cổ", "class": "[DIS]", "source_id": 272663, "context": "Top 3 cách trị gai cột sống cổ tại nhà dễ thực hiện"},
    {"term": "cột sống cổ", "class": "[ANA]", "source_id": 272663, "context": "gai thoái hóa các đốt sống cổ C4-C7 gây đau mỏi vai gáy"},
    {"term": "dầu gấc", "class": "[DRUG]", "source_id": 233060, "context": "Giải đáp: Dầu gấc nên uống vào lúc nào là tốt nhất?"},
    {"term": "thuốc tránh thai khẩn cấp", "class": "[DRUG]", "source_id": 226295, "context": "Có thai uống thuốc tránh thai khẩn cấp có sao không?"},
    {"term": "levonorgestrel", "class": "[DRUG]", "source_id": 226295, "context": "hoạt chất Progestin tổng hợp levonorgestrel trong viên tránh thai khẩn cấp"},
    {"term": "gây tê ngoài màng cứng", "class": "[PROC]", "source_id": 259133, "context": "Phương pháp gây tê ngoài màng cứng giảm đau sản khoa"},
    {"term": "viêm khớp", "class": "[DIS]", "source_id": 208584, "context": "Arthritis là bệnh viêm khớp gây sưng đau và hạn chế vận động"},
    {"term": "xạ trị ung thư tuyến tiền liệt", "class": "[PROC]", "source_id": 281025, "context": "Xạ trị ung thư tuyến tiền liệt: Khi nào cần thực hiện?"},
    {"term": "vắc xin covid", "class": "[DRUG]", "source_id": 278208, "context": "Vắc xin Covid phải tiêm mấy mũi? Mỗi mũi tiêm cách nhau bao lâu?"},
]

items_b8 = [
    # Batch 008
    {"term": "ngộ độc quetiapine", "class": "[DIS]", "source_id": 249551, "context": "Ngộ độc quetiapine là gì? Tác dụng và những lưu ý khi sử dụng"},
    {"term": "quetiapine", "class": "[DRUG]", "source_id": 249551, "context": "thuốc chống loạn thần không điển hình quetiapine"},
    {"term": "tâm thần phân liệt", "class": "[DIS]", "source_id": 249551, "context": "quetiapine chỉ định điều trị tâm thần phân liệt và rối loạn lưỡng cực"},
    {"term": "rối loạn lưỡng cực", "class": "[DIS]", "source_id": 249551, "context": "quetiapine kiểm soát pha hưng cảm trong rối loạn lưỡng cực"},
    {"term": "cận thị", "class": "[DIS]", "source_id": 234657, "context": "Giải pháp chống cận thị khi ngồi máy tính hiệu quả nhất"},
    {"term": "bệnh crohn", "class": "[DIS]", "source_id": 282389, "context": "Bệnh Crohn là một bệnh gây viêm mạn tính ở đường tiêu hóa"},
    {"term": "viêm ruột mạn tính", "class": "[DIS]", "source_id": 282389, "context": "viêm ruột mãn tính từng vùng tổn thương xuyên thành ruột"},
    {"term": "đau tim", "class": "[SYM]", "source_id": 242786, "context": "Lên cơn đau tim mà chỉ có một mình, phải làm sao?"},
    {"term": "ngứa bìu về đêm", "class": "[SYM]", "source_id": 249784, "context": "Ngứa bìu về đêm: Nguyên nhân và biện pháp phòng ngừa"},
    {"term": "bìu", "class": "[ANA]", "source_id": 249784, "context": "vùng da bìu bị nhiễm nấm candida hoặc ghẻ ngứa dữ dội"},
    {"term": "bệnh quai bị", "class": "[DIS]", "source_id": 253732, "context": "Những dấu hiệu bệnh quai bị và cách phòng tránh bệnh"},
    {"term": "viêm tuyến mang tai", "class": "[DIS]", "source_id": 253732, "context": "virus quai bị gây viêm sưng tuyến mang tai hai bên"},
    {"term": "tĩnh mạch cổ nổi", "class": "[SYM]", "source_id": 271676, "context": "Tĩnh mạch cổ nổi có nguy hiểm không? Dấu hiệu ứ trệ tuần hoàn"},
    {"term": "tĩnh mạch cổ", "class": "[ANA]", "source_id": 271676, "context": "tĩnh mạch cảnh ngoài nổi phồng khi áp lực nhĩ phải tăng cao"},
    {"term": "nấm lim xanh", "class": "[DRUG]", "source_id": 275624, "context": "Nấm lim xanh là thực phẩm giàu dinh dưỡng và được dùng như dược liệu quý"},
    {"term": "chuột rút khi mang thai", "class": "[SYM]", "source_id": 225075, "context": "Chuột rút khi mang thai: Nguyên nhân do đâu và cách phòng ngừa"},
    {"term": "chủng delta", "class": "[DIS]", "source_id": 257913, "context": "Phân biệt sự khác nhau giữa chủng Delta và Omicron"},
    {"term": "chủng omicron", "class": "[DIS]", "source_id": 257913, "context": "biến thể Omicron của virus Sars-CoV-2 gây lây lan nhanh"},
    {"term": "phẫu thuật bong võng mạc", "class": "[PROC]", "source_id": 258146, "context": "Phẫu thuật bong võng mạc diễn ra như thế nào?"},
    {"term": "bong võng mạc", "class": "[DIS]", "source_id": 258146, "context": "Võng mạc bị bong là một bệnh rất nặng của nhãn khoa"},
    {"term": "võng mạc", "class": "[ANA]", "source_id": 258146, "context": "lớp võng mạc cảm thụ ánh sáng ở đáy mắt bị tách khỏi biểu mô sắc tố"},
    {"term": "thuốc tanganil", "class": "[DRUG]", "source_id": 269092, "context": "Thuốc Tanganil uống trong bao lâu? Những lưu ý khi sử dụng"},
    {"term": "acetylleucine", "class": "[DRUG]", "source_id": 269092, "context": "Thuốc Tanganil (acetylleucine) điều trị cơn chóng mặt tiền đình"},
    {"term": "nói lắp", "class": "[DIS]", "source_id": 218543, "context": "Nói lắp là một chứng rối loạn ngôn ngữ thường gặp"},
    {"term": "vắc xin abrysvo", "class": "[DRUG]", "source_id": 264534, "context": "Hiện nay, vắc xin Abrysvo (Pfizer) đã được cấp phép phòng RSV"},
    {"term": "virus hợp bào hô hấp rsv", "class": "[DIS]", "source_id": 264534, "context": "nhiễm virus hợp bào hô hấp RSV gây viêm tiểu phế quản ở trẻ nhỏ"},
    {"term": "sốc nhiễm trùng", "class": "[DIS]", "source_id": 257625, "context": "Phác đồ điều trị sốc nhiễm trùng Bộ Y tế"},
    {"term": "nhiễm khuẩn huyết", "class": "[DIS]", "source_id": 257625, "context": "viêm nhiễm nặng dẫn đến nhiễm khuẩn huyết và suy đa tạng"},
    {"term": "hút mỡ bụng", "class": "[PROC]", "source_id": 251381, "context": "Nguyên nhân hút mỡ bụng bị lồi lõm và cách khắc phục"},
    {"term": "cấy que tránh thai", "class": "[PROC]", "source_id": 222724, "context": "Cấy que tránh thai có được xuất vào trong không?"},
    {"term": "chữa viêm tủy răng", "class": "[PROC]", "source_id": 233437, "context": "Tại sao chữa viêm tủy răng xong vẫn đau nhức?"},
    {"term": "gây mê", "class": "[PROC]", "source_id": 266508, "context": "Gây mê hay gây tê đều là phương pháp giúp bệnh nhân giảm thiểu đau đớn"},
    {"term": "gây tê", "class": "[PROC]", "source_id": 266508, "context": "phương pháp vô cảm gây tê vùng hoặc gây tê tại chỗ"},
    {"term": "hội chứng colic", "class": "[DIS]", "source_id": 237851, "context": "Hội chứng quấy khóc ở trẻ nhũ nhi hay cơn khóc dạ đề colic"},
    {"term": "bacillus subtilis", "class": "[DRUG]", "source_id": 209194, "context": "Bacillus subtilis là gì? Tác dụng của Bacillus subtilis đối với tiêu hóa"},
    {"term": "hội chứng bong da do tụ cầu", "class": "[DIS]", "source_id": 237618, "context": "Hội chứng bong da do tụ cầu: Những điều cần biết"},
    {"term": "staphylococcus aureus", "class": "[DIS]", "source_id": 237618, "context": "độc tố bong da do tụ cầu vàng Staphylococcus aureus tiết ra"},
]

if __name__ == "__main__":
    all_items = items_b6 + items_b7 + items_b8
    print(f"Group 3: Curated {len(all_items)} candidate terms across batches 006, 007, 008.")
    append_curated_terms("vi", all_items)
