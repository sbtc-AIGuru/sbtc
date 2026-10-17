#!/usr/bin/env python3
"""
curate_vi_group6.py - Deep clinical entity curation across all 15 batches (Group 6)
Curated by Vietnamese Medical Curator (Biomedical NLP Specialist)
"""

import sys
sys.path.insert(0, ".")
from BackEnd.app.Retrieval.curate_worker import append_curated_terms

items_deep = [
    # DIS
    {"term": "rối loạn cơ thể hóa", "class": "[DIS]", "source_id": 260874, "context": "Rối loạn cơ thể hóa somatization disorder biểu hiện triệu chứng thực thể không rõ tổn thương"},
    {"term": "tâm căn nghi bệnh", "class": "[DIS]", "source_id": 260874, "context": "tâm căn nghi bệnh hypochondriasis luôn lo sợ mắc bệnh hiểm nghèo"},
    {"term": "hội chứng bàn chân bẹt", "class": "[DIS]", "source_id": 251148, "context": "Trẻ bị hội chứng bàn chân bẹt thường có toàn bộ lòng bàn chân sụp chạm đất"},
    {"term": "bàn chân bẹt", "class": "[DIS]", "source_id": 251148, "context": "mất vòm bàn chân dọc dẫn tới tật bàn chân bẹt vẹo trục cổ chân"},
    {"term": "bệnh ban đào", "class": "[DIS]", "source_id": 211545, "context": "Bệnh ban đào Roseola infantum ở trẻ nhỏ do virus Herpes type 6"},
    {"term": "bệnh giời leo", "class": "[DIS]", "source_id": 225685, "context": "Zona hay còn gọi là bệnh giời leo do virus varicella-zoster tái hoạt"},
    {"term": "nấm bìu", "class": "[DIS]", "source_id": 249784, "context": "nhiễm nấm bìu Tinea cruris gây ngứa ngáy dữ dội về ban đêm"},
    {"term": "chàm bìu", "class": "[DIS]", "source_id": 249784, "context": "viêm da dị ứng chàm bìu mạn tính dày sừng thâm nhiễm"},
    {"term": "ung thư da", "class": "[DIS]", "source_id": 204780, "context": "tia cực tím UV gây tổn thương DNA biểu mô làm tăng nguy cơ ung thư da"},
    {"term": "sùi mào gà ở lưỡi", "class": "[DIS]", "source_id": 263924, "context": "Sùi mào gà ở lưỡi: U nhú gai sinh dục phát triển tại niêm mạc lưỡi miệng"},
    {"term": "bệnh giun lươn", "class": "[DIS]", "source_id": 230853, "context": "Điều trị và phòng tránh bệnh giun lươn Strongyloides stercoralis tự nhiễm"},
    {"term": "bướu máu ở lưỡi", "class": "[DIS]", "source_id": 268105, "context": "Tình trạng bướu máu ở lưỡi dị dạng mạch máu vùng hàm mặt ở trẻ nhỏ"},
    {"term": "u máu", "class": "[DIS]", "source_id": 268105, "context": "u máu thể hang lành tính vùng niêm mạc khoang miệng"},
    {"term": "viêm mũi không do dị ứng", "class": "[DIS]", "source_id": 228502, "context": "Dấu hiệu nhận biết bạn bị bệnh viêm mũi không do dị ứng viêm mũi vận mạch"},
    {"term": "u nguyên bào màng phổi", "class": "[DIS]", "source_id": 276467, "context": "U nguyên bào màng phổi Pleuropulmonary blastoma ở trẻ em"},
    {"term": "bệnh leptospira", "class": "[DIS]", "source_id": 282999, "context": "Bệnh Leptospira xoắn khuẩn lây truyền từ nước tiểu động vật gặm nhấm"},
    {"term": "tuyến giáp to", "class": "[SYM]", "source_id": 276234, "context": "Tuyến giáp to phì đại cảnh báo nhiều bệnh lý tuyến giáp"},
    {"term": "viêm mũi dị ứng", "class": "[DIS]", "source_id": 236631, "context": "Hậu quả của bệnh viêm mũi dị ứng khi tiếp xúc phấn hoa bụi nhà"},
    {"term": "bệnh bạch hầu", "class": "[DIS]", "source_id": 257769, "context": "Bạch hầu do trực khuẩn Corynebacterium diphtheriae tạo giả mạc hầu họng"},
    {"term": "viêm phổi cấp ở trẻ em", "class": "[DIS]", "source_id": 280038, "context": "Viêm phổi cấp ở trẻ em thở nhanh rút lõm lồng ngực"},
    {"term": "viêm phổi cấp", "class": "[DIS]", "source_id": 280038, "context": "viêm phổi cấp tính do phế cầu khuẩn và tụ cầu vàng"},
    {"term": "trẻ sinh non", "class": "[DIS]", "source_id": 262327, "context": "trẻ sinh non nhẹ cân dưới 37 tuần thai có nguy cơ suy hô hấp"},
    {"term": "khiếm thị", "class": "[DIS]", "source_id": 262327, "context": "di chứng bệnh võng mạc trẻ đẻ non ROP gây mù lòa khiếm thị"},
    {"term": "khiếm thính", "class": "[DIS]", "source_id": 262327, "context": "giảm hoặc mất thính lực thần kinh giác quan gây khiếm thính"},
    {"term": "đứt dây chằng đầu gối", "class": "[DIS]", "source_id": 231929, "context": "Đứt dây chằng đầu gối mất vững khớp gối sau chấn thương thể thao"},
    {"term": "viêm đại tràng", "class": "[DIS]", "source_id": 253821, "context": "Những dấu hiệu nhận biết viêm đại tràng đau quặn bụng phân nhầy máu"},
    {"term": "viêm đại tràng co thắt", "class": "[DIS]", "source_id": 253821, "context": "hội chứng ruột kích thích IBS hay viêm đại tràng co thắt"},
    {"term": "viêm màng não phế cầu", "class": "[DIS]", "source_id": 279894, "context": "Viêm màng não phế cầu Streptococcus pneumoniae gây sốt cao mê sảng"},
    {"term": "phế cầu khuẩn", "class": "[DIS]", "source_id": 279894, "context": "vi khuẩn phế cầu Streptococcus pneumoniae gây viêm phổi và viêm màng não"},
    {"term": "nhờn thuốc", "class": "[DIS]", "source_id": 252978, "context": "Nhờn thuốc là tình trạng kháng kháng sinh do dùng thuốc không đủ liều"},
    {"term": "cúm a", "class": "[DIS]", "source_id": 211634, "context": "Cúm A do virus Influenza A gây sốt rét run đau nhức cơ toàn thân"},
    {"term": "răng thừa", "class": "[DIS]", "source_id": 250394, "context": "Răng thừa mọc kẹt chèn ép sai lệch khớp cắn cung hàm"},
    {"term": "trầm cảm", "class": "[DIS]", "source_id": 249407, "context": "cảm giác cô đơn kéo dài dẫn đến rối loạn trầm cảm và sa sút trí tuệ"},
    {"term": "thoái hóa cột sống", "class": "[DIS]", "source_id": 240668, "context": "thoái hóa cột sống dẫn tới mọc chồi gai xương chèn ép tủy sống"},
    {"term": "viêm da đầu", "class": "[DIS]", "source_id": 216857, "context": "viêm da dầu viêm da đầu tiết bã nhờn ngứa ngáy bong tróc vảy"},
    
    # DRUG
    {"term": "hormone ghrelin", "class": "[DRUG]", "source_id": 267406, "context": "Hormone ghrelin kích thích sự thèm ăn được dạ dày tiết ra"},
    {"term": "vitamin d3", "class": "[DRUG]", "source_id": 278064, "context": "cholecalciferol Vitamin D3 giúp tăng cường hấp thu canxi tại ruột non"},
    {"term": "progestin", "class": "[DRUG]", "source_id": 222724, "context": "que cấy giải phóng hormone progestin làm đặc chất nhầy cổ tử cung"},
    {"term": "endorphin", "class": "[DRUG]", "source_id": 274637, "context": "chất dẫn truyền thần kinh opioid nội sinh endorphin giúp giảm đau và tạo sảng khoái"},
    {"term": "xanh methylen", "class": "[DRUG]", "source_id": 241278, "context": "chấm dung dịch sát trùng xanh methylen 1% lên các nốt bọng nước thủy đậu"},
    {"term": "que thử rụng trứng", "class": "[PROC]", "source_id": 238694, "context": "que thử rụng trứng đo nồng độ hormone LH đỉnh điểm trước khi phóng noãn"},
    {"term": "hormone lh", "class": "[DRUG]", "source_id": 238694, "context": "hormone Luteinizing LH do tuyến yên thùy trước bài tiết"},
    {"term": "thuốc đạn đặt hậu môn", "class": "[DRUG]", "source_id": 220695, "context": "Cách sử dụng thuốc đạn đặt hậu môn paracetamol hạ sốt cho trẻ nhỏ"},
    {"term": "thuốc đạn", "class": "[DRUG]", "source_id": 220695, "context": "dạng thuốc đạn tan chảy ở nhiệt độ cơ thể trong trực tràng"},
    {"term": "vắc xin phế cầu", "class": "[DRUG]", "source_id": 279894, "context": "tiêm phòng vắc xin phế cầu Synflorix hoặc Prevenar 13 cho trẻ"},
    {"term": "cây cà độc dược", "class": "[DRUG]", "source_id": 222580, "context": "Cây cà độc dược Datura metel chứa alcaloid kháng cholinergic scopolamine"},
    {"term": "cà độc dược", "class": "[DRUG]", "source_id": 222580, "context": "lá cà độc dược phơi khô thái nhỏ hút chữa hen suyễn trong đông y"},
    {"term": "scopolamine", "class": "[DRUG]", "source_id": 222580, "context": "alcaloid scopolamine chống co thắt cơ trơn và ức chế tiết dịch"},
    {"term": "atropine", "class": "[DRUG]", "source_id": 222580, "context": "thuốc giãn đồng tử và điều trị nhịp tim chậm atropine sulfat"},
    {"term": "lá rẻ quạt", "class": "[DRUG]", "source_id": 224321, "context": "Chia sẻ cách sử dụng lá rẻ quạt chữa viêm họng hạt khàn tiếng"},
    {"term": "cây rẻ quạt", "class": "[DRUG]", "source_id": 224321, "context": "vị thuốc xạ can từ thân rễ cây rẻ quạt Belamcanda chinensis"},
    {"term": "nấm linh chi", "class": "[DRUG]", "source_id": 238461, "context": "dược liệu quý nấm linh chi Ganoderma lucidum giàu polysaccharides"},

    # SYM
    {"term": "ngứa da đầu", "class": "[SYM]", "source_id": 216857, "context": "viêm da tiết bã gây ngứa da đầu và rụng tóc nhiều"},
    {"term": "ngứa tinh hoàn", "class": "[SYM]", "source_id": 249784, "context": "ngứa bìu và ngứa tinh hoàn vào ban đêm do nhiễm nấm bẹn"},
    {"term": "nghén chua", "class": "[SYM]", "source_id": 279051, "context": "triệu chứng ốm nghén nghén chua thèm đồ chua trong thai kỳ"},
    {"term": "ốm nghén", "class": "[SYM]", "source_id": 279051, "context": "nôn ói mệt mỏi trong hội chứng ốm nghén 3 tháng đầu thai kỳ"},
    {"term": "sốt cảm cúm", "class": "[SYM]", "source_id": 262371, "context": "sốt cao gai rét mỏi nhừ cơ khớp do sốt cảm cúm mùa"},
    {"term": "răng lung lay", "class": "[SYM]", "source_id": 260353, "context": "viêm quanh cuống răng làm tiêu xương ổ răng khiến răng lung lay"},
    {"term": "ê buốt chân răng", "class": "[SYM]", "source_id": 251614, "context": "triệu chứng ê buốt chân răng khi uống nước lạnh hoặc chải răng"},

    # ANA
    {"term": "vòm bàn chân", "class": "[ANA]", "source_id": 251148, "context": "vòm bàn chân có chức năng giảm xóc và chịu lực phân phối trọng lượng cơ thể"},
    {"term": "ruột già", "class": "[ANA]", "source_id": 224931, "context": "Ruột già đại tràng dài khoảng 1.5m có chức năng tái hấp thu nước và tạo phân"},
    {"term": "tinh trùng", "class": "[ANA]", "source_id": 256460, "context": "tế bào sinh dục nam tinh trùng được sinh ra từ các ống sinh tinh"},
    {"term": "nang trứng", "class": "[ANA]", "source_id": 238694, "context": "nang trứng Graaf phát triển và vỡ ra giải phóng noãn bào"},
    {"term": "dây chằng đầu gối", "class": "[ANA]", "source_id": 231929, "context": "hệ thống dây chằng đầu gối gồm dây chằng chéo trước và chéo sau"},
    {"term": "dây chằng chéo trước", "class": "[ANA]", "source_id": 231929, "context": "dây chằng chéo trước ACL giữ cho mâm chày không bị trượt ra trước"},
    {"term": "răng vĩnh viễn", "class": "[ANA]", "source_id": 260353, "context": "bộ răng vĩnh viễn gồm 32 chiếc thay thế cho hệ răng sữa"},

    # PROC
    {"term": "xịt rửa mũi", "class": "[PROC]", "source_id": 226206, "context": "Xịt rửa mũi bằng nước muối sinh lý làm sạch hốc mũi"},
    {"term": "tiêm thuốc tránh thai", "class": "[PROC]", "source_id": 269702, "context": "tiêm thuốc tránh thai DMPA định kỳ mỗi 3 tháng một lần"},
    {"term": "xét nghiệm hiv ab", "class": "[PROC]", "source_id": 240435, "context": "Kết quả xét nghiệm HIV AB test nhanh tìm kháng thể kháng virus HIV"},
    {"term": "mổ đứt dây chằng", "class": "[PROC]", "source_id": 231929, "context": "phẫu thuật nội soi tái tạo dây chằng khớp gối mổ đứt dây chằng"},
    {"term": "test hp hơi thở c14", "class": "[PROC]", "source_id": 266364, "context": "Test HP hơi thở C14 là phương pháp chẩn đoán vi khuẩn HP dạ dày"},
    {"term": "test hp hơi thở", "class": "[PROC]", "source_id": 266364, "context": "nghiệm pháp test HP hơi thở kiểm tra men urease của vi khuẩn"},
    {"term": "chọc dò dịch não tủy", "class": "[PROC]", "source_id": 242642, "context": "chọc dò dịch não tủy qua khe đốt sống thắt lưng chẩn đoán lao màng não"},
    {"term": "vật lý trị liệu phục hồi chức năng", "class": "[PROC]", "source_id": 230709, "context": "tập vật lý trị liệu phục hồi chức năng vận động cho trẻ bại não co cứng"},
    {"term": "xoắn polyp cổ tử cung", "class": "[PROC]", "source_id": 259366, "context": "thủ thuật xoắn polyp cổ tử cung bấm cuống polyp tại phòng khám phụ khoa"},
]

if __name__ == "__main__":
    print(f"Group 6: Curated {len(items_deep)} deep clinical candidate terms.")
    append_curated_terms("vi", items_deep)
