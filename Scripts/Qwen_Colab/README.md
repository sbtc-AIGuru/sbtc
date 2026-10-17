# Qwen3.5-9B trên Colab

- `Qwen3_5_9B_Colab_API.ipynb`: notebook độc lập, tải model từ Hugging Face và chạy API trên GPU Colab.
- `test_local.py`: client thử API từ local, chỉ dùng Python standard library.

Model **công khai**, tải trực tiếp bằng `token=False`; không yêu cầu đăng nhập hay kiểm tra Hugging Face token.
`QWEN_API_KEY` là khóa xác thực cho endpoint của bạn. `NGROK_AUTHTOKEN` dùng để mở tunnel ngrok.
Hai khóa này phục vụ kết nối API, không phải điều kiện tải weights.

## Chạy notebook

1. Upload notebook vào [Colab](https://colab.research.google.com/) và chọn runtime GPU.
   Ưu tiên L4/A100. Mặc định NF4 4-bit để giảm VRAM; T4 16 GB là cấu hình để thử,
   chưa được kiểm chứng với weights thật trong phiên phát triển này.
2. Trong Colab Secrets, thêm `QWEN_API_KEY` (chuỗi ASCII tự chọn, ít nhất 16 ký tự,
   không chứa khoảng trắng) và `NGROK_AUTHTOKEN`, cho notebook quyền đọc chúng.
   Nếu chưa thêm, notebook sẽ hỏi bằng ô nhập ẩn.
3. Xem lệnh cài dependency trong cell đầu. Đặt `INSTALL_PACKAGES = True` nếu đồng ý
   cài trong Colab, chạy cell, rồi restart session. Đặt lại `False`, chạy từ đầu.
   Notebook không tự thay PyTorch/CUDA. Không cần cài thư viện trên máy local.
4. Chạy lần lượt đến smoke test. Notebook kiểm tra CUDA, tải model một lần,
   khởi động API và sinh một câu trả lời qua HTTP nội bộ.
5. Khi smoke test thành công, đặt `OPEN_PUBLIC_TUNNEL = True` và chạy cell tunnel.
   Lần đầu pyngrok có thể tải ngrok binary. Sao chép URL HTTPS được in ra.
6. Giữ phiên Colab hoạt động trong khi gọi từ local. Khi xong, đặt `STOP_SERVER = True`
   trong cell dừng rồi chạy; ngắt runtime để giải phóng model/GPU.

Weights gốc được tải trước khi quantize; nên có khoảng 30 GB disk trống.
Mặc định tổng context là 4096 token, output tối đa 1024 token/request.
Thiếu kernel DeltaNet tối ưu thì Transformers có thể dùng đường thực thi PyTorch
chậm và tốn VRAM hơn. Notebook không tự cài thêm kernel.

## Gọi từ local

Từ thư mục dự án trên máy Ubuntu này:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
python Scripts/Qwen_Colab/test_local.py \
  --base-url "https://YOUR-NGROK-DOMAIN" \
  --prompt "Giải thích RAG bằng tiếng Việt trong 3 câu." \
  --max-tokens 256
```

Script hỏi `QWEN_API_KEY` bằng `getpass`, dùng đúng key trong Colab.
Có thể đặt `QWEN_BASE_URL`, `QWEN_API_KEY` trong environment thay thế.
URL được chấp nhận ở dạng root hoặc kết thúc bằng `/v1`.

```bash
python Scripts/Qwen_Colab/test_local.py \
  --base-url "https://YOUR-NGROK-DOMAIN/v1" \
  --prompt "Viết một hàm Python tính Fibonacci." \
  --temperature 0 --max-tokens 512 --json
```

`--thinking --max-tokens 1024` bật thinking. Nội dung thinking được trả nguyên văn trong
`message.content`, có thể chiếm hết output budget trước khi có câu trả lời cuối.
`--timeout 1200` tăng thời gian chờ khi GPU chậm. Client kiểm tra health và danh sách
model trước khi gửi prompt; lỗi trả exit code khác 0, không tự retry request sinh văn bản.

## API

Tất cả endpoint yêu cầu header `Authorization: Bearer YOUR_API_KEY`:

| Method | Path | Chức năng |
| --- | --- | --- |
| GET | `/health` | Trạng thái, model revision, context limit, GPU có bận không |
| GET | `/v1/models` | Model được phục vụ |
| POST | `/v1/chat/completions` | Sinh câu trả lời văn bản, response có `choices` và `usage` |

Body ví dụ:

```json
{
  "model": "Qwen/Qwen3.5-9B",
  "messages": [{"role": "user", "content": "Xin chào!"}],
  "max_tokens": 256,
  "temperature": 0.7,
  "top_p": 0.8,
  "enable_thinking": false,
  "stream": false
}
```

API triển khai tập con chat completions: chỉ text, không streaming, ảnh/video, tools hay
JSON schema output. Tham số chưa hỗ trợ bị từ chối. Giới hạn 32 message, 16.000 ký tự/message,
64.000 ký tự tổng cộng; context được tính bằng tokenizer và bao gồm cả output budget.
Request thứ hai khi đang sinh nhận 429. Context vượt giới hạn nhận 400, OOM nhận 503.
Nếu OOM, giảm context/output và restart runtime, hoặc chọn GPU lớn hơn.
Nếu 401, kiểm tra API key. Nếu mất kết nối, kiểm tra phiên Colab và URL tunnel hiện tại.
API dừng khi runtime Colab ngắt; không có hosting thường trực trên Hugging Face.

## Kiểm chứng

Kiểm tra offline từ thư mục dự án, không tải weights và không mở tunnel:

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate DL_Env
pytest -q tests/test_qwen_colab.py
python -m compileall -q Scripts/Qwen_Colab/test_local.py tests/test_qwen_colab.py
```

Test kiểm tra notebook, API với engine giả lập và client. Việc tải weights, inference CUDA,
VRAM/tốc độ và ngrok cần kiểm chứng bằng các cell smoke test trên Colab thật.

## Nguồn

- [Model card](https://huggingface.co/Qwen/Qwen3.5-9B)
- [Transformers Qwen3.5](https://huggingface.co/docs/transformers/model_doc/qwen3_5)
- [Bitsandbytes quantization](https://huggingface.co/docs/transformers/quantization/bitsandbytes)
- [pyngrok API](https://pyngrok.readthedocs.io/en/latest/api.html)
