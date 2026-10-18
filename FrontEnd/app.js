"use strict";

const $ = (id) => document.getElementById(id);
const labels = {uploaded:"Đã tải lên",queued:"Trong hàng đợi",running:"Đang xử lý",pausing:"Đang tạm dừng",paused:"Đã tạm dừng",failed:"Cần xử lý lỗi",completed:"Hoàn tất"};
const descriptions = {
  queued:"Tác vụ đang chờ lượt. Mỗi thời điểm server xử lý một file.",
  running:"Đang truy hồi và xếp hạng. Tiến độ cập nhật sau mỗi truy vấn được lưu thành công.",
  pausing:"Sẽ tạm dừng sau batch hiện tại. Checkpoint đã lưu được giữ nguyên.",
  paused:"Đã giữ lại checkpoint. Chọn Tiếp tục để xử lý phần còn lại.",
  failed:"Các dòng thành công vẫn được giữ lại. Kiểm tra lỗi rồi tiếp tục từ checkpoint.",
  completed:"Kết quả đã sẵn sàng. File ZIP chứa output.json theo định dạng nộp bài.",
};
const format = new Intl.NumberFormat("vi-VN");
let jobs = [];
let selectedId = localStorage.getItem("sbtc-selected-job");
let selectedFile = null;
let uploading = false;
let actionBusy = false;

function notice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

function connection(online) {
  $("connection").className = `connection ${online ? "online" : "offline"}`;
  $("connection").lastElementChild.textContent = online ? "Đã kết nối server" : "Mất kết nối · Đang thử lại";
}

async function request(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options});
  const result = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(result.detail) ? result.detail.map((d) => d.msg).join("; ") : result.detail;
    throw new Error(detail || "Không thể thực hiện yêu cầu.");
  }
  return result;
}

function badge(state) {
  const span = document.createElement("span");
  span.className = "badge";
  span.dataset.status = state;
  span.textContent = labels[state] || state;
  return span;
}

function render() {
  const job = jobs.find((item) => item.id === selectedId);
  $("history-count").textContent = `${format.format(jobs.length)} tác vụ`;
  $("history-empty").hidden = jobs.length > 0;
  const focusId = $("job-history").contains(document.activeElement) ? document.activeElement.dataset.jobId : null;
  $("job-history").replaceChildren(...jobs.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item";
    button.dataset.jobId = item.id;
    button.setAttribute("aria-pressed", String(item.id === selectedId));
    const left = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = item.filename;
    const detail = document.createElement("small");
    detail.textContent = `Dòng ${format.format(item.start)}–${format.format(item.end)} · ${new Date(item.created_at).toLocaleString("vi-VN")}`;
    left.append(name, detail);
    const right = document.createElement("span");
    right.className = "history-right";
    const count = document.createElement("span");
    count.className = "history-count";
    count.textContent = `${format.format(item.completed)} / ${format.format(item.total)} đã lưu`;
    right.append(count, badge(item.status));
    button.append(left, right);
    button.addEventListener("click", () => select(item.id));
    return button;
  }));
  if (focusId) {
    [...$("job-history").children].find((element) => element.dataset.jobId === focusId)?.focus({preventScroll:true});
  }
  $("empty-state").hidden = Boolean(job);
  $("job-detail").hidden = !job;
  $("job-badge").hidden = !job;
  if (!job) return;
  $("job-badge").textContent = labels[job.status] || job.status;
  $("job-badge").dataset.status = job.status;
  $("job-filename").textContent = job.filename;
  $("job-meta").textContent = `Dòng ${format.format(job.start)}–${format.format(job.end)} / ${format.format(job.rows)} · Batch ${job.batch_size} · Lần chạy ${job.attempts}`;
  $("completed-count").textContent = format.format(job.completed);
  $("failed-count").textContent = format.format(job.failed);
  $("total-count").textContent = format.format(job.total);
  const percent = job.total ? Math.floor(job.completed * 100 / job.total) : 0;
  $("progress-percent").textContent = `${percent}%`;
  $("job-progress").value = percent;
  $("progress-label").textContent = job.status === "completed" ? "Hoàn tất và đã lưu" : "Dòng đã lưu vào checkpoint";
  $("job-status-copy").textContent = descriptions[job.status] || "Đang chuẩn bị tác vụ.";
  $("pause-button").hidden = !["queued","running","pausing"].includes(job.status);
  $("pause-button").disabled = actionBusy || job.status === "pausing";
  $("resume-button").hidden = !["paused","failed"].includes(job.status);
  $("resume-button").disabled = actionBusy;
  $("download-link").hidden = !job.download_url;
  if (job.download_url) $("download-link").href = job.download_url;
  $("job-error").hidden = !job.error;
  $("job-error-text").textContent = job.error ? `${job.error.message} (${job.error.type})` : "";
  $("errors-link").hidden = !job.errors_url;
  if (job.errors_url) $("errors-link").href = job.errors_url;
}

