"""expand_lexicon_data.py: Script tạo bộ lexicon_data.py đồ sộ mở rộng hàng trăm concepts.
"""

from __future__ import annotations

import json
from pathlib import Path

# Đọc lexicon_data.py hiện tại và bổ sung các danh mục phong phú
CURRENT_FILE = Path("/home/tran-nhat-truong/TranNhatTruong/other/AIGuru/sbtc/Scripts/Retrieval/lexicon_data.py")


EXTRA_DISEASES = [
    # Truyền nhiễm
    {"concept_id": "ICD_A00", "type": "disease", "labels": {"vi": "bệnh tả", "en": "cholera", "zh": "霍乱"}, "aliases": ["dịch tả", "tiêu chảy mất nước cấp", "vibrio cholerae", "霍乱弧菌感染"]},
    {"concept_id": "ICD_A01", "type": "disease", "labels": {"vi": "thương hàn", "en": "typhoid fever", "zh": "伤寒"}, "aliases": ["bệnh thương hàn", "sốt thương hàn", "salmonella typhi", "伤寒病"]},
    {"concept_id": "ICD_A09", "type": "disease", "labels": {"vi": "viêm dạ dày ruột nhiễm trùng", "en": "infectious gastroenteritis", "zh": "感染性胃肠炎"}, "aliases": ["nhiễm trùng đường ruột", "ngộ độc thực phẩm", "tiêu chảy nhiễm trùng", "gastroenteritis", "food poisoning", "急性胃肠炎", "食物中毒"]},
    {"concept_id": "ICD_A35", "type": "disease", "labels": {"vi": "uốn ván", "en": "tetanus", "zh": "破伤风"}, "aliases": ["bệnh uốn ván", "co giật uốn ván", "lockjaw", "clostridium tetani", "破伤风杆菌感染"]},
    {"concept_id": "ICD_B01", "type": "disease", "labels": {"vi": "thủy đậu", "en": "chickenpox", "zh": "水痘"}, "aliases": ["bệnh trái rạ", "thủy đậu bội nhiễm", "varicella", "varicella zoster virus", "水疱病"]},
    {"concept_id": "ICD_B02", "type": "disease", "labels": {"vi": "zona thần kinh", "en": "herpes zoster", "zh": "带状疱疹"}, "aliases": ["bệnh zona", "giời leo", "đau sau zona", "shingles", "postherpetic neuralgia", "缠腰火丹", "蛇胆疮"]},
    {"concept_id": "ICD_B05", "type": "disease", "labels": {"vi": "bệnh sởi", "en": "measles", "zh": "麻疹"}, "aliases": ["sởi ban", "phát ban sởi", "rubeola", "measles virus", "出麻疹"]},
    {"concept_id": "ICD_B26", "type": "disease", "labels": {"vi": "quai bị", "en": "mumps", "zh": "流行性腮腺炎"}, "aliases": ["bệnh quai bị", "viêm tuyến mang tai", "mumps parotitis", "腮腺炎", "痄腮"]},
    {"concept_id": "ICD_B08", "type": "disease", "labels": {"vi": "tay chân miệng", "en": "hand foot and mouth disease", "zh": "手足口病"}, "aliases": ["HFMD", "viêm loét miệng tay chân", "coxsackievirus a16", "enterovirus 71", "手足口综合征"]},
    {"concept_id": "ICD_B50", "type": "disease", "labels": {"vi": "sốt rét", "en": "malaria", "zh": "疟疾"}, "aliases": ["ngã nước", "sốt rét cơn", "sốt rét ác tính", "plasmodium falciparum", "打摆子", "恶性疟"]},
    {"concept_id": "ICD_G00", "type": "disease", "labels": {"vi": "viêm màng não", "en": "meningitis", "zh": "脑膜炎"}, "aliases": ["viêm màng não mủ", "cứng gáy", "nhiễm trùng màng não", "bacterial meningitis", "化脓性脑膜炎"]},

    # Mắt, Tai Mũi Họng
    {"concept_id": "ICD_H10", "type": "disease", "labels": {"vi": "viêm kết mạc", "en": "conjunctivitis", "zh": "结膜炎"}, "aliases": ["đau mắt đỏ", "đỏ mắt", "cộm mắt", "ghèn mắt", "pink eye", "red eye", "红眼病", "眼睛发炎"]},
    {"concept_id": "ICD_H25", "type": "disease", "labels": {"vi": "đục thủy tinh thể", "en": "cataract", "zh": "白内障"}, "aliases": ["cườm khô", "mờ mắt người già", "thay thủy tinh thể", "senile cataract", "老年性白内障"]},
    {"concept_id": "ICD_H40", "type": "disease", "labels": {"vi": "glaucoma", "en": "glaucoma", "zh": "青光眼"}, "aliases": ["cườm nước", "thiên đầu thống", "tăng nhãn áp", "đau nhức hốc mắt", "high intraocular pressure", "绿内障"]},
    {"concept_id": "ICD_H65", "type": "disease", "labels": {"vi": "viêm tai giữa", "en": "otitis media", "zh": "中耳炎"}, "aliases": ["chảy mủ tai", "đau nhức trong tai", "viêm tai giữa cấp", "ear infection", "tympanitis", "分泌性中耳炎"]},
    {"concept_id": "ICD_J01", "type": "disease", "labels": {"vi": "viêm xoang", "en": "sinusitis", "zh": "鼻窦炎"}, "aliases": ["viêm xoang mũi", "viêm xoang hàm", "ngạt mũi nhức trán", "sinus infection", "rhinosinusitis", "副鼻窦炎"]},
    {"concept_id": "ICD_J30", "type": "disease", "labels": {"vi": "viêm mũi dị ứng", "en": "allergic rhinitis", "zh": "过敏性鼻炎"}, "aliases": ["dị ứng thời tiết", "hắt hơi sổ mũi liên tục", "hay fever", "pollinosis", "花粉症", "过敏性鼻窦炎"]},

    # Tim mạch & Mạch máu
    {"concept_id": "ICD_I80", "type": "disease", "labels": {"vi": "huyết khối tĩnh mạch sâu", "en": "deep vein thrombosis", "zh": "深静脉血栓形成"}, "aliases": ["DVT", "cục máu đông tĩnh mạch", "sưng đau bắp chân", "deep venous thrombosis", "深静脉血栓"]},
    {"concept_id": "ICD_I83", "type": "disease", "labels": {"vi": "suy giãn tĩnh mạch", "en": "varicose veins", "zh": "下肢静脉曲张"}, "aliases": ["giãn tĩnh mạch chi dưới", "nổi gân xanh bắp chân", "nặng mỏi chân", "venous insufficiency", "静脉曲张"]},
    {"concept_id": "ICD_I26", "type": "disease", "labels": {"vi": "thuyên tắc phổi", "en": "pulmonary embolism", "zh": "肺栓塞"}, "aliases": ["PE", "nghẽn mạch phổi", "đau ngực khó thở đột ngột", "pulmonary thromboembolism", "肺动脉栓塞"]},

    # Tiêu hóa
    {"concept_id": "ICD_K50", "type": "disease", "labels": {"vi": "bệnh crohn", "en": "Crohn's disease", "zh": "克罗恩病"}, "aliases": ["viêm ruột u hạt", "viêm ruột mạn tính", "regional enteritis", "局限性回肠炎"]},
    {"concept_id": "ICD_K51", "type": "disease", "labels": {"vi": "viêm loét đại tràng", "en": "ulcerative colitis", "zh": "溃疡性结肠炎"}, "aliases": ["UC", "viêm loét đại trực tràng chảy máu", "đi ngoài ra máu nhầy", "colitis", "溃结"]},
    {"concept_id": "ICD_K64", "type": "disease", "labels": {"vi": "bệnh trĩ", "en": "hemorrhoids", "zh": "痔疮"}, "aliases": ["trĩ nội", "trĩ ngoại", "lòi dom", "chảy máu hậu môn khi đi cầu", "piles", "hemorrhoidal disease", "内痔", "外痔", "混合痔"]},
    {"concept_id": "ICD_K81", "type": "disease", "labels": {"vi": "viêm túi mật", "en": "cholecystitis", "zh": "胆囊炎"}, "aliases": ["đau hạ sườn phải", "viêm túi mật do sỏi", "acute cholecystitis", "急性胆囊炎", "慢性胆囊炎"]},

    # Thận - Tiết niệu
    {"concept_id": "ICD_N04", "type": "disease", "labels": {"vi": "hội chứng thận hư", "en": "nephrotic syndrome", "zh": "肾病综合征"}, "aliases": ["thận nhiễm mỡ", "tiểu đạm nhiều", "phù toàn thân", "proteinuria syndrome", "小儿肾病综合征"]},
    {"concept_id": "ICD_N00", "type": "disease", "labels": {"vi": "viêm cầu thận", "en": "glomerulonephritis", "zh": "肾小球肾炎"}, "aliases": ["viêm cầu thận cấp", "tiểu máu phù mặt", "acute glomerulonephritis", "AGN", "急性肾炎", "慢性肾炎"]},
    {"concept_id": "ICD_N34", "type": "disease", "labels": {"vi": "viêm niệu đạo", "en": "urethritis", "zh": "尿道炎"}, "aliases": ["tiểu buốt rát đường tiểu", "nhiễm trùng niệu đạo", "urethral inflammation", "非淋菌性尿道炎"]},
    {"concept_id": "ICD_N41", "type": "disease", "labels": {"vi": "viêm tuyến tiền liệt", "en": "prostatitis", "zh": "前列腺炎"}, "aliases": ["đau tức vùng đáy chậu", "tiểu đêm buốt rắt", "chronic prostatitis", "慢性前列腺炎"]},

    # Cơ xương khớp
    {"concept_id": "ICD_M45", "type": "disease", "labels": {"vi": "viêm cột sống dính khớp", "en": "ankylosing spondylitis", "zh": "强直性脊柱炎"}, "aliases": ["AS", "dính khớp cột sống", "cột sống tre", "bamboo spine", "强脊炎"]},
    {"concept_id": "ICD_M47", "type": "disease", "labels": {"vi": "thoái hóa cột sống", "en": "spondylosis", "zh": "脊柱退行性病变"}, "aliases": ["vôi hóa cột sống", "gai cột sống", "thoái hóa đốt sống cổ", "thoái hóa thắt lưng", "spinal osteoarthritis", "骨刺", "颈椎退行性变"]},
    {"concept_id": "ICD_M65", "type": "disease", "labels": {"vi": "viêm gân", "en": "tendinitis", "zh": "肌腱炎"}, "aliases": ["viêm bao gân", "viêm điểm bám gân", "đau nhức cơ bắp", "tendonitis", "tenosynovitis", "腱鞘炎"]},
    {"concept_id": "ICD_G56", "type": "disease", "labels": {"vi": "hội chứng ống cổ tay", "en": "carpal tunnel syndrome", "zh": "腕管综合征"}, "aliases": ["CTS", "tê đầu ngón tay", "chèn ép thần kinh giữa", "median nerve entrapment", "腕管狭窄"]},

    # Da liễu
    {"concept_id": "ICD_L23", "type": "disease", "labels": {"vi": "viêm da tiếp xúc", "en": "contact dermatitis", "zh": "接触性皮炎"}, "aliases": ["dị ứng mỹ phẩm", "dị ứng hóa chất", "ngứa rát đỏ da", "allergic contact dermatitis", "变应性接触性皮炎"]},

    # Ung bướu
    {"concept_id": "ICD_C18", "type": "disease", "labels": {"vi": "ung thư đại trực tràng", "en": "colorectal cancer", "zh": "结直肠癌"}, "aliases": ["K đại tràng", "K trực tràng", "ung thư ruột già", "CRC", "colon cancer", "rectal cancer", "大肠癌", "直肠癌"]},
    {"concept_id": "ICD_C53", "type": "disease", "labels": {"vi": "ung thư cổ tử cung", "en": "cervical cancer", "zh": "宫颈癌"}, "aliases": ["K cổ tử cung", "nhiễm virus HPV", "carcinoma cổ tử cung", "HPV cancer", "子宫颈癌"]},
    {"concept_id": "ICD_C61", "type": "disease", "labels": {"vi": "ung thư tiền liệt tuyến", "en": "prostate cancer", "zh": "前列腺癌"}, "aliases": ["K tuyến tiền liệt", "ung thư nhiếp hộ tuyến", "prostatic carcinoma", "前列腺恶性肿瘤"]},
    {"concept_id": "ICD_C73", "type": "disease", "labels": {"vi": "ung thư tuyến giáp", "en": "thyroid cancer", "zh": "甲状腺癌"}, "aliases": ["K giáp", "u giáp ác tính", "ung thư giáp nhú", "thyroid carcinoma", "甲状腺恶性肿瘤"]},
    {"concept_id": "ICD_C91", "type": "disease", "labels": {"vi": "ung thư máu", "en": "leukemia", "zh": "白血病"}, "aliases": ["bệnh bạch cầu", "bạch cầu cấp", "máu trắng", "leukaemia", "血癌", "急性白血病"]},
    {"concept_id": "ICD_C81", "type": "disease", "labels": {"vi": "u lympho", "en": "lymphoma", "zh": "淋巴瘤"}, "aliases": ["ung thư hạch", "ung thư hạch bạch huyết", "Hodgkin", "non-Hodgkin lymphoma", "淋巴肉瘤"]},
    {"concept_id": "ICD_C11", "type": "disease", "labels": {"vi": "ung thư vòm họng", "en": "nasopharyngeal carcinoma", "zh": "鼻咽癌"}, "aliases": ["K vòm", "ung thư biểu mô mũi họng", "NPC", "nasopharynx cancer", "鼻咽恶性肿瘤"]},
]

