"""lexicon_data.py: Bộ Dữ Liệu Khung Chuẩn Hóa Y Khoa Đa Ngữ (VI - EN - ZH).

Chứa hàng trăm concepts cốt lõi bao phủ 5 miền:
1. ICD-10 Diseases & Syndromes (22 chương mã bệnh quốc tế).
2. Pharmacology & Essential Drugs (Thuốc, hoạt chất, biệt dược, nhóm dược lý).
3. Traditional Chinese Medicine (TCM Đông Y: Vị thuốc Bắc & Bài thuốc cổ phương).
4. Patient Lay Language & Colloquial Symptoms (Khẩu ngữ người bệnh, mô tả đau & triệu chứng).
5. Laboratory Tests & Diagnostic Procedures (Xét nghiệm, chẩn đoán hình ảnh & chỉ số sinh hóa).
"""

from __future__ import annotations

from typing import Any, Dict, List

# ==============================================================================
# 1. BỆNH HỌC & HỘI CHỨNG (ICD-10 DISEASES & SYNDROMES)
# ==============================================================================
DISEASE_CONCEPTS: List[Dict[str, Any]] = [
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
    {"concept_id": "ICD_H10", "type": "disease", "labels": {"vi": "viêm kết mạc", "en": "conjunctivitis", "zh": "结膜炎"}, "aliases": ["đau mắt đỏ", "đỏ mắt", "cộm mắt", "ghèn mắt", "pink eye", "red eye", "红眼病", "眼睛发炎"]},
    {"concept_id": "ICD_H25", "type": "disease", "labels": {"vi": "đục thủy tinh thể", "en": "cataract", "zh": "白内障"}, "aliases": ["cườm khô", "mờ mắt người già", "thay thủy tinh thể", "senile cataract", "老年性白内障"]},
    {"concept_id": "ICD_H40", "type": "disease", "labels": {"vi": "glaucoma", "en": "glaucoma", "zh": "青光眼"}, "aliases": ["cườm nước", "thiên đầu thống", "tăng nhãn áp", "đau nhức hốc mắt", "high intraocular pressure", "绿内障"]},
    {"concept_id": "ICD_H65", "type": "disease", "labels": {"vi": "viêm tai giữa", "en": "otitis media", "zh": "中耳炎"}, "aliases": ["chảy mủ tai", "đau nhức trong tai", "viêm tai giữa cấp", "ear infection", "tympanitis", "分泌性中耳炎"]},
    {"concept_id": "ICD_J01", "type": "disease", "labels": {"vi": "viêm xoang", "en": "sinusitis", "zh": "鼻窦炎"}, "aliases": ["viêm xoang mũi", "viêm xoang hàm", "ngạt mũi nhức trán", "sinus infection", "rhinosinusitis", "副鼻窦炎"]},
    {"concept_id": "ICD_J30", "type": "disease", "labels": {"vi": "viêm mũi dị ứng", "en": "allergic rhinitis", "zh": "过敏性鼻炎"}, "aliases": ["dị ứng thời tiết", "hắt hơi sổ mũi liên tục", "hay fever", "pollinosis", "花粉症", "过敏性鼻窦炎"]},
    {"concept_id": "ICD_I80", "type": "disease", "labels": {"vi": "huyết khối tĩnh mạch sâu", "en": "deep vein thrombosis", "zh": "深静脉血栓形成"}, "aliases": ["DVT", "cục máu đông tĩnh mạch", "sưng đau bắp chân", "deep venous thrombosis", "深静脉血栓"]},
    {"concept_id": "ICD_I83", "type": "disease", "labels": {"vi": "suy giãn tĩnh mạch", "en": "varicose veins", "zh": "下肢静脉曲张"}, "aliases": ["giãn tĩnh mạch chi dưới", "nổi gân xanh bắp chân", "nặng mỏi chân", "venous insufficiency", "静脉曲张"]},
    {"concept_id": "ICD_I26", "type": "disease", "labels": {"vi": "thuyên tắc phổi", "en": "pulmonary embolism", "zh": "肺栓塞"}, "aliases": ["PE", "nghẽn mạch phổi", "đau ngực khó thở đột ngột", "pulmonary thromboembolism", "肺动脉栓塞"]},
    {"concept_id": "ICD_K50", "type": "disease", "labels": {"vi": "bệnh crohn", "en": "Crohn's disease", "zh": "克罗恩病"}, "aliases": ["viêm ruột u hạt", "viêm ruột mạn tính", "regional enteritis", "局限性回肠炎"]},
    {"concept_id": "ICD_K51", "type": "disease", "labels": {"vi": "viêm loét đại tràng", "en": "ulcerative colitis", "zh": "溃疡性结肠炎"}, "aliases": ["UC", "viêm loét đại trực tràng chảy máu", "đi ngoài ra máu nhầy", "colitis", "溃结"]},
    {"concept_id": "ICD_K64", "type": "disease", "labels": {"vi": "bệnh trĩ", "en": "hemorrhoids", "zh": "痔疮"}, "aliases": ["trĩ nội", "trĩ ngoại", "lòi dom", "chảy máu hậu môn khi đi cầu", "piles", "hemorrhoidal disease", "内痔", "外痔", "混合痔"]},
    {"concept_id": "ICD_K81", "type": "disease", "labels": {"vi": "viêm túi mật", "en": "cholecystitis", "zh": "胆囊炎"}, "aliases": ["đau hạ sườn phải", "viêm túi mật do sỏi", "acute cholecystitis", "急性胆囊炎", "慢性胆囊炎"]},
    {"concept_id": "ICD_N04", "type": "disease", "labels": {"vi": "hội chứng thận hư", "en": "nephrotic syndrome", "zh": "肾病综合征"}, "aliases": ["thận nhiễm mỡ", "tiểu đạm nhiều", "phù toàn thân", "proteinuria syndrome", "小儿肾病综合征"]},
    {"concept_id": "ICD_N00", "type": "disease", "labels": {"vi": "viêm cầu thận", "en": "glomerulonephritis", "zh": "肾小球肾炎"}, "aliases": ["viêm cầu thận cấp", "tiểu máu phù mặt", "acute glomerulonephritis", "AGN", "急性肾炎", "慢性肾炎"]},
    {"concept_id": "ICD_N34", "type": "disease", "labels": {"vi": "viêm niệu đạo", "en": "urethritis", "zh": "尿道炎"}, "aliases": ["tiểu buốt rát đường tiểu", "nhiễm trùng niệu đạo", "urethral inflammation", "非淋菌性尿道炎"]},
    {"concept_id": "ICD_N41", "type": "disease", "labels": {"vi": "viêm tuyến tiền liệt", "en": "prostatitis", "zh": "前列腺炎"}, "aliases": ["đau tức vùng đáy chậu", "tiểu đêm buốt rắt", "chronic prostatitis", "慢性前列腺炎"]},
    {"concept_id": "ICD_M45", "type": "disease", "labels": {"vi": "viêm cột sống dính khớp", "en": "ankylosing spondylitis", "zh": "强直性脊柱炎"}, "aliases": ["AS", "dính khớp cột sống", "cột sống tre", "bamboo spine", "强脊炎"]},
    {"concept_id": "ICD_M47", "type": "disease", "labels": {"vi": "thoái hóa cột sống", "en": "spondylosis", "zh": "脊柱退行性病变"}, "aliases": ["vôi hóa cột sống", "gai cột sống", "thoái hóa đốt sống cổ", "thoái hóa thắt lưng", "spinal osteoarthritis", "骨刺", "颈椎退行性变"]},
    {"concept_id": "ICD_M65", "type": "disease", "labels": {"vi": "viêm gân", "en": "tendinitis", "zh": "肌腱炎"}, "aliases": ["viêm bao gân", "viêm điểm bám gân", "đau nhức cơ bắp", "tendonitis", "tenosynovitis", "腱鞘炎"]},
    {"concept_id": "ICD_G56", "type": "disease", "labels": {"vi": "hội chứng ống cổ tay", "en": "carpal tunnel syndrome", "zh": "腕管综合征"}, "aliases": ["CTS", "tê đầu ngón tay", "chèn ép thần kinh giữa", "median nerve entrapment", "腕管狭窄"]},
    {"concept_id": "ICD_L23", "type": "disease", "labels": {"vi": "viêm da tiếp xúc", "en": "contact dermatitis", "zh": "接触性皮炎"}, "aliases": ["dị ứng mỹ phẩm", "dị ứng hóa chất", "ngứa rát đỏ da", "allergic contact dermatitis", "变应性接触性皮炎"]},
    {"concept_id": "ICD_C18", "type": "disease", "labels": {"vi": "ung thư đại trực tràng", "en": "colorectal cancer", "zh": "结直肠癌"}, "aliases": ["K đại tràng", "K trực tràng", "ung thư ruột già", "CRC", "colon cancer", "rectal cancer", "大肠癌", "直肠癌"]},
    {"concept_id": "ICD_C53", "type": "disease", "labels": {"vi": "ung thư cổ tử cung", "en": "cervical cancer", "zh": "宫颈癌"}, "aliases": ["K cổ tử cung", "nhiễm virus HPV", "carcinoma cổ tử cung", "HPV cancer", "子宫颈癌"]},
    {"concept_id": "ICD_C61", "type": "disease", "labels": {"vi": "ung thư tiền liệt tuyến", "en": "prostate cancer", "zh": "前列腺癌"}, "aliases": ["K tuyến tiền liệt", "ung thư nhiếp hộ tuyến", "prostatic carcinoma", "前列腺恶性肿瘤"]},
    {"concept_id": "ICD_C73", "type": "disease", "labels": {"vi": "ung thư tuyến giáp", "en": "thyroid cancer", "zh": "甲状腺癌"}, "aliases": ["K giáp", "u giáp ác tính", "ung thư giáp nhú", "thyroid carcinoma", "甲状腺恶性肿瘤"]},
    {"concept_id": "ICD_C91", "type": "disease", "labels": {"vi": "ung thư máu", "en": "leukemia", "zh": "白血病"}, "aliases": ["bệnh bạch cầu", "bạch cầu cấp", "máu trắng", "leukaemia", "血癌", "急性白血病"]},
    {"concept_id": "ICD_C81", "type": "disease", "labels": {"vi": "u lympho", "en": "lymphoma", "zh": "淋巴瘤"}, "aliases": ["ung thư hạch", "ung thư hạch bạch huyết", "Hodgkin", "non-Hodgkin lymphoma", "淋巴肉瘤"]},
    {"concept_id": "ICD_C11", "type": "disease", "labels": {"vi": "ung thư vòm họng", "en": "nasopharyngeal carcinoma", "zh": "鼻咽癌"}, "aliases": ["K vòm", "ung thư biểu mô mũi họng", "NPC", "nasopharynx cancer", "鼻咽恶性肿瘤"]},
    # --- Tim mạch & Mạch máu (Cardiovascular - Chương I) ---
    {
        "concept_id": "ICD_I10",
        "type": "disease",
        "labels": {"vi": "tăng huyết áp", "en": "hypertension", "zh": "高血压"},
        "aliases": ["cao huyết áp", "huyết áp cao", "tăng xông", "tăng huyết áp vô căn", "high blood pressure", "HTN", "essential hypertension", "高血压病", "血压高"],
    },
    {
        "concept_id": "ICD_I20",
        "type": "disease",
        "labels": {"vi": "đau thắt ngực", "en": "angina pectoris", "zh": "心绞痛"},
        "aliases": ["đau tim", "thắt ngực", "thiếu máu cơ tim", "cơn đau thắt ngực", "angina", "chest pain", "stenocardia", "心绞痛发作", "胸痛"],
    },
    {
        "concept_id": "ICD_I21",
        "type": "disease",
        "labels": {"vi": "nhồi máu cơ tim", "en": "myocardial infarction", "zh": "心肌梗死"},
        "aliases": ["nhồi máu cơ tim cấp", "đột quỵ tim", "đau tim cấp", "hoại tử cơ tim", "heart attack", "acute myocardial infarction", "AMI", "MI", "心梗", "急性心梗", "心肌梗塞"],
    },
    {
        "concept_id": "ICD_I25",
        "type": "disease",
        "labels": {"vi": "bệnh mạch vành", "en": "coronary artery disease", "zh": "冠心病"},
        "aliases": ["bệnh tim thiếu máu cục bộ", "thiếu máu cơ tim mạn", "xơ vữa động mạch vành", "CAD", "coronary heart disease", "CHD", "ischaemic heart disease", "冠状动脉粥样硬化性心脏病", "冠状动脉硬化"],
    },
    {
        "concept_id": "ICD_I50",
        "type": "disease",
        "labels": {"vi": "suy tim", "en": "heart failure", "zh": "心力衰竭"},
        "aliases": ["suy tim ứ huyết", "suy tim sung huyết", "yếu tim", "suy tâm thất", "congestive heart failure", "CHF", "cardiac failure", "心衰", "充血性心力衰竭"],
    },
    {
        "concept_id": "ICD_I63",
        "type": "disease",
        "labels": {"vi": "nhồi máu não", "en": "cerebral infarction", "zh": "脑梗死"},
        "aliases": ["đột quỵ thiếu máu não", "tai biến mạch máu não", "nhũn não", "nghẽn mạch máu não", "ischemic stroke", "cerebral stroke", "brain infarction", "脑梗", "缺血性脑卒中", "脑血栓"],
    },
    {
        "concept_id": "ICD_I64",
        "type": "disease",
        "labels": {"vi": "đột quỵ", "en": "stroke", "zh": "脑卒中"},
        "aliases": ["tai biến", "tai biến mạch máu não", "tai biến não", "méo miệng liệt nửa người", "cerebrovascular accident", "CVA", "apoplexy", "中风", "卒中", "脑血管意外"],
    },
    {
        "concept_id": "ICD_I48",
        "type": "disease",
        "labels": {"vi": "rung nhĩ", "en": "atrial fibrillation", "zh": "心房颤动"},
        "aliases": ["loạn nhịp nhĩ", "rung tâm nhĩ", "tim đập loạn nhịp", "AFib", "AF", "房颤", "心房纤颤"],
    },
    {
        "concept_id": "ICD_I70",
        "type": "disease",
        "labels": {"vi": "xơ vữa động mạch", "en": "atherosclerosis", "zh": "动脉粥样硬化"},
        "aliases": ["xơ cứng động mạch", "xơ vữa mạch máu", "mảng xơ vữa", "arteriosclerosis", "atheroma", "动脉硬化", "血管硬化"],
    },

    # --- Hô hấp (Respiratory - Chương J) ---
    {
        "concept_id": "ICD_J00",
        "type": "disease",
        "labels": {"vi": "cảm lạnh", "en": "common cold", "zh": "普通感冒"},
        "aliases": ["cảm mạo", "cảm cúm thông thường", "viêm mũi họng cấp", "trúng gió", "cold", "acute nasopharyngitis", "感冒", "伤风"],
    },
    {
        "concept_id": "ICD_J02",
        "type": "disease",
        "labels": {"vi": "viêm họng", "en": "pharyngitis", "zh": "咽炎"},
        "aliases": ["đau họng", "viêm họng hạt", "viêm họng cấp", "sore throat", "acute pharyngitis", "咽喉炎", "喉咙发炎"],
    },
    {
        "concept_id": "ICD_J03",
        "type": "disease",
        "labels": {"vi": "viêm amidan", "en": "tonsillitis", "zh": "扁桃体炎"},
        "aliases": ["sưng amidan", "amidan hốc mủ", "viêm hạch hạnh", "acute tonsillitis", "扁桃体发炎", "扁桃腺炎"],
    },
    {
        "concept_id": "ICD_J06",
        "type": "disease",
        "labels": {"vi": "nhiễm trùng đường hô hấp trên", "en": "upper respiratory tract infection", "zh": "上呼吸道感染"},
        "aliases": ["viêm đường hô hấp trên", "nhiễm khuẩn hô hấp trên", "URTI", "URI", "上感"],
    },
    {
        "concept_id": "ICD_J18",
        "type": "disease",
        "labels": {"vi": "viêm phổi", "en": "pneumonia", "zh": "肺炎"},
        "aliases": ["sưng phổi", "nhiễm trùng phổi", "viêm phế nang", "lung infection", "pulmonitis", "肺部感染"],
    },
    {
        "concept_id": "ICD_J20",
        "type": "disease",
        "labels": {"vi": "viêm phế quản", "en": "bronchitis", "zh": "支气管炎"},
        "aliases": ["sưng cuống phổi", "viêm phế quản cấp", "viêm cuống họng", "acute bronchitis", "气管炎"],
    },
    {
        "concept_id": "ICD_J44",
        "type": "disease",
        "labels": {"vi": "bệnh phổi tắc nghẽn mạn tính", "en": "chronic obstructive pulmonary disease", "zh": "慢性阻塞性肺疾病"},
        "aliases": ["COPD", "viêm phế quản mạn tính", "khí phế thũng", "tắc nghẽn phổi", "chronic bronchitis", "emphysema", "慢阻肺"],
    },
    {
        "concept_id": "ICD_J45",
        "type": "disease",
        "labels": {"vi": "hen suyễn", "en": "asthma", "zh": "支气管哮喘"},
        "aliases": ["hen phế quản", "bệnh suyễn", "lên cơn suyễn", "thở khò khè", "bronchial asthma", "哮喘", "气喘病"],
    },

    # --- Tiêu hóa & Gan mật (Digestive & Hepato-biliary - Chương K) ---
    {
        "concept_id": "ICD_K21",
        "type": "disease",
        "labels": {"vi": "trào ngược dạ dày thực quản", "en": "gastroesophageal reflux disease", "zh": "胃食管反流病"},
        "aliases": ["GERD", "trào ngược dạ dày", "viêm thực quản trào ngược", "ợ chua ợ nóng", "acid reflux", "heartburn disease", "反流性食管炎", "胃食管反流", "烧心反酸"],
    },
    {
        "concept_id": "ICD_K25",
        "type": "disease",
        "labels": {"vi": "loét dạ dày", "en": "gastric ulcer", "zh": "胃溃疡"},
        "aliases": ["viêm loét dạ dày", "loét bao tử", "đau bao tử", "đau dạ dày", "stomach ulcer", "peptic ulcer", "胃部溃疡", "胃病"],
    },
    {
        "concept_id": "ICD_K29",
        "type": "disease",
        "labels": {"vi": "viêm dạ dày", "en": "gastritis", "zh": "胃炎"},
        "aliases": ["đau dạ dày", "viêm hang vị", "viêm niêm mạc dạ dày", "stomach ache", "acute gastritis", "慢性胃炎", "急性胃炎"],
    },
    {
        "concept_id": "ICD_K35",
        "type": "disease",
        "labels": {"vi": "viêm ruột thừa", "en": "appendicitis", "zh": "阑尾炎"},
        "aliases": ["đau ruột thừa", "viêm ruột thừa cấp", "mổ ruột thừa", "acute appendicitis", "盲肠炎"],
    },
    {
        "concept_id": "ICD_K58",
        "type": "disease",
        "labels": {"vi": "hội chứng ruột kích thích", "en": "irritable bowel syndrome", "zh": "肠易激综合征"},
        "aliases": ["IBS", "viêm đại tràng co thắt", "đại tràng chức năng", "spastic colon", "肠道过敏综合征"],
    },
    {
        "concept_id": "ICD_K70",
        "type": "disease",
        "labels": {"vi": "gan nhiễm mỡ", "en": "fatty liver disease", "zh": "脂肪肝"},
        "aliases": ["thoái hóa mỡ gan", "mỡ trong gan", "NAFLD", "hepatic steatosis", "非酒精性脂肪肝"],
    },
    {
        "concept_id": "ICD_K74",
        "type": "disease",
        "labels": {"vi": "xơ gan", "en": "cirrhosis", "zh": "肝硬化"},
        "aliases": ["xơ gan cổ trướng", "chai gan", "liver cirrhosis", "hepatic cirrhosis", "肝硬变"],
    },
    {
        "concept_id": "ICD_K80",
        "type": "disease",
        "labels": {"vi": "sỏi mật", "en": "cholelithiasis", "zh": "胆结石"},
        "aliases": ["sỏi túi mật", "sỏi ống mật", "gallstones", "gallstone disease", "胆石症", "胆囊结石"],
    },
    {
        "concept_id": "ICD_K85",
        "type": "disease",
        "labels": {"vi": "viêm tụy", "en": "pancreatitis", "zh": "胰腺炎"},
        "aliases": ["viêm tụy cấp", "hoại tử tụy", "acute pancreatitis", "急性胰腺炎"],
    },

    # --- Thận & Tiết niệu (Renal & Urology - Chương N) ---
    {
        "concept_id": "ICD_N17",
        "type": "disease",
        "labels": {"vi": "suy thận cấp", "en": "acute kidney injury", "zh": "急性肾损伤"},
        "aliases": ["tổn thương thận cấp", "suy thận cấp tính", "AKI", "acute renal failure", "ARF", "急性肾衰竭", "急性肾衰"],
    },
    {
        "concept_id": "ICD_N18",
        "type": "disease",
        "labels": {"vi": "suy thận mạn", "en": "chronic kidney disease", "zh": "慢性肾脏病"},
        "aliases": ["bệnh thận mạn", "suy thận mãn tính", "suy thận giai đoạn cuối", "CKD", "chronic renal failure", "CRF", "慢性肾衰竭", "尿毒症"],
    },
    {
        "concept_id": "ICD_N20",
        "type": "disease",
        "labels": {"vi": "sỏi thận", "en": "nephrolithiasis", "zh": "肾结石"},
        "aliases": ["sỏi đường tiết niệu", "sỏi niệu quản", "kidney stones", "renal calculi", "尿路结石"],
    },
    {
        "concept_id": "ICD_N30",
        "type": "disease",
        "labels": {"vi": "viêm bàng quang", "en": "cystitis", "zh": "膀胱炎"},
        "aliases": ["nhiễm trùng bàng quang", "viêm đường tiết niệu dưới", "bladder infection", "UTI", "尿路感染"],
    },
    {
        "concept_id": "ICD_N40",
        "type": "disease",
        "labels": {"vi": "phì đại tiền liệt tuyến", "en": "benign prostatic hyperplasia", "zh": "前列腺增生"},
        "aliases": ["u xơ tiền liệt tuyến", "tăng sinh lành tính tuyến tiền liệt", "BPH", "enlarged prostate", "前列腺肥大"],
    },

    # --- Nội tiết & Chuyển hóa (Endocrine & Metabolic - Chương E) ---
    {
        "concept_id": "ICD_E11",
        "type": "disease",
        "labels": {"vi": "đái tháo đường", "en": "diabetes mellitus", "zh": "糖尿病"},
        "aliases": ["tiểu đường", "bệnh tiểu đường", "đái tháo đường týp 2", "đái đường", "T2DM", "type 2 diabetes", "2型糖尿病", "血糖高"],
    },
    {
        "concept_id": "ICD_E03",
        "type": "disease",
        "labels": {"vi": "suy giáp", "en": "hypothyroidism", "zh": "甲状腺功能减退"},
        "aliases": ["suy tuyến giáp", "giảm năng tuyến giáp", "underactive thyroid", "甲减"],
    },
    {
        "concept_id": "ICD_E05",
        "type": "disease",
        "labels": {"vi": "cường giáp", "en": "hyperthyroidism", "zh": "甲状腺功能亢进"},
        "aliases": ["bệnh Basedow", "bướu cổ lồi mắt", "tăng năng tuyến giáp", "overactive thyroid", "Graves' disease", "甲亢"],
    },
    {
        "concept_id": "ICD_E78",
        "type": "disease",
        "labels": {"vi": "rối loạn lipid máu", "en": "dyslipidemia", "zh": "血脂异常"},
        "aliases": ["mỡ máu cao", "tăng cholesterol", "mỡ trong máu", "tăng mỡ máu", "hyperlipidemia", "high cholesterol", "高脂血症", "高胆固醇"],
    },
    {
        "concept_id": "ICD_E79",
        "type": "disease",
        "labels": {"vi": "bệnh gút", "en": "gout", "zh": "痛风"},
        "aliases": ["thống phong", "tăng axit uric máu", "viêm khớp gút", "gouty arthritis", "hyperuricemia", "高尿酸血症", "痛风性关节炎"],
    },

    # --- Nhiễm trùng & Virus (Infectious Diseases - Chương A & B) ---
    {
        "concept_id": "ICD_B18",
        "type": "disease",
        "labels": {"vi": "viêm gan B", "en": "hepatitis B", "zh": "乙型肝炎"},
        "aliases": ["viêm gan siêu vi B", "HBV", "nhiễm virus viêm gan B", "chronic hepatitis B", "乙肝", "乙型病毒性肝炎"],
    },
    {
        "concept_id": "ICD_B19",
        "type": "disease",
        "labels": {"vi": "viêm gan C", "en": "hepatitis C", "zh": "丙型肝炎"},
        "aliases": ["viêm gan siêu vi C", "HCV", "nhiễm virus viêm gan C", "chronic hepatitis C", "丙肝", "丙型病毒性肝炎"],
    },
    {
        "concept_id": "ICD_A90",
        "type": "disease",
        "labels": {"vi": "sốt xuất huyết", "en": "dengue fever", "zh": "登革热"},
        "aliases": ["sốt xuất huyết Dengue", "sốt Dengue", "sốt do muỗi vằn", "dengue", "dengue hemorrhagic fever", "DHF", "登革出血热"],
    },
    {
        "concept_id": "ICD_A15",
        "type": "disease",
        "labels": {"vi": "bệnh lao", "en": "tuberculosis", "zh": "结核病"},
        "aliases": ["lao phổi", "ho lao", "nhiễm vi khuẩn lao", "TB", "pulmonary tuberculosis", "肺结核", "结核菌感染"],
    },
    {
        "concept_id": "ICD_U07",
        "type": "disease",
        "labels": {"vi": "COVID-19", "en": "COVID-19", "zh": "新型冠状病毒感染"},
        "aliases": ["nhiễm SARS-CoV-2", "viêm đường hô hấp cấp do nCoV", "coronavirus disease", "SARS-CoV-2", "新冠", "新冠肺炎"],
    },

    # --- Cơ xương khớp (Musculoskeletal - Chương M) ---
    {
        "concept_id": "ICD_M06",
        "type": "disease",
        "labels": {"vi": "viêm khớp dạng thấp", "en": "rheumatoid arthritis", "zh": "类风湿关节炎"},
        "aliases": ["thấp khớp", "viêm đa khớp dạng thấp", "RA", "rheumatism", "类风湿", "类风湿性关节炎"],
    },
    {
        "concept_id": "ICD_M15",
        "type": "disease",
        "labels": {"vi": "thoái hóa khớp", "en": "osteoarthritis", "zh": "骨关节炎"},
        "aliases": ["hư khớp", "viêm xương khớp", "thoái hóa khớp gối", "OA", "degenerative joint disease", "骨关节病", "退行性关节炎", "骨质增生"],
    },
    {
        "concept_id": "ICD_M54",
        "type": "disease",
        "labels": {"vi": "thoát vị đĩa đệm", "en": "herniated disc", "zh": "椎间盘突出"},
        "aliases": ["đau thần kinh tọa", "lồi đĩa đệm", "thoát vị cột sống thắt lưng", "slipped disc", "sciatica", "腰椎间盘突出", "坐骨神经痛"],
    },
    {
        "concept_id": "ICD_M81",
        "type": "disease",
        "labels": {"vi": "loãng xương", "en": "osteoporosis", "zh": "骨质疏松"},
        "aliases": ["xốp xương", "thưa xương", "mất mật độ xương", "brittle bones", "骨质疏松症"],
    },

    # --- Da liễu & Dị ứng (Dermatology - Chương L) ---
    {
        "concept_id": "ICD_L20",
        "type": "disease",
        "labels": {"vi": "viêm da cơ địa", "en": "atopic dermatitis", "zh": "特应性皮炎"},
        "aliases": ["chàm thể tạng", "bệnh eczema", "lác sữa", "eczema", "湿疹"],
    },
    {
        "concept_id": "ICD_L50",
        "type": "disease",
        "labels": {"vi": "mề đay", "en": "urticaria", "zh": "荨麻疹"},
        "aliases": ["nổi mề đay", "nổi mẩn ngứa", "mề đay mẩn ngứa", "dị ứng da", "hives", "nettle rash", "风疹块", "风疙瘩"],
    },
    {
        "concept_id": "ICD_L40",
        "type": "disease",
        "labels": {"vi": "vảy nến", "en": "psoriasis", "zh": "银屑病"},
        "aliases": ["vẩy nến", "bệnh vảy nến", "牛皮癣"],
    },

    # --- Thần kinh (Neurology - Chương G) ---
    {
        "concept_id": "ICD_G43",
        "type": "disease",
        "labels": {"vi": "đau nửa đầu", "en": "migraine", "zh": "偏头痛"},
        "aliases": ["đau đầu Migraine", "nhức nửa đầu", "đau đầu vận mạch", "migraine headache", "偏头痛发作"],
    },
    {
        "concept_id": "ICD_G40",
        "type": "disease",
        "labels": {"vi": "động kinh", "en": "epilepsy", "zh": "癫痫"},
        "aliases": ["bệnh giật kinh phong", "co giật", "lên cơn co giật", "seizure disorder", "羊角风", "癫痫发作"],
    },
    {
        "concept_id": "ICD_G20",
        "type": "disease",
        "labels": {"vi": "bệnh Parkinson", "en": "Parkinson's disease", "zh": "帕金森病"},
        "aliases": ["liệt rung", "run tay chân tuổi già", "Parkinsonism", "震颤麻痹"],
    },
    {
        "concept_id": "ICD_G30",
        "type": "disease",
        "labels": {"vi": "sa sút trí tuệ", "en": "dementia", "zh": "痴呆"},
        "aliases": ["bệnh Alzheimer", "lú lẫn tuổi già", "suy giảm trí nhớ", "Alzheimer's disease", "阿尔茨海默病", "老年痴呆"],
    },

    # --- Ung bướu (Oncology - Chương C) ---
    {
        "concept_id": "ICD_C34",
        "type": "disease",
        "labels": {"vi": "ung thư phổi", "en": "lung cancer", "zh": "肺癌"},
        "aliases": ["u ác tính phổi", "carcinoma phổi", "bronchial carcinoma", "肺部恶性肿瘤"],
    },
    {
        "concept_id": "ICD_C16",
        "type": "disease",
        "labels": {"vi": "ung thư dạ dày", "en": "gastric cancer", "zh": "胃癌"},
        "aliases": ["u ác tính dạ dày", "stomach cancer", "胃部恶性肿瘤"],
    },
    {
        "concept_id": "ICD_C22",
        "type": "disease",
        "labels": {"vi": "ung thư gan", "en": "liver cancer", "zh": "肝癌"},
        "aliases": ["ung thư biểu mô tế bào gan", "HCC", "hepatocellular carcinoma", "原发性肝癌"],
    },
    {
        "concept_id": "ICD_C50",
        "type": "disease",
        "labels": {"vi": "ung thư vú", "en": "breast cancer", "zh": "乳腺癌"},
        "aliases": ["u ác tính tuyến vú", "K vú", "mammary carcinoma", "乳癌"],
    },
]

