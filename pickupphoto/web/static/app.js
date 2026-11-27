const byId = (id) => document.getElementById(id);
const strings = {
  open: ["開啟資料夾", "Open folder"], analyze: ["分析照片", "Analyze photos"],
  export: ["匯出 RAW", "Export RAW"], quit: ["結束", "Quit"], library: ["照片庫", "Library"],
  noFolder: ["尚未開啟資料夾", "No folder open"], recent: ["最近開啟", "Recent folders"],
  filter: ["星等篩選", "Rating filter"], rating: ["評分", "Rating"],
  navigate: ["切換照片", "Navigate"], photos: ["照片", "Photos"], grid: ["格狀", "Grid"],
  single: ["單張", "Single"], emptyTitle: ["開啟資料夾開始挑片", "Open a folder to start culling"],
  more: ["載入更多", "Show more"], previous: ["上一張", "Previous"], next: ["下一張", "Next"],
  decode: ["完整解碼", "Decode full RAW"], details: ["照片資訊", "Photo details"],
  selectPhoto: ["選取照片查看資訊", "Select a photo to see its details"],
  unrate: ["清除星等", "Clear rating"], analysis: ["分析結果", "Analysis"],
  path: ["資料夾路徑", "Folder path"], browse: ["瀏覽…", "Browse…"],
  cancel: ["取消", "Cancel"], confirmOpen: ["開啟", "Open"], target: ["目標資料夾", "Destination"],
  conflict: ["同名檔案", "Existing filenames"], rename: ["重新命名", "Rename"],
  skip: ["跳過", "Skip"], overwrite: ["覆蓋", "Overwrite"], copy: ["複製原始檔", "Copy originals"],
  viewLabel: ["檢視模式", "View mode"], progressLabel: ["工作進度", "Task progress"],
  broken: ["無法讀取照片", "Photo could not be loaded"], all: ["全部照片", "All photos"],
  unrated: ["未評分", "Unrated"], unit: ["張", "photos"], star: ["星", "stars"],
  noPhotos: ["這個資料夾沒有 NEF 或 RAF 照片", "No NEF or RAF photos in this folder"],
  noMatches: ["沒有符合篩選條件的照片", "No photos match this filter"],
  clearFilter: ["請調整星等篩選", "Change the rating filter to see photos"],
  best: ["最佳幀", "Best shot"], burst: ["連拍", "Burst"],
  noAnalysis: ["尚未分析", "Not yet analyzed"], sharpness: ["對焦清晰", "Sharpness"],
  exposure: ["曝光正常", "Exposure"], motion_blur: ["無運動模糊", "Motion clarity"],
  eye_focus: ["眼睛對焦", "Eye focus"], loading: ["載入照片…", "Loading photo…"],
  decoding: ["完整解碼中…", "Decoding full RAW…"], scanning: ["正在掃描資料夾…", "Scanning folder…"],
  analyzing: ["正在分析照片…", "Analyzing photos…"], copying: ["正在複製原始檔…", "Copying originals…"],
  analyzed: ["已分析", "Analyzed"], copied: ["已複製", "Copied"],
  failed: ["失敗", "Failed"], skipped: ["跳過", "Skipped"],
  stopped: ["PickUpPhoto 已結束，可以關閉此分頁。", "PickUpPhoto has stopped. You can close this tab."],
  disconnected: ["連線中斷，請重新開啟 PickUpPhoto。", "Disconnected. Reopen PickUpPhoto to reconnect."],
  picking: ["請在 macOS 對話框中選擇資料夾。", "Choose a folder in the macOS dialog."],
};

let lang = sessionStorage.getItem("language") === "en" ? 1 : 0;
const t = (key) => strings[key][lang];
const state = {
  id: "", folder: null, photos: [], recent: [], selected: null, mode: "grid",
  shown: 72, busy: false, rating: false, stopped: false, previewKey: "", version: "",
};
const pageSize = 72;

async function api(path, data) {
  const response = await fetch("/api/" + path, data === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-PickUpPhoto": "1"},
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || response.statusText);
  return result;
}