EXTRA_DRUGS = [
    # Kháng sinh bổ sung
    {"concept_id": "DRUG_CEFTRIAXONE", "type": "drug", "labels": {"vi": "ceftriaxone", "en": "ceftriaxone", "zh": "头孢曲松"}, "aliases": ["rocephin", "kháng sinh tiêm cephalosporin thế hệ 3", "头孢曲松钠"]},
    {"concept_id": "DRUG_LEVOFLOXACIN", "type": "drug", "labels": {"vi": "levofloxacin", "en": "levofloxacin", "zh": "左氧氟沙星"}, "aliases": ["cravit", "kháng sinh phổ rộng hô hấp", "quinolone thế hệ 3", "盐酸左氧氟沙星"]},
    {"concept_id": "DRUG_DOXYCYCLINE", "type": "drug", "labels": {"vi": "doxycycline", "en": "doxycycline", "zh": "多西环素"}, "aliases": ["tetracycline", "kháng sinh trị mụn", "kháng sinh trị sốt mò", "盐酸多西环素"]},
    {"concept_id": "DRUG_METRONIDAZOLE", "type": "drug", "labels": {"vi": "metronidazole", "en": "metronidazole", "zh": "甲硝唑"}, "aliases": ["klion", "flagyl", "thuốc trị vi khuẩn kỵ khí", "thuốc trị ký sinh trùng", "甲硝唑片"]},
    {"concept_id": "DRUG_CLARITHROMYCIN", "type": "drug", "labels": {"vi": "clarithromycin", "en": "clarithromycin", "zh": "克拉霉素"}, "aliases": ["klacid", "thuốc diệt vi khuẩn HP dạ dày", "macrolide", "克拉霉素胶囊"]},

    # Kháng virus & Nấm
    {"concept_id": "DRUG_ACYCLOVIR", "type": "drug", "labels": {"vi": "acyclovir", "en": "acyclovir", "zh": "阿昔洛韦"}, "aliases": ["zovirax", "thuốc trị zona", "thuốc bôi thủy đậu", "thuốc trị herpes", "阿昔洛韦乳膏"]},
    {"concept_id": "DRUG_OSELTAMIVIR", "type": "drug", "labels": {"vi": "oseltamivir", "en": "oseltamivir", "zh": "奥司他韦"}, "aliases": ["tamiflu", "thuốc đặc trị cúm a", "thuốc kháng virus cúm", "磷酸奥司他韦"]},
    {"concept_id": "DRUG_FLUCONAZOLE", "type": "drug", "labels": {"vi": "fluconazole", "en": "fluconazole", "zh": "氟康唑"}, "aliases": ["diflucan", "thuốc kháng nấm", "thuốc trị nấm candida", "氟康唑胶囊"]},

    # Tim mạch & Huyết áp
    {"concept_id": "DRUG_BISOPROLOL", "type": "drug", "labels": {"vi": "bisoprolol", "en": "bisoprolol", "zh": "比索洛尔"}, "aliases": ["concor", "thuốc chẹn beta", "thuốc hạ nhịp tim", "hạ áp chẹn beta", "富马酸比索洛尔"]},
    {"concept_id": "DRUG_PERINDOPRIL", "type": "drug", "labels": {"vi": "perindopril", "en": "perindopril", "zh": "培哚普利"}, "aliases": ["coversyl", "thuốc ức chế men chuyển tim mạch", "培哚普利叔丁胺片"]},
    {"concept_id": "DRUG_TELMISARTAN", "type": "drug", "labels": {"vi": "telmisartan", "en": "telmisartan", "zh": "替米沙坦"}, "aliases": ["micardis", "chẹn thụ thể angiotensin", "替米沙坦片"]},
    {"concept_id": "DRUG_ROSUVASTATIN", "type": "drug", "labels": {"vi": "rosuvastatin", "en": "rosuvastatin", "zh": "瑞舒伐他汀"}, "aliases": ["crestor", "thuốc giảm mỡ máu liều cao", "statin thế hệ mới", "瑞舒伐他汀钙片"]},
    {"concept_id": "DRUG_CLOPIDOGREL", "type": "drug", "labels": {"vi": "clopidogrel", "en": "clopidogrel", "zh": "氯吡格雷"}, "aliases": ["plavix", "thuốc chống ngưng tập tiểu cầu", "ngừa tái phát đột quỵ", "硫酸氢氯吡格雷片"]},
    {"concept_id": "DRUG_FUROSEMIDE", "type": "drug", "labels": {"vi": "furosemide", "en": "furosemide", "zh": "呋塞米"}, "aliases": ["lasix", "thuốc lợi tiểu quai", "lợi tiểu hạ áp", "thuốc giảm phù", "速尿"]},

    # Tiêu hóa & Dạ dày
    {"concept_id": "DRUG_PANTOPRAZOLE", "type": "drug", "labels": {"vi": "pantoprazole", "en": "pantoprazole", "zh": "泮托拉唑"}, "aliases": ["pantoloc", "thuốc dạ dày pantoprazole", "ức chế bơm proton", "泮托拉唑钠"]},
    {"concept_id": "DRUG_DOMPERIDONE", "type": "drug", "labels": {"vi": "domperidone", "en": "domperidone", "zh": "多潘立酮"}, "aliases": ["motilium", "motilium-m", "thuốc chống nôn", "thuốc trị chướng bụng đầy hơi", "吗丁啉"]},
    {"concept_id": "DRUG_PHOSPHALUGEL", "type": "drug", "labels": {"vi": "aluminium phosphate", "en": "aluminium phosphate gel", "zh": "磷酸铝凝胶"}, "aliases": ["phosphalugel", "thuốc chữ p", "gel sữa dạ dày", "thuốc tráng dạ dày", "洁维乐"]},
    {"concept_id": "DRUG_SMECTA", "type": "drug", "labels": {"vi": "diosmectite", "en": "diosmectite", "zh": "蒙脱石散"}, "aliases": ["smecta", "thuốc cầm tiêu chảy", "thuốc trị tiêu chảy smecta", "思密达"]},
    {"concept_id": "DRUG_ORESOL", "type": "drug", "labels": {"vi": "oresol", "en": "oral rehydration salts", "zh": "口服补液盐"}, "aliases": ["ors", "bù nước điện giải", "dung dịch oresol", "口服补液盐散"]},

    # Hô hấp & Dị ứng
    {"concept_id": "DRUG_SALBUTAMOL", "type": "drug", "labels": {"vi": "salbutamol", "en": "salbutamol", "zh": "沙丁胺醇"}, "aliases": ["ventolin", "albuterol", "thuốc xịt hen suyễn", "thuốc giãn phế quản cấp", "硫酸沙丁胺醇吸入气雾剂"]},
    {"concept_id": "DRUG_ACETYLCYSTEINE", "type": "drug", "labels": {"vi": "acetylcysteine", "en": "acetylcysteine", "zh": "乙酰半胱氨酸"}, "aliases": ["nac", "thuốc tiêu đờm", "thuốc long đờm", "giảm ho đờm", "富露施"]},
    {"concept_id": "DRUG_FEXOFENADINE", "type": "drug", "labels": {"vi": "fexofenadine", "en": "fexofenadine", "zh": "非索非那定"}, "aliases": ["telfast", "thuốc chống dị ứng thế hệ mới", "không gây buồn ngủ", "盐酸非索非那定片"]},
    {"concept_id": "DRUG_CETIRIZINE", "type": "drug", "labels": {"vi": "cetirizine", "en": "cetirizine", "zh": "西替利嗪"}, "aliases": ["zyrtec", "thuốc dị ứng mề đay", "kháng histamin h1", "盐酸西替利嗪片"]},
]