# ==============================================================================
# 2. DƯỢC HỌC & THUỐC THIẾT YẾU (PHARMACOLOGY & ESSENTIAL DRUGS)
# ==============================================================================
DRUG_CONCEPTS: List[Dict[str, Any]] = [
    {"concept_id": "DRUG_CEFTRIAXONE", "type": "drug", "labels": {"vi": "ceftriaxone", "en": "ceftriaxone", "zh": "头孢曲松"}, "aliases": ["rocephin", "kháng sinh tiêm cephalosporin thế hệ 3", "头孢曲松钠"]},
    {"concept_id": "DRUG_LEVOFLOXACIN", "type": "drug", "labels": {"vi": "levofloxacin", "en": "levofloxacin", "zh": "左氧氟沙星"}, "aliases": ["cravit", "kháng sinh phổ rộng hô hấp", "quinolone thế hệ 3", "盐酸左氧氟沙星"]},
    {"concept_id": "DRUG_DOXYCYCLINE", "type": "drug", "labels": {"vi": "doxycycline", "en": "doxycycline", "zh": "多西环素"}, "aliases": ["tetracycline", "kháng sinh trị mụn", "kháng sinh trị sốt mò", "盐酸多西环素"]},
    {"concept_id": "DRUG_METRONIDAZOLE", "type": "drug", "labels": {"vi": "metronidazole", "en": "metronidazole", "zh": "甲硝唑"}, "aliases": ["klion", "flagyl", "thuốc trị vi khuẩn kỵ khí", "thuốc trị ký sinh trùng", "甲硝唑片"]},
    {"concept_id": "DRUG_CLARITHROMYCIN", "type": "drug", "labels": {"vi": "clarithromycin", "en": "clarithromycin", "zh": "克拉霉素"}, "aliases": ["klacid", "thuốc diệt vi khuẩn HP dạ dày", "macrolide", "克拉霉素胶囊"]},
    {"concept_id": "DRUG_ACYCLOVIR", "type": "drug", "labels": {"vi": "acyclovir", "en": "acyclovir", "zh": "阿昔洛韦"}, "aliases": ["zovirax", "thuốc trị zona", "thuốc bôi thủy đậu", "thuốc trị herpes", "阿昔洛韦乳膏"]},
    {"concept_id": "DRUG_OSELTAMIVIR", "type": "drug", "labels": {"vi": "oseltamivir", "en": "oseltamivir", "zh": "奥司他韦"}, "aliases": ["tamiflu", "thuốc đặc trị cúm a", "thuốc kháng virus cúm", "磷酸奥司他韦"]},
    {"concept_id": "DRUG_FLUCONAZOLE", "type": "drug", "labels": {"vi": "fluconazole", "en": "fluconazole", "zh": "氟康唑"}, "aliases": ["diflucan", "thuốc kháng nấm", "thuốc trị nấm candida", "氟康唑胶囊"]},
    {"concept_id": "DRUG_BISOPROLOL", "type": "drug", "labels": {"vi": "bisoprolol", "en": "bisoprolol", "zh": "比索洛尔"}, "aliases": ["concor", "thuốc chẹn beta", "thuốc hạ nhịp tim", "hạ áp chẹn beta", "富马酸比索洛尔"]},
    {"concept_id": "DRUG_PERINDOPRIL", "type": "drug", "labels": {"vi": "perindopril", "en": "perindopril", "zh": "培哚普利"}, "aliases": ["coversyl", "thuốc ức chế men chuyển tim mạch", "培哚普利叔丁胺片"]},
    {"concept_id": "DRUG_TELMISARTAN", "type": "drug", "labels": {"vi": "telmisartan", "en": "telmisartan", "zh": "替米沙坦"}, "aliases": ["micardis", "chẹn thụ thể angiotensin", "替米沙坦片"]},
    {"concept_id": "DRUG_ROSUVASTATIN", "type": "drug", "labels": {"vi": "rosuvastatin", "en": "rosuvastatin", "zh": "瑞舒伐他汀"}, "aliases": ["crestor", "thuốc giảm mỡ máu liều cao", "statin thế hệ mới", "瑞舒伐他汀钙片"]},
    {"concept_id": "DRUG_CLOPIDOGREL", "type": "drug", "labels": {"vi": "clopidogrel", "en": "clopidogrel", "zh": "氯吡格雷"}, "aliases": ["plavix", "thuốc chống ngưng tập tiểu cầu", "ngừa tái phát đột quỵ", "硫酸氢氯吡格雷片"]},
    {"concept_id": "DRUG_FUROSEMIDE", "type": "drug", "labels": {"vi": "furosemide", "en": "furosemide", "zh": "呋塞米"}, "aliases": ["lasix", "thuốc lợi tiểu quai", "lợi tiểu hạ áp", "thuốc giảm phù", "速尿"]},
    {"concept_id": "DRUG_PANTOPRAZOLE", "type": "drug", "labels": {"vi": "pantoprazole", "en": "pantoprazole", "zh": "泮托拉唑"}, "aliases": ["pantoloc", "thuốc dạ dày pantoprazole", "ức chế bơm proton", "泮托拉唑钠"]},
    {"concept_id": "DRUG_DOMPERIDONE", "type": "drug", "labels": {"vi": "domperidone", "en": "domperidone", "zh": "多潘立酮"}, "aliases": ["motilium", "motilium-m", "thuốc chống nôn", "thuốc trị chướng bụng đầy hơi", "吗丁啉"]},
    {"concept_id": "DRUG_PHOSPHALUGEL", "type": "drug", "labels": {"vi": "aluminium phosphate", "en": "aluminium phosphate gel", "zh": "磷酸铝凝胶"}, "aliases": ["phosphalugel", "thuốc chữ p", "gel sữa dạ dày", "thuốc tráng dạ dày", "洁维乐"]},
    {"concept_id": "DRUG_SMECTA", "type": "drug", "labels": {"vi": "diosmectite", "en": "diosmectite", "zh": "蒙脱石散"}, "aliases": ["smecta", "thuốc cầm tiêu chảy", "thuốc trị tiêu chảy smecta", "思密达"]},
    {"concept_id": "DRUG_ORESOL", "type": "drug", "labels": {"vi": "oresol", "en": "oral rehydration salts", "zh": "口服补液盐"}, "aliases": ["ors", "bù nước điện giải", "dung dịch oresol", "口服补液盐散"]},
    {"concept_id": "DRUG_SALBUTAMOL", "type": "drug", "labels": {"vi": "salbutamol", "en": "salbutamol", "zh": "沙丁胺醇"}, "aliases": ["ventolin", "albuterol", "thuốc xịt hen suyễn", "thuốc giãn phế quản cấp", "硫酸沙丁胺醇吸入气雾剂"]},
    {"concept_id": "DRUG_ACETYLCYSTEINE", "type": "drug", "labels": {"vi": "acetylcysteine", "en": "acetylcysteine", "zh": "乙酰半胱氨酸"}, "aliases": ["nac", "thuốc tiêu đờm", "thuốc long đờm", "giảm ho đờm", "富露施"]},
    {"concept_id": "DRUG_FEXOFENADINE", "type": "drug", "labels": {"vi": "fexofenadine", "en": "fexofenadine", "zh": "非索非那定"}, "aliases": ["telfast", "thuốc chống dị ứng thế hệ mới", "không gây buồn ngủ", "盐酸非索非那定片"]},
    {"concept_id": "DRUG_CETIRIZINE", "type": "drug", "labels": {"vi": "cetirizine", "en": "cetirizine", "zh": "西替利嗪"}, "aliases": ["zyrtec", "thuốc dị ứng mề đay", "kháng histamin h1", "盐酸西替利嗪片"]},
    # --- Hạ sốt, giảm đau, kháng viêm ---
    {
        "concept_id": "DRUG_PARACETAMOL",
        "type": "drug",
        "labels": {"vi": "paracetamol", "en": "paracetamol", "zh": "对乙酰氨基酚"},
        "aliases": ["acetaminophen", "panadol", "efferalgan", "hapacol", "thuốc hạ sốt", "thuốc giảm đau", "tylenol", "扑热息痛", "泰诺"],
    },
    {
        "concept_id": "DRUG_IBUPROFEN",
        "type": "drug",
        "labels": {"vi": "ibuprofen", "en": "ibuprofen", "zh": "布洛芬"},
        "aliases": ["advil", "motrin", "kháng viêm không steroid", "NSAID", "giảm đau kháng viêm", "布洛芬缓释胶囊", "芬必得"],
    },
    {
        "concept_id": "DRUG_ASPIRIN",
        "type": "drug",
        "labels": {"vi": "aspirin", "en": "aspirin", "zh": "阿司匹林"},
        "aliases": ["acetylsalicylic acid", "thuốc chống đông máu", "thuốc ngừa cục máu đông", "aspirin 81mg", "乙酰水杨酸"],
    },
    {
        "concept_id": "DRUG_DICLOFENAC",
        "type": "drug",
        "labels": {"vi": "diclofenac", "en": "diclofenac", "zh": "双氯芬酸"},
        "aliases": ["voltaren", "cataflam", "thuốc giảm đau khớp", "双氯芬酸钠"],
    },
    {
        "concept_id": "DRUG_CELECOXIB",
        "type": "drug",
        "labels": {"vi": "celecoxib", "en": "celecoxib", "zh": "塞来昔布"},
        "aliases": ["celebrex", "ức chế chọn lọc COX-2", "thuốc đau khớp", "西乐葆"],
    },

    # --- Kháng sinh (Antibiotics) ---
    {
        "concept_id": "DRUG_AMOXICILLIN",
        "type": "drug",
        "labels": {"vi": "amoxicillin", "en": "amoxicillin", "zh": "阿莫西林"},
        "aliases": ["amox", "kháng sinh amoxicillin", "penicillin", "阿莫仙"],
    },
    {
        "concept_id": "DRUG_AUGMENTIN",
        "type": "drug",
        "labels": {"vi": "amoxicillin/clavulanic acid", "en": "amoxicillin and clavulanate potassium", "zh": "阿莫西林克拉维酸钾"},
        "aliases": ["augmentin", "klamentin", "curam", "amoxicillin-clavulanate", "co-amoxiclav", "安美汀"],
    },
    {
        "concept_id": "DRUG_CEFUROXIME",
        "type": "drug",
        "labels": {"vi": "cefuroxime", "en": "cefuroxime", "zh": "头孢呋辛"},
        "aliases": ["zinnat", "kháng sinh cephalosporin thế hệ 2", "头孢呋辛酯"],
    },
    {
        "concept_id": "DRUG_CEFIXIME",
        "type": "drug",
        "labels": {"vi": "cefixime", "en": "cefixime", "zh": "头孢克肟"},
        "aliases": ["kháng sinh cephalosporin thế hệ 3", "头孢克肟分散片"],
    },
    {
        "concept_id": "DRUG_AZITHROMYCIN",
        "type": "drug",
        "labels": {"vi": "azithromycin", "en": "azithromycin", "zh": "阿奇霉素"},
        "aliases": ["zithromax", "kháng sinh macrolide", "阿奇霉素分散片"],
    },
    {
        "concept_id": "DRUG_CIPROFLOXACIN",
        "type": "drug",
        "labels": {"vi": "ciprofloxacin", "en": "ciprofloxacin", "zh": "环丙沙星"},
        "aliases": ["cipro", "kháng sinh quinolone", "fluoroquinolone", "盐酸环丙沙星"],
    },

    # --- Kháng viêm Corticoid ---
    {
        "concept_id": "DRUG_PREDNISOLONE",
        "type": "drug",
        "labels": {"vi": "prednisolone", "en": "prednisolone", "zh": "泼尼松龙"},
        "aliases": ["corticoid", "corticosteroid", "kháng viêm steroid", "thuốc chống viêm", "强的松龙"],
    },
    {
        "concept_id": "DRUG_METHYLPREDNISOLONE",
        "type": "drug",
        "labels": {"vi": "methylprednisolone", "en": "methylprednisolone", "zh": "甲泼尼龙"},
        "aliases": ["medrol", "solu-medrol", "corticoid liều cao", "甲强龙"],
    },
    {
        "concept_id": "DRUG_DEXAMETHASONE",
        "type": "drug",
        "labels": {"vi": "dexamethasone", "en": "dexamethasone", "zh": "地塞米松"},
        "aliases": ["dexa", "corticosteroid kháng viêm", "地塞米松磷酸钠"],
    },

    # --- Tim mạch & Huyết áp ---
    {
        "concept_id": "DRUG_AMLODIPINE",
        "type": "drug",
        "labels": {"vi": "amlodipine", "en": "amlodipine", "zh": "氨氯地平"},
        "aliases": ["norvasc", "thuốc chẹn kênh canxi", "thuốc hạ huyết áp", "CCB", "络活喜"],
    },
    {
        "concept_id": "DRUG_LOSARTAN",
        "type": "drug",
        "labels": {"vi": "losartan", "en": "losartan", "zh": "氯沙坦"},
        "aliases": ["cozaar", "thuốc chẹn thụ thể ARB", "hạ áp", "氯沙坦钾"],
    },
    {
        "concept_id": "DRUG_ENALAPRIL",
        "type": "drug",
        "labels": {"vi": "enalapril", "en": "enalapril", "zh": "依那普利"},
        "aliases": ["thuốc ức chế men chuyển", "ACEi", "hạ huyết áp", "马来酸依那普利"],
    },
    {
        "concept_id": "DRUG_ATORVASTATIN",
        "type": "drug",
        "labels": {"vi": "atorvastatin", "en": "atorvastatin", "zh": "阿托伐他汀"},
        "aliases": ["lipitor", "thuốc hạ mỡ máu", "statin", "hạ cholesterol", "立普妥"],
    },

    # --- Tiểu đường ---
    {
        "concept_id": "DRUG_METFORMIN",
        "type": "drug",
        "labels": {"vi": "metformin", "en": "metformin", "zh": "二甲双胍"},
        "aliases": ["glucophage", "thuốc hạ đường huyết", "thuốc trị tiểu đường", "盐酸二甲双胍", "格华止"],
    },
    {
        "concept_id": "DRUG_INSULIN",
        "type": "drug",
        "labels": {"vi": "insulin", "en": "insulin", "zh": "胰岛素"},
        "aliases": ["tiêm insulin", "insulin glargine", "insulin nhanh", "hạ đường huyết tiêm", "胰岛素注射液"],
    },

    # --- Dạ dày & Tiêu hóa ---
    {
        "concept_id": "DRUG_OMEPRAZOLE",
        "type": "drug",
        "labels": {"vi": "omeprazole", "en": "omeprazole", "zh": "奥美拉唑"},
        "aliases": ["thuốc trị đau dạ dày", "thuốc ức chế bơm proton", "PPI", "giảm tiết axit", "奥美拉唑肠溶胶囊"],
    },
    {
        "concept_id": "DRUG_ESOMEPRAZOLE",
        "type": "drug",
        "labels": {"vi": "esomeprazole", "en": "esomeprazole", "zh": "埃索美拉唑"},
        "aliases": ["nexium", "thuốc dạ dày nexium", "thuốc trào ngược", "耐信"],
    },
]