function notice(message = "", error = false) {
  const area = byId("notice");
  area.textContent = message;
  area.hidden = !message;
  area.classList.toggle("error", error);
}

function formError(id, message = "") {
  byId(id).textContent = message;
  byId(id).hidden = !message;
}

function filterParts(value) {
  const [mode, stars] = (value || ">=:0").split(":");
  return {mode, stars: Number(stars)};
}

function filtered(value = byId("filter").value) {
  const {mode, stars} = filterParts(value);
  return state.photos.filter((photo) => {
    if (mode === "=") return photo.stars === stars;
    if (mode === "<=") return photo.stars <= stars;
    return photo.stars >= stars;
  });
}

function updateFilters() {
  for (const id of ["filter", "export-filter"]) {
    const select = byId(id);
    const selected = select.value || (id === "export-filter" ? ">=:3" : ">=:0");
    const options = [new Option(t("all"), ">=:0"), new Option(t("unrated"), "=:0")];
    for (const [compare, sign] of [[">=", "≥"], ["=", "="], ["<=", "≤"]]) {
      for (let stars = 1; stars <= 5; stars += 1) {
        options.push(new Option(`${sign} ${stars} ${t("star")}`, `${compare}:${stars}`));
      }
    }
    select.replaceChildren(...options);
    select.value = selected;
  }
}

function translate() {
  document.documentElement.lang = lang ? "en" : "zh-Hant";
  byId("language").textContent = lang ? "中文" : "EN";
  document.querySelectorAll("[data-t]").forEach((item) => { item.textContent = t(item.dataset.t); });
  document.querySelectorAll("[data-label]").forEach((item) => item.setAttribute("aria-label", t(item.dataset.label)));
  updateFilters();
}

const imageUrl = (photo, kind) => `/api/image/${state.id}/${photo.id}/${kind}`;
const selectedPhoto = () => state.photos.find((photo) => photo.id === state.selected);

function makeImage(photo, kind, frame) {
  const img = document.createElement("img");
  img.alt = photo.name;
  img.decoding = "async";
  if (kind === "thumbnail") img.loading = "lazy";
  img.addEventListener("error", () => {
    const message = document.createElement("span");
    message.className = "broken";
    message.textContent = t("broken");
    if (img.parentElement === frame) frame.replaceChildren(message);
  });
  img.src = imageUrl(photo, kind);
  return img;
}

function cardRating(card, photo) {
  card.querySelector(".card-stars").textContent = "★".repeat(photo.stars);
  card.setAttribute("aria-label", `${photo.name}, ${photo.stars} ${t("star")}${photo.group?.ai_best ? ", " + t("best") : ""}`);
}

function addCards(photos, start) {
  const fragment = document.createDocumentFragment();
  for (const photo of photos.slice(start, state.shown)) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "card";
    card.dataset.photo = photo.id;
    card.setAttribute("aria-pressed", String(state.selected === photo.id));
    const frame = document.createElement("span");
    frame.className = "frame";
    frame.append(makeImage(photo, "thumbnail", frame));
    const details = document.createElement("span");
    details.className = "card-details";
    details.innerHTML = '<span class="card-name"></span><span class="card-meta"><span class="card-stars"></span><span class="best"></span></span>';
    details.querySelector(".card-name").textContent = photo.name;
    details.querySelector(".best").textContent = photo.group?.ai_best ? t("best") : "";
    card.append(frame, details);
    cardRating(card, photo);
    card.addEventListener("click", () => selectPhoto(photo.id));
    card.addEventListener("dblclick", () => changeMode("single"));
    fragment.append(card);
  }
  byId("grid").append(fragment);
}

function paintSelection() {
  for (const card of byId("grid").children) {
    card.setAttribute("aria-pressed", String(Number(card.dataset.photo) === state.selected));
  }
}

function selectPhoto(id) {
  state.selected = id;
  paintSelection();
  renderInspector();
  if (state.mode === "single") renderPreview();
}