EXTRA_TCM = [
    # Thảo dược thanh nhiệt, hóa đờm, hành khí
    {"concept_id": "TCM_SHIGAO", "type": "tcm_herb", "labels": {"vi": "thạch cao", "en": "gypsum", "zh": "石膏"}, "aliases": ["thanh nhiệt giáng hỏa", "sinh thạch cao", "Gypsum Fibrosum"]},
    {"concept_id": "TCM_ZHIMU", "type": "tcm_herb", "labels": {"vi": "tri mẫu", "en": "anemarrhena rhizome", "zh": "知母"}, "aliases": ["tư âm giáng hỏa", "Rhizoma Anemarrhenae"]},
    {"concept_id": "TCM_ZHIZI", "type": "tcm_herb", "labels": {"vi": "chi tử", "en": "gardenia fruit", "zh": "栀子"}, "aliases": ["dành dành", "thanh nhiệt trừ phiền", "Fructus Gardeniae"]},
    {"concept_id": "TCM_HUANGQIN", "type": "tcm_herb", "labels": {"vi": "hoàng cầm", "en": "scutellaria baicalensis", "zh": "黄芩"}, "aliases": ["thanh nhiệt phế kinh", "Radix Scutellariae"]},
    {"concept_id": "TCM_HUANGBAI", "type": "tcm_herb", "labels": {"vi": "hoàng bá", "en": "phellodendron bark", "zh": "黄柏"}, "aliases": ["thanh nhiệt táo thấp hạ tiêu", "Cortex Phellodendri"]},
    {"concept_id": "TCM_YUXINGCAO", "type": "tcm_herb", "labels": {"vi": "ngư tinh thảo", "en": "houttuynia cordata", "zh": "鱼腥草"}, "aliases": ["rau diếp cá", "thanh nhiệt giải độc phế", "Herba Houttuyniae"]},
    {"concept_id": "TCM_FUTZI", "type": "tcm_herb", "labels": {"vi": "phụ tử", "en": "aconite root", "zh": "附子"}, "aliases": ["hắc phụ", "bạch phụ", "hồi dương cứu nghịch", "Radix Aconiti Lateralis"]},
    {"concept_id": "TCM_GANJIANG", "type": "tcm_herb", "labels": {"vi": "can khương", "en": "dried ginger", "zh": "干姜"}, "aliases": ["gừng khô", "ôn trung tán hàn", "Rhizoma Zingiberis"]},
    {"concept_id": "TCM_ROUGUI", "type": "tcm_herb", "labels": {"vi": "nhục quế", "en": "cinnamon bark", "zh": "肉桂"}, "aliases": ["quế thanh", "bổ hỏa trợ dương", "Cortex Cinnamomi"]},
    {"concept_id": "TCM_FANGFENG", "type": "tcm_herb", "labels": {"vi": "phòng phong", "en": "saposhnikovia root", "zh": "防风"}, "aliases": ["trừ phong thắng thấp", "Radix Saposhnikoviae"]},
    {"concept_id": "TCM_DUHUO", "type": "tcm_herb", "labels": {"vi": "độc hoạt", "en": "angelica pubescens", "zh": "独活"}, "aliases": ["khu phong trừ thấp hạ tiêu", "Radix Angelicae Pubescentis"]},
    {"concept_id": "TCM_BANXIA", "type": "tcm_herb", "labels": {"vi": "bán hạ", "en": "pinellia rhizome", "zh": "半夏"}, "aliases": ["chế bán hạ", "táo thấp hóa đờm giáng nghịch", "Rhizoma Pinelliae"]},
    {"concept_id": "TCM_CHENPI", "type": "tcm_herb", "labels": {"vi": "trần bì", "en": "tangerine peel", "zh": "陈皮"}, "aliases": ["vỏ quýt lâu năm", "lý khí kiện tỳ", "Pericarpium Citri Reticulatae"]},
    {"concept_id": "TCM_JIEGENG", "type": "tcm_herb", "labels": {"vi": "cát cánh", "en": "platycodon root", "zh": "桔梗"}, "aliases": ["khai tuyên phế khí", "chỉ khái bài nùng", "Radix Platycodonis"]},
    {"concept_id": "TCM_XINGREN", "type": "tcm_herb", "labels": {"vi": "hạnh nhân", "en": "apricot kernel", "zh": "杏仁"}, "aliases": ["khổ hạnh nhân", "chỉ khái bình suyễn", "Semen Armeniacae Amarum"]},
    {"concept_id": "TCM_BAISHAO", "type": "tcm_herb", "labels": {"vi": "bạch thược", "en": "white peony root", "zh": "白芍"}, "aliases": ["dưỡng huyết nhu can chỉ thống", "Radix Paeoniae Alba"]},
    {"concept_id": "TCM_GOUQIZI", "type": "tcm_herb", "labels": {"vi": "kỷ tử", "en": "goji berry", "zh": "枸杞子"}, "aliases": ["câu kỷ tử", "bổ can thận sáng mắt", "Fructus Lycii", "枸杞"]},
    {"concept_id": "TCM_DUZHONG", "type": "tcm_herb", "labels": {"vi": "đỗ trọng", "en": "eucommia bark", "zh": "杜仲"}, "aliases": ["bổ can thận mạnh gân cốt", "Cortex Eucommiae"]},

    # Bài thuốc danh phương bổ sung
    {"concept_id": "TCM_XIAOCHAIHU", "type": "tcm_formula", "labels": {"vi": "tiểu sài hồ thang", "en": "xiaochaihu decoction", "zh": "小柴胡汤"}, "aliases": ["hòa giải thiếu dương", "xiao chai hu tang", "小柴胡颗粒"]},
    {"concept_id": "TCM_DACHAIHU", "type": "tcm_formula", "labels": {"vi": "đại sài hồ thang", "en": "dachaihu decoction", "zh": "大柴胡汤"}, "aliases": ["hòa giải thiếu dương thông phủ", "da chai hu tang"]},
    {"concept_id": "TCM_BAIHUTANG", "type": "tcm_formula", "labels": {"vi": "bạch hổ thang", "en": "baihu decoction", "zh": "白虎汤"}, "aliases": ["thanh nhiệt dương minh", "bai hu tang"]},
    {"concept_id": "TCM_LONGDAN", "type": "tcm_formula", "labels": {"vi": "long đởm tả can thang", "en": "longdan xiegan decoction", "zh": "龙胆泻肝汤"}, "aliases": ["tả can đởm thực hỏa", "thanh hạ tiêu thấp nhiệt", "龙胆泻肝丸"]},
    {"concept_id": "TCM_BANXIAXIE", "type": "tcm_formula", "labels": {"vi": "bán hạ tả tâm thang", "en": "banxia xiexin decoction", "zh": "半夏泻心汤"}, "aliases": ["hàn nhiệt thác tạp", "tiêu bĩ tán kết", "ban xia xie xin tang"]},
    {"concept_id": "TCM_YINQIAO", "type": "tcm_formula", "labels": {"vi": "ngân kiều tán", "en": "yinqiao powder", "zh": "银翘散"}, "aliases": ["tân lương giải biểu", "trị cảm sốt phong nhiệt", "yin qiao san", "银翘解毒片"]},
    {"concept_id": "TCM_MAHUANGTANG", "type": "tcm_formula", "labels": {"vi": "ma hoàng thang", "en": "mahuang decoction", "zh": "麻黄汤"}, "aliases": ["phát hãn giải biểu tuyên phế bình suyễn", "ma huang tang"]},
    {"concept_id": "TCM_GUIZHITANG", "type": "tcm_formula", "labels": {"vi": "quế chi thang", "en": "guizhi decoction", "zh": "桂枝汤"}, "aliases": ["giải cơ thoái nhiệt điều hòa vinh vệ", "gui zhi tang"]},
    {"concept_id": "TCM_BAOHUAWAN", "type": "tcm_formula", "labels": {"vi": "bảo hòa hoàn", "en": "baohe pills", "zh": "保和丸"}, "aliases": ["tiêu thực hóa trệ hòa vị", "thuốc trị ăn không tiêu đông y", "bao he wan"]},
]