# ==============================================================================
# 3. ĐÔNG Y / Y HỌC CỔ TRUYỀN (TRADITIONAL CHINESE MEDICINE - TCM)
# ==============================================================================
TCM_CONCEPTS: List[Dict[str, Any]] = [
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
    {"concept_id": "TCM_XIAOCHAIHU", "type": "tcm_formula", "labels": {"vi": "tiểu sài hồ thang", "en": "xiaochaihu decoction", "zh": "小柴胡汤"}, "aliases": ["hòa giải thiếu dương", "xiao chai hu tang", "小柴胡颗粒"]},
    {"concept_id": "TCM_DACHAIHU", "type": "tcm_formula", "labels": {"vi": "đại sài hồ thang", "en": "dachaihu decoction", "zh": "大柴胡汤"}, "aliases": ["hòa giải thiếu dương thông phủ", "da chai hu tang"]},
    {"concept_id": "TCM_BAIHUTANG", "type": "tcm_formula", "labels": {"vi": "bạch hổ thang", "en": "baihu decoction", "zh": "白虎汤"}, "aliases": ["thanh nhiệt dương minh", "bai hu tang"]},
    {"concept_id": "TCM_LONGDAN", "type": "tcm_formula", "labels": {"vi": "long đởm tả can thang", "en": "longdan xiegan decoction", "zh": "龙胆泻肝汤"}, "aliases": ["tả can đởm thực hỏa", "thanh hạ tiêu thấp nhiệt", "龙胆泻肝丸"]},
    {"concept_id": "TCM_BANXIAXIE", "type": "tcm_formula", "labels": {"vi": "bán hạ tả tâm thang", "en": "banxia xiexin decoction", "zh": "半夏泻心汤"}, "aliases": ["hàn nhiệt thác tạp", "tiêu bĩ tán kết", "ban xia xie xin tang"]},
    {"concept_id": "TCM_YINQIAO", "type": "tcm_formula", "labels": {"vi": "ngân kiều tán", "en": "yinqiao powder", "zh": "银翘散"}, "aliases": ["tân lương giải biểu", "trị cảm sốt phong nhiệt", "yin qiao san", "银翘解毒片"]},
    {"concept_id": "TCM_MAHUANGTANG", "type": "tcm_formula", "labels": {"vi": "ma hoàng thang", "en": "mahuang decoction", "zh": "麻黄汤"}, "aliases": ["phát hãn giải biểu tuyên phế bình suyễn", "ma huang tang"]},
    {"concept_id": "TCM_GUIZHITANG", "type": "tcm_formula", "labels": {"vi": "quế chi thang", "en": "guizhi decoction", "zh": "桂枝汤"}, "aliases": ["giải cơ thoái nhiệt điều hòa vinh vệ", "gui zhi tang"]},
    {"concept_id": "TCM_BAOHUAWAN", "type": "tcm_formula", "labels": {"vi": "bảo hòa hoàn", "en": "baohe pills", "zh": "保和丸"}, "aliases": ["tiêu thực hóa trệ hòa vị", "thuốc trị ăn không tiêu đông y", "bao he wan"]},
    # --- Vị thuốc Bổ khí & Bổ huyết ---
    {
        "concept_id": "TCM_HUANGQI",
        "type": "tcm_herb",
        "labels": {"vi": "hoàng kỳ", "en": "astragalus root", "zh": "黄芪"},
        "aliases": ["bắc hoàng kỳ", "astragalus", "bổ khí cố biểu", "Radix Astragali", "北芪"],
    },
    {
        "concept_id": "TCM_RENSHEN",
        "type": "tcm_herb",
        "labels": {"vi": "nhân sâm", "en": "ginseng", "zh": "人参"},
        "aliases": ["sâm triều tiên", "hồng sâm", "đại bổ nguyên khí", "Panax ginseng", "红参"],
    },
    {
        "concept_id": "TCM_DANGGUI",
        "type": "tcm_herb",
        "labels": {"vi": "đương quy", "en": "angelica sinensis", "zh": "当归"},
        "aliases": ["quy đầu", "sâm đương quy", "bổ huyết hoạt huyết", "Radix Angelicae Sinensis"],
    },
    {
        "concept_id": "TCM_BAIZHU",
        "type": "tcm_herb",
        "labels": {"vi": "bạch truật", "en": "atractylodes macrocephala", "zh": "白术"},
        "aliases": ["kiện tỳ táo thấp", "bạch truật sao", "Rhizoma Atractylodis Macrocephalae"],
    },
    {
        "concept_id": "TCM_GANCAO",
        "type": "tcm_herb",
        "labels": {"vi": "cam thảo", "en": "licorice root", "zh": "甘草"},
        "aliases": ["cam thảo bắc", "chích cam thảo", "điều hòa chư dược", "Radix Glycyrrhizae"],
    },
    {
        "concept_id": "TCM_SHUDI",
        "type": "tcm_herb",
        "labels": {"vi": "thục địa", "en": "rehmannia root", "zh": "熟地黄"},
        "aliases": ["thục địa hoàng", "tư âm bổ huyết", "Rehmannia glutinosa", "熟地"],
    },

    # --- Vị thuốc Hoạt huyết & Thanh nhiệt ---
    {
        "concept_id": "TCM_DANSHEN",
        "type": "tcm_herb",
        "labels": {"vi": "đan sâm", "en": "salvia miltiorrhiza", "zh": "丹参"},
        "aliases": ["huyết sâm", "hoạt huyết khứ ứ", "Radix Salviae Miltiorrhizae"],
    },
    {
        "concept_id": "TCM_CHUANXIONG",
        "type": "tcm_herb",
        "labels": {"vi": "xuyên khung", "en": "ligusticum striatum", "zh": "川芎"},
        "aliases": ["khung cùng", "hành khí hoạt huyết", "Rhizoma Chuanxiong"],
    },
    {
        "concept_id": "TCM_JINYINHUA",
        "type": "tcm_herb",
        "labels": {"vi": "kim ngân hoa", "en": "honeysuckle flower", "zh": "金银花"},
        "aliases": ["nhẫn đông đằng", "thanh nhiệt giải độc", "Flos Lonicerae"],
    },
    {
        "concept_id": "TCM_LIANQIAO",
        "type": "tcm_herb",
        "labels": {"vi": "liên kiều", "en": "forsythia fruit", "zh": "连翘"},
        "aliases": ["thanh nhiệt tán kết", "Fructus Forsythiae"],
    },
    {
        "concept_id": "TCM_HUANGTIAN",
        "type": "tcm_herb",
        "labels": {"vi": "hoàng liên", "en": "coptis chinensis", "zh": "黄连"},
        "aliases": ["thanh nhiệt táo thấp", "kháng sinh thực vật", "Rhizoma Coptidis"],
    },
    {
        "concept_id": "TCM_BANLANGEN",
        "type": "tcm_herb",
        "labels": {"vi": "bản lam căn", "en": "isatis root", "zh": "板蓝根"},
        "aliases": ["rễ bọ mẩy", "thanh nhiệt lương huyết", "Radix Isatidis", "板蓝根颗粒"],
    },

    # --- Bài thuốc cổ phương danh tiếng (Classical Formulas) ---
    {
        "concept_id": "TCM_LIUWEI",
        "type": "tcm_formula",
        "labels": {"vi": "lục vị địa hoàng hoàn", "en": "liuwei dihuang pills", "zh": "六味地黄丸"},
        "aliases": ["lục vị", "tư bổ can thận âm", "liu wei di huang wan", "六味地黄"],
    },
    {
        "concept_id": "TCM_BAZHI",
        "type": "tcm_formula",
        "labels": {"vi": "bát vị quế phụ", "en": "jinqui shenqi pills", "zh": "八味地黄丸"},
        "aliases": ["kim quỹ thận khí hoàn", "ôn bổ thận dương", "bát vị", "金匮肾气丸"],
    },
    {
        "concept_id": "TCM_SIWU",
        "type": "tcm_formula",
        "labels": {"vi": "tứ vật thang", "en": "siwu decoction", "zh": "四物汤"},
        "aliases": ["bổ huyết điều huyết", "si wu tang"],
    },
    {
        "concept_id": "TCM_SIJUN",
        "type": "tcm_formula",
        "labels": {"vi": "tứ quân tử thang", "en": "sijunzi decoction", "zh": "四君子汤"},
        "aliases": ["ích khí kiện tỳ", "si jun zi tang"],
    },
    {
        "concept_id": "TCM_BAZHEN",
        "type": "tcm_formula",
        "labels": {"vi": "bát trân thang", "en": "bazhen decoction", "zh": "八珍汤"},
        "aliases": ["khí huyết song bổ", "ba zhen tang", "八珍颗粒"],
    },
    {
        "concept_id": "TCM_BUZHONG",
        "type": "tcm_formula",
        "labels": {"vi": "bổ trung ích khí thang", "en": "buzhong yiqi decoction", "zh": "补中益气汤"},
        "aliases": ["thăng dương cử hãm", "bu zhong yi qi tang", "补中益气丸"],
    },
    {
        "concept_id": "TCM_XIAOYAO",
        "type": "tcm_formula",
        "labels": {"vi": "tiêu dao tán", "en": "xiaoyao powder", "zh": "逍遥散"},
        "aliases": ["sơ can giải uất", "xiao yao san", "逍遥丸"],
    },
    {
        "concept_id": "TCM_ANGONG",
        "type": "tcm_formula",
        "labels": {"vi": "an cung ngưu hoàng hoàn", "en": "angong niuhuang pills", "zh": "安宫牛黄丸"},
        "aliases": ["an cung", "thanh tâm khai khiếu", "thuốc tai biến đông y", "an gong niu huang wan"],
    },
]

