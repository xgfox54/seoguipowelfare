(() => {
  "use strict";

  const form = document.querySelector("#question-form");
  const question = document.querySelector("#question");
  const count = document.querySelector("#question-count");
  const questionError = document.querySelector("#question-error");
  const submitButton = document.querySelector("#submit-button");
  const clearButton = document.querySelector("#clear-button");
  const emptyState = document.querySelector("#empty-state");
  const loadingState = document.querySelector("#loading-state");
  const errorState = document.querySelector("#error-state");
  const errorMessage = document.querySelector("#error-message");
  const answerDocument = document.querySelector("#answer-document");
  const resultHeading = document.querySelector("#result-heading");
  const answerElapsed = document.querySelector("#answer-elapsed");
  const resultSearchInput = document.querySelector("#result-search-input");
  const resultSearchCount = document.querySelector("#result-search-count");
  const resultSearchPrev = document.querySelector("#result-search-prev");
  const resultSearchNext = document.querySelector("#result-search-next");
  const exampleButtons = document.querySelectorAll("[data-question]");
  const modelOptions = document.querySelector("#model-options");
  const shutdownButton = document.querySelector("#shutdown-button");
  const setupSummary = document.querySelector("#setup-summary");
  const setupSummaryText = document.querySelector("#setup-summary-text");
  const setupGuideButton = document.querySelector("#setup-guide-button");
  const setupRefreshButton = document.querySelector("#setup-refresh-button");
  const setupDialog = document.querySelector("#setup-dialog");
  const setupDialogStatus = document.querySelector("#setup-dialog-status");
  const setupCloseButton = document.querySelector("#setup-close-button");
  const setupDialogDoneButton = document.querySelector("#setup-dialog-done-button");
  const setupDialogRefreshButton = document.querySelector("#setup-dialog-refresh-button");
  const ollamaDownloadButton = document.querySelector("#ollama-download-button");

  const statusFields = {
    header: document.querySelector("#header-status"),
    panel: document.querySelector("#panel-status"),
    ai: document.querySelector("#status-ai"),
    ollama: document.querySelector("#status-ollama"),
    e4b: document.querySelector("#status-e4b"),
    e2b: document.querySelector("#status-e2b"),
    model: document.querySelector("#status-model"),
    documents: document.querySelector("#status-documents"),
    sections: document.querySelector("#status-sections"),
  };

  const formatNumber = new Intl.NumberFormat("ko-KR");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let selectedModel = "gemma_e4b";
  let modelLabels = new Map();
  let answerStartedAt = 0;
  let answerTimerId = null;
  let aiReady = false;
  let setupDialogShownAutomatically = false;
  let resultSearchMatches = [];
  let resultSearchIndex = -1;

  function formatElapsed(milliseconds) {
    const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `답변에 걸린 시간: ${String(minutes).padStart(2, "0")}분 ${String(seconds).padStart(2, "0")}초`;
  }

  function updateElapsedTimer() {
    const elapsed = answerStartedAt > 0 ? performance.now() - answerStartedAt : 0;
    answerElapsed.textContent = formatElapsed(elapsed);
  }

  function startElapsedTimer() {
    if (answerTimerId !== null) {
      window.clearInterval(answerTimerId);
    }
    answerStartedAt = performance.now();
    updateElapsedTimer();
    answerTimerId = window.setInterval(updateElapsedTimer, 1000);
  }

  function stopElapsedTimer() {
    updateElapsedTimer();
    if (answerTimerId !== null) {
      window.clearInterval(answerTimerId);
      answerTimerId = null;
    }
  }

  function resetElapsedTimer() {
    if (answerTimerId !== null) {
      window.clearInterval(answerTimerId);
      answerTimerId = null;
    }
    answerStartedAt = 0;
    answerElapsed.textContent = formatElapsed(0);
  }

  function clearResultSearchMarks() {
    for (const mark of answerDocument.querySelectorAll("mark[data-result-search-match]")) {
      mark.replaceWith(document.createTextNode(mark.textContent ?? ""));
    }
    answerDocument.normalize();
    resultSearchMatches = [];
    resultSearchIndex = -1;
  }

  function updateResultSearchControls() {
    const hasMatches = resultSearchMatches.length > 0;
    resultSearchPrev.disabled = !hasMatches;
    resultSearchNext.disabled = !hasMatches;
    resultSearchCount.textContent = hasMatches
      ? `${resultSearchIndex + 1} / ${resultSearchMatches.length}`
      : "0 / 0";
  }

  function resetResultSearch({ disabled = false } = {}) {
    clearResultSearchMarks();
    resultSearchInput.value = "";
    resultSearchInput.disabled = disabled;
    updateResultSearchControls();
  }

  function activateResultSearchMatch(index, { scroll = true } = {}) {
    if (resultSearchMatches.length === 0) {
      resultSearchIndex = -1;
      updateResultSearchControls();
      return;
    }

    for (const mark of resultSearchMatches) {
      mark.classList.remove("is-active");
    }
    resultSearchIndex = (index + resultSearchMatches.length) % resultSearchMatches.length;
    const activeMatch = resultSearchMatches[resultSearchIndex];
    activeMatch.classList.add("is-active");
    updateResultSearchControls();
    if (scroll) {
      activeMatch.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "center",
      });
    }
  }

  function highlightResultSearch(query) {
    clearResultSearchMarks();
    const searchTerm = query.trim();
    if (!searchTerm || answerDocument.hidden) {
      updateResultSearchControls();
      return;
    }

    const escaped = searchTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const nodes = [];
    const walker = document.createTreeWalker(answerDocument, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeValue && node.nodeValue.trim()) {
        nodes.push(node);
      }
    }

    for (const node of nodes) {
      const pattern = new RegExp(escaped, "gi");
      const text = node.nodeValue ?? "";
      if (!pattern.test(text)) {
        continue;
      }
      pattern.lastIndex = 0;
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      let match = pattern.exec(text);
      while (match !== null) {
        fragment.append(document.createTextNode(text.slice(cursor, match.index)));
        const mark = document.createElement("mark");
        mark.className = "result-search-mark";
        mark.dataset.resultSearchMatch = "true";
        mark.textContent = match[0];
        fragment.append(mark);
        resultSearchMatches.push(mark);
        cursor = match.index + match[0].length;
        match = pattern.exec(text);
      }
      fragment.append(document.createTextNode(text.slice(cursor)));
      node.replaceWith(fragment);
    }

    if (resultSearchMatches.length > 0) {
      activateResultSearchMatch(0);
    } else {
      updateResultSearchControls();
    }
  }

  function selectedModelLabel() {
    return modelLabels.get(selectedModel) ?? selectedModel;
  }

  function renderModelOptions(models, defaultModel) {
    modelLabels = new Map(models.map((model) => [model.key, model.label]));
    const firstAvailable = models.find((model) => model.available);
    const preferred = models.find((model) => model.key === defaultModel);
    selectedModel = preferred?.available ? preferred.key : firstAvailable?.key ?? defaultModel;
    modelOptions.replaceChildren();

    for (const model of models) {
      const option = document.createElement("label");
      option.className = "model-option";

      const input = document.createElement("input");
      input.type = "radio";
      input.name = "model";
      input.value = model.key;
      input.className = "model-option__input";
      input.checked = model.key === selectedModel;
      input.disabled = !model.available;
      input.dataset.unavailable = String(!model.available);
      input.addEventListener("change", () => {
        selectedModel = model.key;
        statusFields.model.textContent = model.label;
      });

      const body = document.createElement("span");
      body.className = "model-option__body";

      const name = document.createElement("span");
      name.className = "model-option__name";
      name.textContent = model.label;

      const runtime = document.createElement("span");
      runtime.className = "model-option__runtime";
      runtime.textContent = model.runtime;

      const description = document.createElement("span");
      description.className = "model-option__description";
      description.textContent = model.available
        ? model.description
        : model.unavailable_reason;

      body.append(name, runtime, description);
      option.append(input, body);
      modelOptions.append(option);
    }
  }

  function updateCount() {
    count.textContent = `${formatNumber.format(question.value.length)} / 2,000`;
  }

  function clearValidation() {
    question.removeAttribute("aria-invalid");
    questionError.hidden = true;
    questionError.textContent = "";
  }

  function validateQuestion() {
    const value = question.value.trim();
    if (value.length < 2) {
      question.setAttribute("aria-invalid", "true");
      questionError.textContent = "질문을 2자 이상 입력하세요.";
      questionError.hidden = false;
      question.focus();
      return null;
    }
    clearValidation();
    return value;
  }

  function showOnly(target) {
    for (const state of [emptyState, loadingState, errorState, answerDocument]) {
      state.hidden = state !== target;
    }
  }

  function setBusy(isBusy) {
    question.disabled = isBusy;
    clearButton.disabled = isBusy;
    for (const button of exampleButtons) {
      button.disabled = isBusy;
    }
    for (const input of modelOptions.querySelectorAll("input")) {
      input.disabled = isBusy || input.dataset.unavailable === "true";
    }
    submitButton.disabled = isBusy || !aiReady;
    submitButton.setAttribute("aria-busy", String(isBusy));
    submitButton.innerHTML = isBusy
      ? '<span class="spinner" aria-hidden="true"></span>확인 중'
      : "질문하기";
  }

  function statusBadge(element, kind, text) {
    element.className = `status-badge status-badge--${kind}`;
    element.textContent = text;
  }

  function modelAvailability(status, key) {
    return status.models.find((model) => model.key === key)?.available === true;
  }

  function installationStatusText(status) {
    if (!status.ollama_installed) {
      return "Ollama가 설치되어 있지 않습니다. Ollama 설치 후 기본 모델 E4B를 내려받아 주세요.";
    }
    if (!status.ollama_running) {
      return "Ollama는 설치되어 있지만 현재 실행되고 있지 않습니다. 프로그램을 종료한 뒤 다시 실행해 주세요.";
    }
    if (!status.ai_ready) {
      return "Ollama는 정상 실행 중이지만 사용할 수 있는 Gemma 모델이 없습니다. E4B 또는 E2B 모델을 설치해 주세요.";
    }
    const missing = status.models.filter((model) => !model.available).map((model) => model.label);
    return missing.length > 0
      ? `AI는 사용 가능합니다. 추가로 설치하지 않은 모델: ${missing.join(", ")}`
      : "Ollama와 로컬 모델이 정상적으로 설치되어 있습니다.";
  }

  function updateSetupGuide(status) {
    const message = installationStatusText(status);
    setupSummary.hidden = !status.setup_required;
    setupSummaryText.textContent = message;
    setupDialogStatus.textContent = message;
    setupDialogStatus.classList.toggle("is-ready", status.ai_ready === true);
    if (status.setup_required && !setupDialogShownAutomatically && !setupDialog.open) {
      setupDialogShownAutomatically = true;
      setupDialog.showModal();
    }
  }

  async function loadStatus() {
    try {
      const response = await fetch("/api/status", { headers: { Accept: "application/json" } });
      if (!response.ok) {
        throw new Error("시스템 상태 응답 오류");
      }
      const status = await response.json();
      const healthy = status.status === "정상";
      const e4bAvailable = modelAvailability(status, "gemma_e4b");
      const e2bAvailable = modelAvailability(status, "gemma_e2b");
      const aiConnected = e4bAvailable || e2bAvailable;
      aiReady = status.ai_ready === true;
      const systemReady = healthy && aiReady;
      statusBadge(statusFields.header, systemReady ? "success" : "error", systemReady ? "시스템 정상" : aiReady ? "DB 점검 필요" : "AI 설치 필요");
      statusBadge(statusFields.panel, systemReady ? "success" : "error", systemReady ? "정상" : aiReady ? status.status : "설치 필요");
      statusBadge(statusFields.ai, aiConnected ? "success" : "error", aiConnected ? "연결됨" : "연결 안 됨");
      statusBadge(
        statusFields.ollama,
        status.ollama_running ? "success" : status.ollama_installed ? "warning" : "error",
        status.ollama_running ? "설치됨 · 실행 중" : status.ollama_installed ? "설치됨 · 실행 필요" : "미설치",
      );
      statusBadge(statusFields.e4b, e4bAvailable ? "success" : "error", e4bAvailable ? "설치됨" : "미설치");
      statusBadge(statusFields.e2b, e2bAvailable ? "success" : "error", e2bAvailable ? "설치됨" : "미설치");
      renderModelOptions(status.models, status.default_model);
      statusFields.model.textContent = selectedModelLabel();
      statusFields.documents.textContent = `${formatNumber.format(status.source_documents)}개`;
      statusFields.sections.textContent = `${formatNumber.format(status.search_sections)}개`;
      updateSetupGuide(status);
      setBusy(false);
    } catch {
      aiReady = false;
      statusBadge(statusFields.header, "error", "상태 확인 실패");
      statusBadge(statusFields.panel, "error", "확인 실패");
      statusBadge(statusFields.ai, "error", "확인 실패");
      statusBadge(statusFields.ollama, "error", "확인 실패");
      statusBadge(statusFields.e4b, "error", "확인 실패");
      statusBadge(statusFields.e2b, "error", "확인 실패");
      statusFields.model.textContent = "확인할 수 없음";
      statusFields.documents.textContent = "확인할 수 없음";
      statusFields.sections.textContent = "확인할 수 없음";
      setupSummary.hidden = false;
      setupSummaryText.textContent = "설치 상태를 확인할 수 없습니다. 프로그램을 다시 실행해 주세요.";
      setBusy(false);
    }
  }

  function showSetupDialog() {
    if (!setupDialog.open) {
      setupDialog.showModal();
    }
  }

  async function refreshSetupStatus() {
    setupRefreshButton.disabled = true;
    setupDialogRefreshButton.disabled = true;
    try {
      await loadStatus();
    } finally {
      setupRefreshButton.disabled = false;
      setupDialogRefreshButton.disabled = false;
    }
  }

  async function openOllamaDownload() {
    if (window.pywebview?.api?.open_ollama_download) {
      await window.pywebview.api.open_ollama_download();
      return;
    }
    window.open("https://ollama.com/download/windows", "_blank", "noopener");
  }

  async function copyCommand(button) {
    const command = button.dataset.copyCommand ?? "";
    if (!command) {
      return;
    }
    try {
      await navigator.clipboard.writeText(command);
      const original = button.textContent;
      button.textContent = "복사됨";
      window.setTimeout(() => {
        button.textContent = original;
      }, 1200);
    } catch {
      button.textContent = "복사 실패";
    }
  }

  async function submitQuestion(event) {
    event.preventDefault();
    const value = validateQuestion();
    if (value === null) {
      return;
    }

    setBusy(true);
    resetResultSearch({ disabled: true });
    startElapsedTimer();
    showOnly(loadingState);
    resultHeading.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start",
    });

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question: value, model: selectedModel }),
      });
      if (!response.ok) {
        throw new Error(response.status === 422 ? "질문 내용을 확인해 주세요." : "복지DB 답변 생성에 실패했습니다.");
      }
      const payload = await response.json();
      stopElapsedTimer();
      answerDocument.innerHTML = payload.answer_html;
      resetResultSearch({ disabled: false });
      statusFields.model.textContent = payload.model_label;
      showOnly(answerDocument);
      resultHeading.focus({ preventScroll: true });
    } catch (error) {
      const knownMessage = error instanceof Error && (
        error.message === "질문 내용을 확인해 주세요." ||
        error.message === "복지DB 답변 생성에 실패했습니다."
      );
      errorMessage.textContent = knownMessage
        ? error.message
        : "서버 연결 상태를 확인한 뒤 다시 시도해 주세요.";
      stopElapsedTimer();
      resetResultSearch({ disabled: true });
      showOnly(errorState);
      errorState.focus({ preventScroll: true });
    } finally {
      setBusy(false);
    }
  }

  function clearQuestion() {
    question.value = "";
    clearValidation();
    updateCount();
    resetElapsedTimer();
    resetResultSearch({ disabled: true });
    showOnly(emptyState);
    question.focus();
  }

  async function shutdownApplication() {
    shutdownButton.disabled = true;
    shutdownButton.textContent = "종료 중";
    try {
      await fetch("/api/shutdown", { method: "POST" });
      if (window.pywebview?.api?.close_app) {
        await window.pywebview.api.close_app();
        return;
      }
      document.body.innerHTML = '<main class="container page-main"><section class="card"><h1 class="page-title">복지업무 비서를 종료했습니다</h1><p class="page-summary">이 창을 닫아도 됩니다. 다시 사용하려면 EXE 파일을 실행하세요.</p></section></main>';
    } catch {
      shutdownButton.disabled = false;
      shutdownButton.textContent = "프로그램 종료";
    }
  }

  question.addEventListener("input", () => {
    clearValidation();
    updateCount();
  });
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit(submitButton);
    }
  });
  resultSearchInput.addEventListener("input", () => {
    highlightResultSearch(resultSearchInput.value);
  });
  resultSearchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && resultSearchMatches.length > 0) {
      event.preventDefault();
      activateResultSearchMatch(resultSearchIndex + (event.shiftKey ? -1 : 1));
    }
  });
  resultSearchPrev.addEventListener("click", () => {
    activateResultSearchMatch(resultSearchIndex - 1);
  });
  resultSearchNext.addEventListener("click", () => {
    activateResultSearchMatch(resultSearchIndex + 1);
  });
  form.addEventListener("submit", submitQuestion);
  clearButton.addEventListener("click", clearQuestion);
  shutdownButton.addEventListener("click", shutdownApplication);
  setupGuideButton.addEventListener("click", showSetupDialog);
  setupRefreshButton.addEventListener("click", refreshSetupStatus);
  setupDialogRefreshButton.addEventListener("click", refreshSetupStatus);
  setupCloseButton.addEventListener("click", () => setupDialog.close());
  setupDialogDoneButton.addEventListener("click", () => setupDialog.close());
  ollamaDownloadButton.addEventListener("click", openOllamaDownload);
  for (const button of document.querySelectorAll("[data-copy-command]")) {
    button.addEventListener("click", () => copyCommand(button));
  }
  for (const button of exampleButtons) {
    button.addEventListener("click", () => {
      question.value = button.dataset.question ?? "";
      clearValidation();
      updateCount();
      question.focus();
    });
  }

  updateCount();
  resetResultSearch({ disabled: true });
  void loadStatus();
})();