EXTRA_COLLOQUIAL = [
    {"concept_id": "SYMP_PALPITATION", "type": "symptom", "labels": {"vi": "hồi hộp tim đập nhanh", "en": "palpitations", "zh": "心悸"}, "aliases": ["tim đập thình thịch", "đánh trống ngực", "hồi hộp", "loạn nhịp", "heart racing", "heart pounding", "心慌", "心跳过快"]},
    {"concept_id": "SYMP_NUMBNESS", "type": "symptom", "labels": {"vi": "tê bì chân tay", "en": "numbness and tingling", "zh": "手脚发麻"}, "aliases": ["tê rần", "châm chích như kiến bò", "tê buốt", "mất cảm giác", "pins and needles", "paresthesia", "肢体麻木", "发麻"]},
    {"concept_id": "SYMP_COLD_EXTREMITIES", "type": "symptom", "labels": {"vi": "chân tay lạnh", "en": "cold extremities", "zh": "手脚冰凉"}, "aliases": ["lạnh buốt tay chân", "sợ lạnh", "chân tay giá lạnh", "cold hands and feet", "畏寒肢冷", "手足不温"]},
    {"concept_id": "SYMP_NIGHT_SWEATS", "type": "symptom", "labels": {"vi": "đổ mồ hôi trộm", "en": "night sweats", "zh": "盗汗"}, "aliases": ["toát mồ hôi đêm", "vã mồ hôi", "vã mồ hôi hột", "nocturnal sweating", "夜间出汗", "自汗盗汗"]},
    {"concept_id": "SYMP_HOARSENESS", "type": "symptom", "labels": {"vi": "khản tiếng", "en": "hoarseness", "zh": "声音嘶哑"}, "aliases": ["mất tiếng", "khàn giọng", "nói không ra hơi", "husky voice", "dysphonia", "喉咙嘶哑", "失音"]},
    {"concept_id": "SYMP_SORE_THROAT_DRY", "type": "symptom", "labels": {"vi": "khô họng ngứa cổ", "en": "dry and itchy throat", "zh": "喉咙干痒"}, "aliases": ["vướng đờm ở cổ", "rát họng ngứa cổ", "nuốt nghẹn", "đắng miệng", "dry throat", "scratchy throat", "咽干", "咽部异物感"]},
    {"concept_id": "SYMP_EDEMA", "type": "symptom", "labels": {"vi": "phù chân", "en": "peripheral edema", "zh": "下肢水肿"}, "aliases": ["sưng phù mắt cá", "phù thũng", "ấn lõm mắt cá chân", "swollen ankles", "leg swelling", "腿肿", "脚踝浮肿"]},
    {"concept_id": "SYMP_WEIGHT_LOSS", "type": "symptom", "labels": {"vi": "sụt cân", "en": "unintentional weight loss", "zh": "体重下降"}, "aliases": ["sút cân nhanh", "gầy sút", "sụt ký bất thường", "unexplained weight loss", "消瘦", "短时间内消瘦"]},
]