# ==============================================================================
# 4. KHẨU NGỮ BỆNH NHÂN & TRIỆU CHỨNG ĐỜI THƯỜNG (PATIENT COLLOQUIAL SYMPTOMS)
# ==============================================================================
COLLOQUIAL_CONCEPTS: List[Dict[str, Any]] = [
    {"concept_id": "SYMP_PALPITATION", "type": "symptom", "labels": {"vi": "hồi hộp tim đập nhanh", "en": "palpitations", "zh": "心悸"}, "aliases": ["tim đập thình thịch", "đánh trống ngực", "hồi hộp", "loạn nhịp", "heart racing", "heart pounding", "心慌", "心跳过快"]},
    {"concept_id": "SYMP_NUMBNESS", "type": "symptom", "labels": {"vi": "tê bì chân tay", "en": "numbness and tingling", "zh": "手脚发麻"}, "aliases": ["tê rần", "châm chích như kiến bò", "tê buốt", "mất cảm giác", "pins and needles", "paresthesia", "肢体麻木", "发麻"]},
    {"concept_id": "SYMP_COLD_EXTREMITIES", "type": "symptom", "labels": {"vi": "chân tay lạnh", "en": "cold extremities", "zh": "手脚冰凉"}, "aliases": ["lạnh buốt tay chân", "sợ lạnh", "chân tay giá lạnh", "cold hands and feet", "畏寒肢冷", "手足不温"]},
    {"concept_id": "SYMP_NIGHT_SWEATS", "type": "symptom", "labels": {"vi": "đổ mồ hôi trộm", "en": "night sweats", "zh": "盗汗"}, "aliases": ["toát mồ hôi đêm", "vã mồ hôi", "vã mồ hôi hột", "nocturnal sweating", "夜间出汗", "自汗盗汗"]},
    {"concept_id": "SYMP_HOARSENESS", "type": "symptom", "labels": {"vi": "khản tiếng", "en": "hoarseness", "zh": "声音嘶哑"}, "aliases": ["mất tiếng", "khàn giọng", "nói không ra hơi", "husky voice", "dysphonia", "喉咙嘶哑", "失音"]},
    {"concept_id": "SYMP_SORE_THROAT_DRY", "type": "symptom", "labels": {"vi": "khô họng ngứa cổ", "en": "dry and itchy throat", "zh": "喉咙干痒"}, "aliases": ["vướng đờm ở cổ", "rát họng ngứa cổ", "nuốt nghẹn", "đắng miệng", "dry throat", "scratchy throat", "咽干", "咽部异物感"]},
    {"concept_id": "SYMP_EDEMA", "type": "symptom", "labels": {"vi": "phù chân", "en": "peripheral edema", "zh": "下肢水肿"}, "aliases": ["sưng phù mắt cá", "phù thũng", "ấn lõm mắt cá chân", "swollen ankles", "leg swelling", "腿肿", "脚踝浮肿"]},
    {"concept_id": "SYMP_WEIGHT_LOSS", "type": "symptom", "labels": {"vi": "sụt cân", "en": "unintentional weight loss", "zh": "体重下降"}, "aliases": ["sút cân nhanh", "gầy sút", "sụt ký bất thường", "unexplained weight loss", "消瘦", "短时间内消瘦"]},
    # --- Đau nhức & Cảm giác (Pain & Sensation) ---
    {
        "concept_id": "SYMP_HEADACHE",
        "type": "symptom",
        "labels": {"vi": "đau đầu", "en": "headache", "zh": "头痛"},
        "aliases": ["nhức đầu", "đau nhức đầu", "nặng đầu", "đau nhức nửa đầu", "đau buốt óc", "nhức đầu như búa bổ", "head pain", "cranial pain", "头晕脑胀", "偏头疼"],
    },
    {
        "concept_id": "SYMP_CHESTPAIN",
        "type": "symptom",
        "labels": {"vi": "đau ngực", "en": "chest pain", "zh": "胸痛"},
        "aliases": ["tức ngực", "đau tức ngực", "nặng ngực", "ngực bị đè nghẹn", "đau thắt ngực", "nhói ngực", "khó thở tức ngực", "chest tightness", "chest pressure", "胸闷", "胸口疼", "心口痛"],
    },
    {
        "concept_id": "SYMP_ABDOMINALPAIN",
        "type": "symptom",
        "labels": {"vi": "đau bụng", "en": "abdominal pain", "zh": "腹痛"},
        "aliases": ["đau quặn bụng", "đau âm ỉ vùng bụng", "đau vùng thượng vị", "đau quanh rốn", "đau bụng dưới", "cồn cào ruột gan", "xót ruột", "stomach ache", "belly pain", "bellyache", "cramps", "肚子疼", "胃痛", "腹部隐痛", "肚子绞痛"],
    },
    {
        "concept_id": "SYMP_BACKPAIN",
        "type": "symptom",
        "labels": {"vi": "đau lưng", "en": "back pain", "zh": "腰痛"},
        "aliases": ["đau mỏi thắt lưng", "đau cột sống", "đau mỏi lưng", "đau buốt sống lưng", "đau hông", "lumbago", "backache", "lower back pain", "腰酸", "腰疼", "腰肌劳损"],
    },
    {
        "concept_id": "SYMP_JOINTPAIN",
        "type": "symptom",
        "labels": {"vi": "đau khớp", "en": "joint pain", "zh": "关节痛"},
        "aliases": ["nhức mỏi khớp", "đau đầu gối", "lục cục khớp gối", "sưng nóng đỏ đau khớp", "cứng khớp buổi sáng", "arthralgia", "joint stiffness", "关节酸痛", "膝盖疼", "关节僵硬"],
    },

    # --- Tiêu hóa & Bài tiết (GI & Excretory Lay Terms) ---
    {
        "concept_id": "SYMP_DIARRHEA",
        "type": "symptom",
        "labels": {"vi": "tiêu chảy", "en": "diarrhea", "zh": "腹泻"},
        "aliases": ["đi ngoài", "đi ngoài phân lỏng", "đi ỉa chảy", "tháo dạ", "đi phân sống", "mót rặn", "loạn khuẩn đường ruột", "loose stools", "watery diarrhea", "runny stool", "拉肚子", "拉稀", "大便稀溏"],
    },
    {
        "concept_id": "SYMP_CONSTIPATION",
        "type": "symptom",
        "labels": {"vi": "táo bón", "en": "constipation", "zh": "便秘"},
        "aliases": ["khó đi cầu", "đi ngoài phân cứng", "phân dê", "bón", "uống thuốc trị táo bón", "costiveness", "irregular bowel", "大便干燥", "排便困难"],
    },
    {
        "concept_id": "SYMP_HEARTBURN",
        "type": "symptom",
        "labels": {"vi": "ợ chua", "en": "heartburn", "zh": "反酸"},
        "aliases": ["ợ nóng", "ợ hơi", "nóng rát cổ họng", "trào ngược axit dạ dày", "nóng rát sau xương ức", "đầy bụng ợ hơi", "acid reflux", "water brash", "pyrosis", "烧心", "打嗝", "嗳气"],
    },
    {
        "concept_id": "SYMP_NAUSEA",
        "type": "symptom",
        "labels": {"vi": "buồn nôn", "en": "nausea", "zh": "恶心"},
        "aliases": ["nôn ói", "nôn mửa", "mắc ói", "buồn nôn nôn ói", "cồn cào buồn nôn", "sickness", "vomiting", "retching", "想吐", "呕吐"],
    },
    {
        "concept_id": "SYMP_DYSURIA",
        "type": "symptom",
        "labels": {"vi": "tiểu buốt", "en": "dysuria", "zh": "尿痛"},
        "aliases": ["tiểu rắt", "tiểu són", "tiểu buốt tiểu rắt", "tiểu đau", "nước tiểu đục", "tiểu ra máu", "tiểu đêm nhiều lần", "burning urination", "painful urination", "frequent urination", "尿急", "尿频", "夜尿多"],
    },

    # --- Hô hấp & Dị ứng (Respiratory & Allergy Lay Terms) ---
    {
        "concept_id": "SYMP_COUGH",
        "type": "symptom",
        "labels": {"vi": "ho", "en": "cough", "zh": "咳嗽"},
        "aliases": ["ho khan", "ho có đờm", "ho rũ rượi", "ngứa cổ ho", "ho dai dẳng", "ho về đêm", "khạc đờm", "dry cough", "productive cough", "hacking cough", "干咳", "咳痰", "夜间咳嗽"],
    },
    {
        "concept_id": "SYMP_DYSPNEA",
        "type": "symptom",
        "labels": {"vi": "khó thở", "en": "dyspnea", "zh": "呼吸困难"},
        "aliases": ["thở gấp", "hụt hơi", "thở không ra hơi", "ngộp thở", "thở dốc", "thở khò khè", "nặng ngực khó thở", "shortness of breath", "breathlessness", "wheezing", "喘气", "气促", "胸闷气短"],
    },
    {
        "concept_id": "SYMP_FEVER",
        "type": "symptom",
        "labels": {"vi": "sốt", "en": "fever", "zh": "发热"},
        "aliases": ["phát sốt", "sốt cao", "sốt nóng", "sốt rét", "sốt li bì", "nóng lạnh", "sốt kèm rét run", "đổ mồ hôi trộm", "pyrexia", "high temperature", "chills", "发烧", "高热", "畏寒", "打寒战"],
    },
    {
        "concept_id": "SYMP_DIZZINESS",
        "type": "symptom",
        "labels": {"vi": "chóng mặt", "en": "dizziness", "zh": "头晕"},
        "aliases": ["hoa mắt chóng mặt", "xây xẩm mặt mày", "choáng váng", "mất thăng bằng", "quay cuồng", "tiền đình", "lightheadedness", "vertigo", "giddiness", "眩晕", "头昏", "天旋地转"],
    },
    {
        "concept_id": "SYMP_ITCHING",
        "type": "symptom",
        "labels": {"vi": "ngứa da", "en": "pruritus", "zh": "皮肤瘙痒"},
        "aliases": ["ngứa ngáy", "nổi mẩn đỏ", "nổi sẩn", "nổi mề đay ngứa", "da ngứa ngáy", "gãi ngứa", "itching", "itchy skin", "rash", "发痒", "起红疹", "身上痒"],
    },
    {
        "concept_id": "SYMP_FATIGUE",
        "type": "symptom",
        "labels": {"vi": "mệt mỏi", "en": "fatigue", "zh": "乏力"},
        "aliases": ["uể oải", "kiệt sức", "rã rời tay chân", "mệt mỏi rã rời", "thiếu sức sống", "mất sức", "tiredness", "exhaustion", "lethargy", "浑身无力", "没精神", "倦怠"],
    },
    {
        "concept_id": "SYMP_INSOMNIA",
        "type": "symptom",
        "labels": {"vi": "mất ngủ", "en": "insomnia", "zh": "失眠"},
        "aliases": ["khó ngủ", "trằn trọc mất ngủ", "ngủ không sâu giấc", "thức giấc nửa đêm", "sleeplessness", "sleep disorder", "睡不着", "入睡困难", "多梦易醒"],
    },
]

