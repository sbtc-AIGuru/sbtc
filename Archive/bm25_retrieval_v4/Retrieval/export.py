"""SubmissionWriter: Đóng gói Bài nộp Chuẩn 100% Quy định BTC.

Theo SPEC-bm25-medical-multilingual.md Mục 15 và Bất biến ViBioMIR.
- Đóng gói đúng 1 file ZIP duy nhất, chỉ chứa đúng 1 file .json ở root.
- Đảm bảo đầy đủ toàn bộ 1.200 queries từ query.parquet.
- doc_id xuất chuỗi string, id query xuất integer.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence, Set

from sbtc.Scripts.Retrieval.models import SubmissionItem


class SubmissionWriter:
    """Quản lý ghi streaming file JSON và đóng gói ZIP nộp bài."""

    def __init__(self, output_dir: Path, expected_query_ids: Sequence[int] | None = None) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.expected_query_ids = list(expected_query_ids) if expected_query_ids else []

    def write_submission(
        self,
        items: Iterable[SubmissionItem],
        json_filename: str = "submission.json",
        zip_filename: str = "submission.zip",
    ) -> Tuple[Path, Path]:
        """Ghi streaming mảng JSON và nén ZIP.

        Returns:
            (json_path, zip_path)
        """
        json_path = self.output_dir / json_filename
        partial_json_path = self.output_dir / f"{json_filename}.partial"
        zip_path = self.output_dir / zip_filename

        seen_query_ids: Set[int] = set()

        with open(partial_json_path, "w", encoding="utf-8") as f:
            f.write("[\n")
            first = True
            for item in items:
                seen_query_ids.add(item.id)
                if not first:
                    f.write(",\n")
                first = False
                # Format 2 spaces indent
                item_json = json.dumps(item.to_dict(), ensure_ascii=False, indent=2)
                f.write(item_json)

            # Bù đắp các query còn thiếu nếu có khai báo expected_query_ids
            for expected_id in self.expected_query_ids:
                if expected_id not in seen_query_ids:
                    seen_query_ids.add(expected_id)
                    if not first:
                        f.write(",\n")
                    first = False
                    empty_item = {
                        "id": expected_id,
                        "relevant_docs": [],
                        "relevant_chunks": [],
                    }
                    f.write(json.dumps(empty_item, ensure_ascii=False, indent=2))

            f.write("\n]\n")

        # Atomic rename từ .partial sang .json
        if json_path.exists():
            json_path.unlink()
        partial_json_path.rename(json_path)

        # Kiểm tra đọc lại JSON hợp lệ
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("Submission JSON root phải là mảng (Array).")
            if self.expected_query_ids and len(data) != len(self.expected_query_ids):
                raise ValueError(
                    f"Số lượng queries trong JSON ({len(data)}) không khớp với kỳ vọng ({len(self.expected_query_ids)})!"
                )

        # Đóng gói ZIP root (chỉ chứa duy nhất file .json)
        if zip_path.exists():
            zip_path.unlink()

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Ghi file vào root ZIP (arcname chỉ lấy tên file, không kèm folder cha)
            zf.write(json_path, arcname=json_filename)

        return json_path, zip_path