def expand() -> None:
    # Đọc nội dung hiện tại
    with open(CURRENT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Bổ sung vào các danh sách tương ứng
    # 1. Bổ sung EXTRA_DISEASES
    dis_str = ",\n".join("    " + json.dumps(item, ensure_ascii=False) for item in EXTRA_DISEASES)
    content = content.replace("DISEASE_CONCEPTS: List[Dict[str, Any]] = [", f"DISEASE_CONCEPTS: List[Dict[str, Any]] = [\n{dis_str},")

    # 2. Bổ sung EXTRA_DRUGS
    drug_str = ",\n".join("    " + json.dumps(item, ensure_ascii=False) for item in EXTRA_DRUGS)
    content = content.replace("DRUG_CONCEPTS: List[Dict[str, Any]] = [", f"DRUG_CONCEPTS: List[Dict[str, Any]] = [\n{drug_str},")

    # 3. Bổ sung EXTRA_TCM
    tcm_str = ",\n".join("    " + json.dumps(item, ensure_ascii=False) for item in EXTRA_TCM)
    content = content.replace("TCM_CONCEPTS: List[Dict[str, Any]] = [", f"TCM_CONCEPTS: List[Dict[str, Any]] = [\n{tcm_str},")

    # 4. Bổ sung EXTRA_COLLOQUIAL
    col_str = ",\n".join("    " + json.dumps(item, ensure_ascii=False) for item in EXTRA_COLLOQUIAL)
    content = content.replace("COLLOQUIAL_CONCEPTS: List[Dict[str, Any]] = [", f"COLLOQUIAL_CONCEPTS: List[Dict[str, Any]] = [\n{col_str},")

    with open(CURRENT_FILE, "w", encoding="utf-8") as f:
        f.write(content)

    print("Mở rộng lexicon_data.py hoàn tất thành công!")


if __name__ == "__main__":
    expand()