# ==============================================================================
# 5. XÉT NGHIỆM & CHỈ SỐ SINH HÓA (LAB TESTS & PROCEDURES)
# ==============================================================================
LAB_CONCEPTS: List[Dict[str, Any]] = [
    {
        "concept_id": "LAB_GLUCOSE",
        "type": "lab_test",
        "labels": {"vi": "xét nghiệm đường huyết", "en": "blood glucose test", "zh": "血糖检测"},
        "aliases": ["đường máu", "đo đường huyết", "đường huyết lúc đói", "HbA1c", "chỉ số đường huyết", "blood sugar test", "fasting blood sugar", "FPG", "血糖", "空腹血糖", "糖化血红蛋白"],
    },
    {
        "concept_id": "LAB_LIPID",
        "type": "lab_test",
        "labels": {"vi": "xét nghiệm mỡ máu", "en": "lipid panel", "zh": "血脂化验"},
        "aliases": ["bộ mỡ máu", "cholesterol toàn phần", "triglyceride", "LDL-C", "HDL-C", "chỉ số mỡ máu", "lipid profile", "cholesterol test", "血脂四项", "总胆固醇", "甘油三酯"],
    },
    {
        "concept_id": "LAB_LIVER",
        "type": "lab_test",
        "labels": {"vi": "xét nghiệm men gan", "en": "liver function tests", "zh": "肝功能检查"},
        "aliases": ["men gan cao", "chỉ số AST", "chỉ số ALT", "SGOT", "SGPT", "GGT", "bilirubin", "LFT", "liver enzymes", "肝功", "转氨酶", "谷丙转氨酶"],
    },
    {
        "concept_id": "LAB_KIDNEY",
        "type": "lab_test",
        "labels": {"vi": "xét nghiệm chức năng thận", "en": "renal function tests", "zh": "肾功能检查"},
        "aliases": ["chức năng thận", "chỉ số creatinine", "creatinin máu", "độ lọc cầu thận", "eGFR", "ure máu", "BUN", "RFT", "kidney panel", "肾功", "血肌酐", "尿素氮"],
    },
    {
        "concept_id": "LAB_CBC",
        "type": "lab_test",
        "labels": {"vi": "tổng phân tích tế bào máu", "en": "complete blood count", "zh": "全血细胞计数"},
        "aliases": ["công thức máu", "bạch cầu cao", "hồng cầu", "tiểu cầu", "huyết sắc tố", "CBC", "hemogram", "blood count", "血常规", "白细胞", "红细胞", "血小板"],
    },
    {
        "concept_id": "LAB_URINALYSIS",
        "type": "lab_test",
        "labels": {"vi": "tổng phân tích nước tiểu", "en": "urinalysis", "zh": "尿常规检查"},
        "aliases": ["xét nghiệm nước tiểu", "đạm niệu", "protein niệu", "hồng cầu trong nước tiểu", "urine test", "urinary test", "尿常规", "尿蛋白"],
    },
    {
        "concept_id": "LAB_ECG",
        "type": "lab_test",
        "labels": {"vi": "điện tâm đồ", "en": "electrocardiogram", "zh": "心电图"},
        "aliases": ["đo điện tim", "ECG", "EKG", "điện tim đồ", "electrocardiography", "心电图检查"],
    },
    {
        "concept_id": "LAB_ULTRASOUND",
        "type": "lab_test",
        "labels": {"vi": "siêu âm", "en": "ultrasound", "zh": "超声波检查"},
        "aliases": ["siêu âm ổ bụng", "siêu âm tim", "siêu âm thai", "siêu âm Doppler", "ultrasonography", "sonogram", "B超", "彩超", "心脏彩超"],
    },
    {
        "concept_id": "LAB_CT",
        "type": "lab_test",
        "labels": {"vi": "chụp cắt lớp vi tính", "en": "computed tomography", "zh": "计算机断层扫描"},
        "aliases": ["chụp CT", "CT scanner", "chụp CT sọ não", "chụp CT lồng ngực", "CT scan", "CAT scan", "CT检查", "螺旋CT"],
    },
    {
        "concept_id": "LAB_MRI",
        "type": "lab_test",
        "labels": {"vi": "chụp cộng hưởng từ", "en": "magnetic resonance imaging", "zh": "磁共振成像"},
        "aliases": ["chụp MRI", "cộng hưởng từ não", "MRI cột sống", "MRI scan", "核磁共振", "MRI检查"],
    },
    {
        "concept_id": "LAB_ENDOSCOPY",
        "type": "lab_test",
        "labels": {"vi": "nội soi", "en": "endoscopy", "zh": "内窥镜检查"},
        "aliases": ["nội soi dạ dày", "nội soi đại tràng", "nội soi tiêu hóa", "gastroscopy", "colonoscopy", "胃镜", "肠镜"],
    },
]