function renderInspector() {
  const photo = selectedPhoto();
  byId("photo-details").hidden = !photo;
  byId("inspector-empty").hidden = Boolean(photo);
  if (!photo) return;
  byId("photo-name").textContent = photo.name;
  byId("photo-size").textContent = `${(photo.size / 1048576).toFixed(1)} MiB`;
  byId("exif").textContent = photo.exif;
  const stars = byId("stars");
  Array.from(stars.children).forEach((button, index) => {
    const value = index + 1;
    button.textContent = value <= photo.stars ? "★" : "☆";
    button.classList.toggle("filled", value <= photo.stars);
    button.setAttribute("aria-pressed", String(value === photo.stars));
    button.setAttribute("aria-label", `${value} ${t("star")}`);
    button.disabled = state.stopped;
  });
  byId("unrate").disabled = state.stopped || photo.stars === 0;
  const group = photo.group;
  byId("burst").hidden = !group;
  byId("burst").textContent = group
    ? `${t("burst")} ${group.group_id} · ${group.group_rank}/${group.group_size}${group.ai_best ? " · " + t("best") : ""}`
    : "";
  const scores = byId("scores");
  scores.replaceChildren();
  if (!photo.scores) {
    const empty = document.createElement("dt");
    empty.className = "muted";
    empty.textContent = t("noAnalysis");
    scores.append(empty);
    return;
  }
  for (const [key, value] of Object.entries(photo.scores)) {
    const row = document.createElement("div");
    const label = document.createElement("dt");
    const reading = document.createElement("dd");
    label.textContent = t(key);
    reading.textContent = value === null ? "—" : `${value.toFixed(0)} / 100`;
    row.append(label, reading);
    scores.append(row);
  }
}

function renderPreview(kind = "preview") {
  const photo = selectedPhoto();
  const photos = filtered();
  if (!photo) return;
  const index = photos.indexOf(photo);
  byId("prev").disabled = index <= 0;
  byId("next").disabled = index >= photos.length - 1;
  const preview = byId("preview");
  const key = `${state.id}/${photo.id}/${kind}`;
  if (key === state.previewKey) return;
  state.previewKey = key;
  const message = document.createElement("span");
  message.textContent = t(kind === "full" ? "decoding" : "loading");
  message.className = "muted";
  const image = makeImage(photo, kind, preview);
  image.hidden = true;
  byId("decode").disabled = kind === "full";
  image.addEventListener("load", () => {
    if (image.parentElement !== preview) return;
    message.remove();
    image.hidden = false;
  });
  image.addEventListener("error", () => {
    if (state.previewKey === key) {
      state.previewKey = "";
      byId("decode").disabled = false;
    }
  });
  preview.replaceChildren(message, image);
}

function renderContent(refreshGrid = true) {
  const photos = filtered();
  if (!photos.some((photo) => photo.id === state.selected)) state.selected = photos[0]?.id ?? null;
  if (!photos.length) state.mode = "grid";
  const single = state.mode === "single";
  byId("grid-mode").setAttribute("aria-pressed", String(!single));
  byId("single-mode").setAttribute("aria-pressed", String(single));
  byId("single-mode").disabled = !photos.length;
  byId("empty").hidden = Boolean(photos.length);
  byId("empty-open").hidden = Boolean(state.folder);
  byId("empty-title").textContent = t(!state.folder ? "emptyTitle" : state.photos.length ? "noMatches" : "noPhotos");
  byId("empty-note").textContent = state.photos.length ? t("clearFilter") : "Nikon NEF · Fujifilm RAF";
  const count = photos.length === state.photos.length ? photos.length : `${photos.length} / ${state.photos.length}`;
  byId("count").textContent = state.folder ? `${count} ${t("unit")}` : "Nikon NEF · Fujifilm RAF";
  byId("grid").hidden = single || !photos.length;
  byId("single").hidden = !single;
  byId("more").hidden = single || photos.length <= state.shown;
  if (refreshGrid) {
    byId("grid").replaceChildren();
    if (!single) addCards(photos, 0);
  }
  if (single) renderPreview();
  renderInspector();
  updateActions();
}

