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
  const exampleButtons = document.querySelectorAll("[data-question]");
  const modelOptions = document.querySelector("#model-options");
  const shutdownButton = document.querySelector("#shutdown-button");

  const statusFields = {
    header: document.querySelector("#header-status"),
    panel: document.querySelector("#panel-status"),
    ai: document.querySelector("#status-ai"),
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
    submitButton.disabled = isBusy;
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
      statusBadge(statusFields.header, healthy ? "success" : "error", healthy ? "시스템 정상" : "점검 필요");
      statusBadge(statusFields.panel, healthy ? "success" : "error", status.status);
      statusBadge(statusFields.ai, aiConnected ? "success" : "error", aiConnected ? "연결됨" : "연결 안 됨");
      statusBadge(statusFields.e4b, e4bAvailable ? "success" : "error", e4bAvailable ? "설치됨" : "미설치");
      statusBadge(statusFields.e2b, e2bAvailable ? "success" : "error", e2bAvailable ? "설치됨" : "미설치");
      renderModelOptions(status.models, status.default_model);
      statusFields.model.textContent = selectedModelLabel();
      statusFields.documents.textContent = `${formatNumber.format(status.source_documents)}개`;
      statusFields.sections.textContent = `${formatNumber.format(status.search_sections)}개`;
    } catch {
      statusBadge(statusFields.header, "error", "상태 확인 실패");
      statusBadge(statusFields.panel, "error", "확인 실패");
      statusBadge(statusFields.ai, "error", "확인 실패");
      statusBadge(statusFields.e4b, "error", "확인 실패");
      statusBadge(statusFields.e2b, "error", "확인 실패");
      statusFields.model.textContent = "확인할 수 없음";
      statusFields.documents.textContent = "확인할 수 없음";
      statusFields.sections.textContent = "확인할 수 없음";
    }
  }

  async function submitQuestion(event) {
    event.preventDefault();
    const value = validateQuestion();
    if (value === null) {
      return;
    }

    setBusy(true);
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
      answerDocument.innerHTML = payload.answer_html;
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
  form.addEventListener("submit", submitQuestion);
  clearButton.addEventListener("click", clearQuestion);
  shutdownButton.addEventListener("click", shutdownApplication);
  for (const button of exampleButtons) {
    button.addEventListener("click", () => {
      question.value = button.dataset.question ?? "";
      clearValidation();
      updateCount();
      question.focus();
    });
  }

  updateCount();
  void loadStatus();
})();