function select(identifier) {
  selectedId = identifier;
  localStorage.setItem("sbtc-selected-job", identifier);
  render();
}

async function refresh() {
  try {
    jobs = await request("/api/jobs");
    connection(true);
    if (!jobs.some((job) => job.id === selectedId) && jobs.length) select(jobs[0].id);
    else render();
  } catch {
    connection(false);
  }
}

function chooseFile(file) {
  notice();
  if (file && !file.name.toLowerCase().endsWith(".parquet")) {
    notice("Vui lòng chọn file có đuôi .parquet.");
    selectedFile = null;
    $("file").value = "";
  } else selectedFile = file;
  $("file-summary").textContent = selectedFile ? selectedFile.name : "Kéo thả file Parquet vào đây";
  $("submit-button").disabled = !selectedFile || uploading;
}

$("file").addEventListener("change", (event) => chooseFile(event.target.files[0]));
for (const name of ["dragenter","dragover"]) $("drop-zone").addEventListener(name, (event) => {
  event.preventDefault();
  $("drop-zone").classList.add("dragging");
});
for (const name of ["dragleave","drop"]) $("drop-zone").addEventListener(name, (event) => {
  event.preventDefault();
  $("drop-zone").classList.remove("dragging");
});
$("drop-zone").addEventListener("drop", (event) => {
  if (uploading) return;
  if (event.dataTransfer.files.length !== 1) return notice("Chọn một file cho mỗi lần chạy.");
  $("file").files = event.dataTransfer.files;
  chooseFile(event.dataTransfer.files[0]);
});

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  notice();
  if (!selectedFile || uploading) return;
  const start = $("start").value;
  const end = $("end").value;
  if (start && end && Number(start) > Number(end)) return notice("Dòng bắt đầu phải nhỏ hơn hoặc bằng dòng kết thúc.");
  const data = new FormData();
  data.append("file", selectedFile);
  if (start) data.append("start", start);
  if (end) data.append("end", end);
  data.append("batch_size", $("batch-size").value);
  uploading = true;
  $("submit-button").disabled = true;
  $("file").disabled = true;
  $("upload-progress-wrap").hidden = false;
  $("upload-progress").value = 0;
  $("upload-percent").textContent = "0%";
  try {
    const job = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      xhr.responseType = "json";
      xhr.upload.addEventListener("progress", (progress) => {
        if (!progress.lengthComputable) return;
        const percent = Math.floor(progress.loaded * 100 / progress.total);
        $("upload-progress").value = percent;
        $("upload-percent").textContent = `${percent}%`;
      });
      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
        else {
          const detail = xhr.response?.detail;
          reject(new Error(typeof detail === "string" ? detail : "Không thể tải file. Kiểm tra file và phạm vi dòng."));
        }
      });
      xhr.addEventListener("error", () => reject(new Error("Không kết nối được server. Vui lòng thử lại.")));
      xhr.addEventListener("abort", () => reject(new Error("Lần tải file đã bị hủy.")));
      xhr.send(data);
    });
    jobs = [job, ...jobs.filter((item) => item.id !== job.id)];
    select(job.id);
    await refresh();
  } catch (error) {
    notice(error.message);
  } finally {
    uploading = false;
    $("submit-button").disabled = !selectedFile;
    $("file").disabled = false;
    $("upload-progress-wrap").hidden = true;
  }
});

async function action(name) {
  if (!selectedId || actionBusy) return;
  actionBusy = true;
  notice();
  render();
  try {
    const job = await request(`/api/jobs/${selectedId}/${name}`, {method:"POST"});
    jobs = jobs.map((item) => item.id === job.id ? job : item);
  } catch (error) {
    notice(error.message);
  } finally {
    actionBusy = false;
    render();
  }
}
$("pause-button").addEventListener("click", () => action("pause"));
$("resume-button").addEventListener("click", () => action("resume"));

async function poll() {
  await refresh();
  setTimeout(poll, document.hidden ? 8000 : 2000);
}
poll();