function renderLibrary() {
  byId("folder-name").textContent = state.folder ? state.folder.split("/").filter(Boolean).at(-1) || "/" : t("noFolder");
  byId("folder-path").textContent = state.folder || "";
  const recent = byId("recent");
  recent.replaceChildren(new Option(t("recent"), ""), ...state.recent.map((path) => new Option(path, path)));
  recent.disabled = !state.recent.length || state.busy;
  renderContent();
}

async function refresh() {
  const library = await api("library");
  if (library.id !== state.id) {
    Object.assign(state, {selected: null, shown: pageSize, previewKey: "", mode: "grid"});
  }
  Object.assign(state, library);
  document.title = `PickUpPhoto ${state.version}`;
  renderLibrary();
}

function changeMode(mode) {
  state.mode = mode;
  renderContent();
}

function navigate(direction) {
  const photos = filtered();
  const index = photos.findIndex((photo) => photo.id === state.selected);
  const nextIndex = index + direction;
  const photo = photos[nextIndex];
  if (!photo) return;
  if (state.mode === "grid" && nextIndex >= state.shown) {
    state.shown = nextIndex + pageSize;
    renderContent();
  }
  selectPhoto(photo.id);
  if (state.mode === "grid") {
    byId("grid").querySelector(`[data-photo="${photo.id}"]`)?.scrollIntoView({block: "nearest"});
  }
}

async function rate(stars) {
  const photo = selectedPhoto();
  if (!photo || state.rating || state.stopped || state.busy) return;
  state.rating = true;
  try {
    await api("rate", {id: state.id, photo: photo.id, stars});
    photo.stars = stars;
    if (filtered().some((item) => item.id === photo.id) && byId("filter").value === ">=:0") {
      const card = byId("grid").querySelector(`[data-photo="${photo.id}"]`);
      if (card) cardRating(card, photo);
      renderInspector();
    } else {
      renderContent();
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    state.rating = false;
  }
}

function updateActions() {
  for (const id of ["open", "empty-open", "quit", "language"]) byId(id).disabled = state.busy || state.stopped;
  for (const id of ["analyze", "export"]) byId(id).disabled = state.busy || state.stopped || !state.photos.length;
  byId("recent").disabled = state.busy || state.stopped || !state.recent.length;
}

function jobStatus(job) {
  const progress = byId("progress");
  const text = {open: "scanning", analyze: "analyzing", export: "copying"};
  notice(t(text[job.kind]) + (job.total ? ` ${job.done}/${job.total}` : ""));
  progress.hidden = false;
  if (job.total) {
    progress.max = job.total;
    progress.value = job.done;
  } else progress.removeAttribute("value");
}

function jobResult(job) {
  const result = job.result || {};
  if (result.error) {
    notice(result.error, true);
  } else if (job.kind === "analyze") {
    notice(`${t("analyzed")} ${result.analyzed} · ${t("failed")} ${result.failed}`, Boolean(result.failed));
  } else if (job.kind === "export") {
    const errors = result.errors.map(([name, error]) => `${name} (${error})`).join(" · ");
    notice(`${t("copied")} ${result.copied} · ${t("skipped")} ${result.skipped} · ${t("failed")} ${result.failed}${errors ? " · " + errors : ""}`, Boolean(result.failed));
  } else notice();
}

async function watchJob() {
  let job;
  do {
    ({job} = await api("status"));
    if (job?.running) {
      jobStatus(job);
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
  } while (job?.running);
  byId("progress").hidden = true;
  if (job) {
    await refresh();
    jobResult(job);
  }
}

async function runJob(kind, data) {
  if (state.busy) return;
  state.busy = true;
  updateActions();
  try {
    await api(kind, data);
    await watchJob();
  } catch (error) {
    notice(error.message, true);
    byId("progress").hidden = true;
  } finally {
    state.busy = false;
    updateActions();
  }
}

async function browse(button, field, errorId) {
  const control = byId(button);
  control.disabled = true;
  formError(errorId, t("picking"));
  try {
    const {folder} = await api("choose", {});
    if (folder) byId(field).value = folder;
    formError(errorId);
  } catch (error) {
    formError(errorId, error.message);
  } finally {
    control.disabled = false;
  }
}

function updateExportCount() {
  const count = filtered(byId("export-filter").value).length;
  byId("export-count").textContent = `${count} ${t("unit")}`;
  byId("export-submit").disabled = !count;
}

function openDialog() {
  formError("folder-error");
  byId("folder-dialog").showModal();
}

for (let stars = 1; stars <= 5; stars += 1) {
  const button = document.createElement("button");
  button.type = "button";
  button.addEventListener("click", () => rate(stars));
  byId("stars").append(button);
}

byId("open").addEventListener("click", openDialog);
byId("empty-open").addEventListener("click", openDialog);
byId("folder-picker").addEventListener("click", () => browse("folder-picker", "folder-input", "folder-error"));
byId("export-picker").addEventListener("click", () => browse("export-picker", "export-folder", "export-error"));
document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => byId(button.dataset.close).close());
});
byId("folder-form").addEventListener("submit", (event) => {
  event.preventDefault();
  byId("folder-dialog").close();
  runJob("open", {folder: byId("folder-input").value});
});
byId("recent").addEventListener("change", (event) => {
  const folder = event.target.value;
  event.target.value = "";
  if (folder) runJob("open", {folder});
});
byId("analyze").addEventListener("click", () => runJob("analyze", {id: state.id}));
byId("export").addEventListener("click", () => {
  formError("export-error");
  updateExportCount();
  byId("export-dialog").showModal();
});
byId("export-filter").addEventListener("change", updateExportCount);
byId("export-form").addEventListener("submit", (event) => {
  event.preventDefault();
  byId("export-dialog").close();
  runJob("export", {
    id: state.id, folder: byId("export-folder").value, conflict: byId("conflict").value,
    ...filterParts(byId("export-filter").value),
  });
});
byId("quit").addEventListener("click", async () => {
  try {
    await api("quit", {});
    state.stopped = true;
    notice(t("stopped"));
    updateActions();
    renderInspector();
  } catch (error) {
    notice(error.message, true);
  }
});
byId("language").addEventListener("click", () => {
  lang = 1 - lang;
  sessionStorage.setItem("language", lang ? "en" : "zh-Hant");
  translate();
  renderLibrary();
});
byId("filter").addEventListener("change", () => {
  state.shown = pageSize;
  renderContent();
});
byId("grid-mode").addEventListener("click", () => changeMode("grid"));
byId("single-mode").addEventListener("click", () => changeMode("single"));
byId("prev").addEventListener("click", () => navigate(-1));
byId("next").addEventListener("click", () => navigate(1));
byId("decode").addEventListener("click", () => renderPreview("full"));
byId("unrate").addEventListener("click", () => rate(0));
byId("more").addEventListener("click", () => {
  const start = state.shown;
  state.shown += pageSize;
  const photos = filtered();
  addCards(photos, start);
  byId("more").hidden = photos.length <= state.shown;
  byId("grid").children[start]?.focus();
});
document.addEventListener("keydown", (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey
      || (event.target instanceof Element && event.target.closest("input, select, textarea, dialog, [contenteditable]"))) return;
  // Use the physical digit key when the active input method changes event.key.
  const digit = /^(?:Digit|Numpad)([0-5])$/.exec(event.code)?.[1]
    ?? (/^[0-5]$/.test(event.key) ? event.key : null);
  if (digit !== null && !event.shiftKey && !event.repeat) {
    event.preventDefault();
    rate(Number(digit));
  } else if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
    event.preventDefault();
    navigate(event.key === "ArrowLeft" ? -1 : 1);
  } else if (event.key === "Escape" && state.mode === "single") changeMode("grid");
});

translate();
try {
  await refresh();
  const {job} = await api("status");
  if (job?.running) {
    state.busy = true;
    updateActions();
    await watchJob();
    state.busy = false;
    updateActions();
  }
} catch (error) {
  state.stopped = true;
  notice(error.message || t("disconnected"), true);
  updateActions();
}
