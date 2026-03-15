import { createApp, ref, reactive, computed, nextTick, onMounted, onBeforeUnmount } from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";
import { DEFAULT_SETTINGS, LOCAL_KEYS, SESSION_PAGE_SIZE, MAX_PREVIEW_LEN } from "./constants.js";
import { safeText, validateIdentifier, sanitizeIntent, normalizeErrorMessage, validateConfirmPreview } from "./utils.js";
import { loadLocalSessions, saveLocalSession, buildSessionTitle } from "./sessionStore.js";
import {
  streamChat,
  streamConfirm,
  cancelPending,
  listTables,
  getTableData,
  deleteTable,
  createTable,
  getConfig,
  saveConfigBatch,
  testConfigConnection,
} from "./services.js";

function buildSessionId() {
  return `session_${Math.random().toString(36).slice(2, 10)}`;
}

createApp({
  setup() {
    const userInput = ref("");
    const statusText = ref("就绪");
    const isLoading = ref(false);

    const sessionId = ref(buildSessionId());
    const visibleSessionCount = ref(SESSION_PAGE_SIZE);
    const persistedSessions = ref(loadLocalSessions());

    const allTables = ref([]);
    const currentTable = ref("");
    const tableData = reactive({ table: "", columns: [], rows: [] });
    const tableLoadingText = ref("");

    const chatItems = ref([]);
    const activeStepsId = ref("");
    const activeAssistantMessageId = ref("");

    const settings = reactive({ ...DEFAULT_SETTINGS });

    const createModalOpen = ref(false);
    const settingsModalOpen = ref(false);
    const createForm = reactive({
      table_name: "",
      description: "",
      aliases: "",
      columns: [],
    });

    const inputRef = ref(null);

    const LEFT_PANE_WIDTH = 232;
    const SPLITTER_WIDTH = 8;
    const CENTER_PANE_DEFAULT_WIDTH = 320;
    const CENTER_PANE_MIN_WIDTH = 280;
    const RIGHT_PANE_MIN_WIDTH = 460;

    const historyPaneVisible = ref(true);
    const centerPaneWidth = ref(CENTER_PANE_DEFAULT_WIDTH);
    const isDraggingSplitter = ref(false);
    let resizeStartX = 0;
    let resizeStartWidth = CENTER_PANE_DEFAULT_WIDTH;

    const displayedSessions = computed(() => {
      const existed = persistedSessions.value.find((s) => s.id === sessionId.value);
      const current = {
        id: sessionId.value,
        title: existed?.title || "当前会话",
        preview: getCurrentPreview(),
        timestamp: new Date().toISOString(),
      };
      const merged = [current, ...persistedSessions.value.filter((s) => s.id !== sessionId.value)];
      return merged.slice(0, visibleSessionCount.value);
    });

    const remainingSessionCount = computed(() => {
      const currentTotal = 1 + persistedSessions.value.filter((s) => s.id !== sessionId.value).length;
      return Math.max(0, currentTotal - displayedSessions.value.length);
    });

    const currentSessionTitle = computed(() => {
      const matched = displayedSessions.value.find((s) => s.id === sessionId.value)
        || persistedSessions.value.find((s) => s.id === sessionId.value);
      const title = safeText(matched?.title || "").trim();
      return title || "当前会话";
    });

    const mainStyle = computed(() => {
      const leftPaneWidth = historyPaneVisible.value ? LEFT_PANE_WIDTH : 0;
      return {
        "--left-pane-width": `${leftPaneWidth}px`,
        "--center-pane-width": `${centerPaneWidth.value}px`,
      };
    });

    function applyTheme(theme) {
      const finalTheme = theme === "light" ? "light" : "dark";
      document.body.classList.toggle("theme-light", finalTheme === "light");
      localStorage.setItem(LOCAL_KEYS.theme, finalTheme);
      settings.theme = finalTheme;
    }

    function setStatus(text) {
      statusText.value = text;
    }

    function buildId(prefix) {
      return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
    }

    function addMessage(role, text, intent = "", className = "") {
      const item = {
        id: buildId("msg"),
        type: "message",
        role,
        text: safeText(text),
        intent: sanitizeIntent(intent),
        className,
      };
      chatItems.value.push(item);
      scrollChatToBottom();
      return item;
    }

    function addStepsContainer() {
      const item = {
        id: buildId("steps"),
        type: "steps",
        steps: [],
      };
      chatItems.value.push(item);
      activeStepsId.value = item.id;
      scrollChatToBottom();
      return item;
    }

    function findItem(itemId) {
      return chatItems.value.find((item) => item.id === itemId);
    }

    function addStep(label, extra = {}) {
      const container = findItem(activeStepsId.value);
      if (!container || container.type !== "steps") return;

      container.steps.forEach((step) => {
        if (step.status === "active") step.status = "done";
      });

      const agent = safeText(extra.agent || "").trim();
      const phase = safeText(extra.phase || "").trim();
      const parts = [safeText(label).trim()].filter(Boolean);
      if (agent) parts.push(`· ${agent}`);
      if (phase) parts.push(`· ${phase}`);

      container.steps.push({
        label: parts.join(" "),
        status: "active",
      });
      scrollChatToBottom();
    }

    function finalizeSteps() {
      const container = findItem(activeStepsId.value);
      if (!container || container.type !== "steps") return;
      container.steps.forEach((step) => {
        if (step.status === "active") step.status = "done";
      });
    }

    async function applyStepPatch(patch) {
      if (!patch || typeof patch !== "object") return;

      const patchType = safeText(patch.type).trim();
      if (!patchType) return;

      if (patchType === "active_table") {
        const table = safeText(patch.table).trim();
        if (table) {
          currentTable.value = table;
          await loadTableData(table);
        }
        return;
      }

      if (patchType === "table_overview") {
        await loadTablesAndMaybeData();
        return;
      }

      if (patchType === "schema" || patchType === "rows") {
        const table = safeText(patch.table || currentTable.value).trim();
        if (table) {
          currentTable.value = table;
          await loadTableData(table);
        } else {
          await loadTablesAndMaybeData();
        }
      }
    }

    async function applyDoneRefreshHint(hint, fallbackIntent = "", activeTable = "") {
      const active = safeText(activeTable).trim();
      if (active) {
        currentTable.value = active;
      }

      if (hint && typeof hint === "object" && hint.refresh) {
        const patchType = safeText(hint.patch_type || hint.hint || "").trim();
        const table = safeText(hint.table || currentTable.value).trim();

        if (patchType === "table_overview") {
          await loadTablesAndMaybeData();
          return;
        }

        if (patchType === "active_table" && table) {
          currentTable.value = table;
          await loadTableData(table);
          return;
        }

        if (table) {
          currentTable.value = table;
          await loadTableData(table);
        } else {
          await loadTablesAndMaybeData();
        }
        return;
      }

      const intent = sanitizeIntent(fallbackIntent || "");
      if (["create_table", "drop_table", "alter_table", "add_col", "drop_col", "rename_col", "list_tables"].includes(intent)) {
        await loadTablesAndMaybeData();
        return;
      }
      if (["insert", "update", "delete_data", "row_insert", "row_update", "row_delete", "cell_update"].includes(intent) && currentTable.value) {
        await loadTableData(currentTable.value);
      }
    }

    function startAssistantStreamBubble() {
      const item = addMessage("assistant", "");
      activeAssistantMessageId.value = item.id;
    }

    function appendAssistantToken(content) {
      const item = findItem(activeAssistantMessageId.value);
      if (!item || item.type !== "message") return;
      item.text += safeText(content);
      scrollChatToBottom();
    }

    function attachIntentMeta(intent) {
      const normalized = sanitizeIntent(intent);
      if (!normalized) return;
      const item = findItem(activeAssistantMessageId.value);
      if (!item || item.type !== "message") return;
      item.intent = normalized;
    }

    function getCurrentPreview() {
      const last = [...chatItems.value].reverse().find((item) => item.type === "message");
      if (!last) return "空会话";
      const text = safeText(last.text).replace(/\s+/g, " ").trim();
      if (!text) return "空会话";
      return text.length > MAX_PREVIEW_LEN ? `${text.slice(0, MAX_PREVIEW_LEN)}...` : text;
    }

    function snapshotCurrentSession() {
      saveLocalSession(
        {
          id: sessionId.value,
          title: buildSessionTitle(sessionId.value),
          preview: getCurrentPreview(),
          timestamp: new Date().toISOString(),
        },
        settings.session_limit
      );
      persistedSessions.value = loadLocalSessions();
    }

    function resetChatWindow(welcomeText, clearHistory = false) {
      chatItems.value = [];
      addMessage("assistant", welcomeText);
      activeStepsId.value = "";
      activeAssistantMessageId.value = "";
      if (clearHistory) {
        currentTable.value = "";
      }
    }

    function createNewSession() {
      snapshotCurrentSession();
      sessionId.value = buildSessionId();
      visibleSessionCount.value = SESSION_PAGE_SIZE;
      resetChatWindow("你好，我准备好了。请告诉我你要进行的数据库操作。", true);
      setStatus("新会话已创建");
      loadTablesAndMaybeData();
    }

    function switchSession(nextId) {
      if (!nextId || nextId === sessionId.value) return;
      snapshotCurrentSession();
      sessionId.value = nextId;
      resetChatWindow("已切换会话，继续输入即可。", false);
      setStatus("会话已切换");
      loadTablesAndMaybeData();
    }

    function loadMoreSessions() {
      visibleSessionCount.value += SESSION_PAGE_SIZE;
      localStorage.setItem(LOCAL_KEYS.paneLimit, String(visibleSessionCount.value));
    }

    function clampCenterPaneWidth(rawWidth) {
      const viewportWidth = window.innerWidth || 0;
      const leftPaneWidth = historyPaneVisible.value ? LEFT_PANE_WIDTH : 0;
      const maxWidth = Math.max(
        CENTER_PANE_MIN_WIDTH,
        viewportWidth - leftPaneWidth - RIGHT_PANE_MIN_WIDTH - SPLITTER_WIDTH
      );
      return Math.min(maxWidth, Math.max(CENTER_PANE_MIN_WIDTH, Math.round(rawWidth)));
    }

    function toggleHistoryPane() {
      historyPaneVisible.value = !historyPaneVisible.value;
      centerPaneWidth.value = clampCenterPaneWidth(centerPaneWidth.value);
      localStorage.setItem(LOCAL_KEYS.historyPaneVisible, historyPaneVisible.value ? "1" : "0");
      localStorage.setItem(LOCAL_KEYS.centerPaneWidth, String(centerPaneWidth.value));
    }

    function startResize(event) {
      if (window.innerWidth <= 980 || event.button !== 0) return;
      event.preventDefault();
      isDraggingSplitter.value = true;
      resizeStartX = event.clientX;
      resizeStartWidth = centerPaneWidth.value;
    }

    function onResizeMove(event) {
      if (!isDraggingSplitter.value) return;
      const deltaX = event.clientX - resizeStartX;
      centerPaneWidth.value = clampCenterPaneWidth(resizeStartWidth + deltaX);
    }

    function stopResize() {
      if (!isDraggingSplitter.value) return;
      isDraggingSplitter.value = false;
      localStorage.setItem(LOCAL_KEYS.centerPaneWidth, String(centerPaneWidth.value));
    }

    function onWindowResize() {
      centerPaneWidth.value = clampCenterPaneWidth(centerPaneWidth.value);
    }

    function addConfirmCard(previewText, intent) {
      const item = {
        id: buildId("confirm"),
        type: "confirm",
        previewText: safeText(previewText),
        intent: sanitizeIntent(intent),
        inlineError: "",
        busy: false,
      };
      chatItems.value.push(item);
      scrollChatToBottom();
      return item;
    }

    function removeChatItem(itemId) {
      chatItems.value = chatItems.value.filter((item) => item.id !== itemId);
    }

    function appendError(message, hint = "") {
      const text = hint ? `${message}\n\n建议：${hint}` : message;
      addMessage("assistant", text, "", "error");
    }

    function appendSuccess(message) {
      addMessage("assistant", message, "", "success");
    }

    async function loadSettings() {
      let backendConfig = {};
      try {
        backendConfig = await getConfig();
      } catch {
        backendConfig = {};
      }

      settings.api_base_url = backendConfig.openai_base_url || localStorage.getItem("api_base_url") || window.location.origin;
      settings.api_key = localStorage.getItem("api_key") || "";
      settings.model_id = backendConfig.openai_model || localStorage.getItem("model_id") || DEFAULT_SETTINGS.model_id;
      settings.temperature = Number(backendConfig.temperature ?? localStorage.getItem("temperature") ?? DEFAULT_SETTINGS.temperature);
      settings.max_history_length = Number(backendConfig.max_history_length ?? localStorage.getItem("max_history_length") ?? DEFAULT_SETTINGS.max_history_length);
      settings.theme = localStorage.getItem(LOCAL_KEYS.theme) || DEFAULT_SETTINGS.theme;
      settings.session_limit = Number(localStorage.getItem(LOCAL_KEYS.sessionLimit) || DEFAULT_SETTINGS.session_limit);

      applyTheme(settings.theme);
    }

    async function saveSettings() {
      if (!settings.api_base_url.startsWith("http://") && !settings.api_base_url.startsWith("https://")) {
        appendError("API 端点必须以 http:// 或 https:// 开头");
        return;
      }

      if (Number.isNaN(settings.temperature) || settings.temperature < 0 || settings.temperature > 2) {
        appendError("温度必须在 0.0 到 2.0 之间");
        return;
      }

      if (
        Number.isNaN(settings.max_history_length) ||
        settings.max_history_length < 1 ||
        settings.max_history_length > 200
      ) {
        appendError("历史长度必须在 1 到 200 之间");
        return;
      }

      try {
        await saveConfigBatch(settings);
        localStorage.setItem("api_base_url", settings.api_base_url);
        localStorage.setItem("api_key", settings.api_key);
        localStorage.setItem("model_id", settings.model_id);
        localStorage.setItem("temperature", String(settings.temperature));
        localStorage.setItem("max_history_length", String(settings.max_history_length));
        localStorage.setItem(LOCAL_KEYS.theme, settings.theme);
        localStorage.setItem(LOCAL_KEYS.sessionLimit, String(settings.session_limit));

        applyTheme(settings.theme);
        persistedSessions.value = loadLocalSessions();

        appendSuccess("设置已保存，新对话会立即使用新模型参数。");
        setStatus("设置已保存");
      } catch (err) {
        appendError(normalizeErrorMessage(err.message), "检查 API 端点、模型 ID 或密钥是否正确。");
        setStatus("设置保存失败");
      }
    }

    async function testSettings() {
      setStatus("正在测试连接...");
      try {
        const result = await testConfigConnection(settings);
        appendSuccess(`连接成功：${result.message || "模型可用"}`);
        setStatus("连接测试成功");
      } catch (err) {
        appendError(normalizeErrorMessage(err.message), "如果是本地模型，请确认服务已启动且端点可访问。");
        setStatus("连接测试失败");
      }
    }

    function resetSettings() {
      localStorage.removeItem("api_base_url");
      localStorage.removeItem("api_key");
      localStorage.removeItem("model_id");
      localStorage.removeItem("temperature");
      localStorage.removeItem("max_history_length");
      localStorage.setItem(LOCAL_KEYS.theme, DEFAULT_SETTINGS.theme);
      localStorage.setItem(LOCAL_KEYS.sessionLimit, String(DEFAULT_SETTINGS.session_limit));

      Object.assign(settings, DEFAULT_SETTINGS);
      applyTheme(DEFAULT_SETTINGS.theme);
      persistedSessions.value = loadLocalSessions();
      setStatus("本地设置已恢复默认");
      appendSuccess("本地设置已恢复默认。后端配置可在保存时覆盖。");
    }

    async function loadTablesAndMaybeData() {
      try {
        allTables.value = await listTables();

        if (!allTables.value.length) {
          currentTable.value = "";
          tableData.table = "";
          tableData.columns = [];
          tableData.rows = [];
          tableLoadingText.value = "暂无表。点击“新建表”开始。";
          return;
        }

        const names = allTables.value.map((t) => t.name);
        if (!currentTable.value || !names.includes(currentTable.value)) {
          currentTable.value = names[0];
        }

        await loadTableData(currentTable.value);
      } catch (err) {
        tableLoadingText.value = "加载表列表失败";
        appendError(normalizeErrorMessage(err.message), "请确认后端服务已启动。");
      }
    }

    async function loadTableData(tableName) {
      if (!tableName) {
        tableLoadingText.value = "请选择要查看的数据表";
        return;
      }

      currentTable.value = tableName;
      tableLoadingText.value = "加载中...";
      try {
        const data = await getTableData(tableName);
        tableData.table = data.table;
        tableData.columns = data.columns || [];
        tableData.rows = data.rows || [];
        tableLoadingText.value = "";
      } catch (err) {
        tableData.table = "";
        tableData.columns = [];
        tableData.rows = [];
        tableLoadingText.value = "加载表数据失败";
        appendError(normalizeErrorMessage(err.message));
      }
    }

    async function refreshTable() {
      if (currentTable.value) {
        await loadTableData(currentTable.value);
      } else {
        await loadTablesAndMaybeData();
      }
    }

    async function deleteCurrentTable() {
      if (!currentTable.value) return;
      if (!window.confirm(`确认删除表「${currentTable.value}」？此操作不可恢复。`)) return;

      try {
        const result = await deleteTable(currentTable.value);
        appendSuccess(result.message || `已删除表 ${currentTable.value}`);
        currentTable.value = "";
        await loadTablesAndMaybeData();
      } catch (err) {
        appendError(normalizeErrorMessage(err.message));
      }
    }

    function openCreateModal() {
      createForm.table_name = "";
      createForm.description = "";
      createForm.aliases = "";
      createForm.columns = [];
      addColumnRow();
      createModalOpen.value = true;
    }

    function closeCreateModal() {
      createModalOpen.value = false;
    }

    function addColumnRow() {
      createForm.columns.push({
        id: buildId("col"),
        name: "",
        type: "TEXT",
        notnull: false,
      });
    }

    function removeColumnRow(columnId) {
      createForm.columns = createForm.columns.filter((col) => col.id !== columnId);
    }

    async function submitCreateTable() {
      const tableName = safeText(createForm.table_name).trim();
      if (!tableName) {
        appendError("请输入表名");
        return;
      }
      if (!validateIdentifier(tableName)) {
        appendError("表名仅允许中文/字母/数字/下划线，且不能以数字开头");
        return;
      }

      const columns = [];
      for (const row of createForm.columns) {
        const name = safeText(row.name).trim();
        const type = safeText(row.type).trim().toUpperCase() || "TEXT";
        const notnull = Boolean(row.notnull);

        if (!name) {
          appendError("字段名不能为空");
          return;
        }
        if (!validateIdentifier(name)) {
          appendError(`字段名不合法：${name}`);
          return;
        }
        if (!["TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"].includes(type)) {
          appendError(`字段类型不支持：${type}`);
          return;
        }

        columns.push({ name, type, notnull });
      }

      if (!columns.length) {
        appendError("请至少添加一个字段");
        return;
      }

      const payload = {
        table_name: tableName,
        description: safeText(createForm.description).trim(),
        aliases: safeText(createForm.aliases)
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        columns,
      };

      try {
        const result = await createTable(payload);
        closeCreateModal();
        appendSuccess(result.message || `表 ${tableName} 创建成功`);
        await loadTablesAndMaybeData();
        await loadTableData(tableName);
      } catch (err) {
        appendError(normalizeErrorMessage(err.message));
      }
    }

    async function handleConfirmRun(cardId) {
      const card = findItem(cardId);
      if (!card || card.type !== "confirm" || card.busy) return;

      const validation = validateConfirmPreview(card.intent, card.previewText);
      if (!validation.ok) {
        card.inlineError = validation.reason;
        return;
      }

      card.inlineError = "";
      card.busy = true;
      addMessage("user", "确认执行");

      addStepsContainer();
      let finalIntent = "";
      let donePayload = {};

      try {
        await streamConfirm(sessionId.value, {
          step: (d) => {
            addStep(d.label || d.node || "处理中", { agent: d.agent, phase: d.phase });
            if (d.patch) {
              applyStepPatch(d.patch).catch((err) => {
                appendError(normalizeErrorMessage(err.message));
              });
            }
          },
          response_start: () => {
            finalizeSteps();
            startAssistantStreamBubble();
          },
          token: (d) => appendAssistantToken(d.content),
          error: (d) => {
            finalizeSteps();
            appendError(normalizeErrorMessage(d.message));
          },
          done: (d) => {
            finalizeSteps();
            finalIntent = sanitizeIntent(d.intent || "");
            donePayload = d || {};
          },
        });

        await applyDoneRefreshHint(donePayload.refresh_hint, finalIntent, donePayload.active_table || "");

        removeChatItem(cardId);
      } catch (err) {
        card.inlineError = normalizeErrorMessage(err.message);
      } finally {
        card.busy = false;
      }
    }

    async function handleConfirmCancel(cardId) {
      const card = findItem(cardId);
      if (!card || card.type !== "confirm" || card.busy) return;

      card.inlineError = "";
      card.busy = true;
      try {
        await cancelPending(sessionId.value);
        removeChatItem(cardId);
        addMessage("assistant", "操作已取消。");
      } catch (err) {
        card.inlineError = normalizeErrorMessage(err.message);
      } finally {
        card.busy = false;
      }
    }

    async function sendMessage() {
      const text = safeText(userInput.value).trim();
      if (!text || isLoading.value) return;

      isLoading.value = true;
      userInput.value = "";
      adjustInputHeight();

      addMessage("user", text);
      setStatus("请求中...");

      addStepsContainer();
      let finalIntent = "";
      let finalError = "";
      let hadConfirm = false;
      let donePayload = {};

      try {
        await streamChat(sessionId.value, text, {
          step: (d) => {
            addStep(d.label || d.node || "处理中", { agent: d.agent, phase: d.phase });
            if (d.patch) {
              applyStepPatch(d.patch).catch((err) => {
                appendError(normalizeErrorMessage(err.message));
              });
            }
          },
          response_start: () => {
            finalizeSteps();
            startAssistantStreamBubble();
          },
          token: (d) => appendAssistantToken(d.content),
          confirm: (d) => {
            finalizeSteps();
            hadConfirm = true;
            finalIntent = sanitizeIntent(d.intent || "");
            addConfirmCard(d.response || "待确认操作", finalIntent);
          },
          error: (d) => {
            finalizeSteps();
            finalError = d.message || "未知错误";
          },
          done: (d) => {
            finalizeSteps();
            finalIntent = sanitizeIntent(d.intent || finalIntent);
            finalError = d.error || finalError;
            donePayload = d || {};
          },
        });

        if (finalIntent && activeAssistantMessageId.value) {
          attachIntentMeta(finalIntent);
        }

        if (finalError) {
          appendError(normalizeErrorMessage(finalError));
          setStatus("处理失败");
        } else if (!hadConfirm) {
          setStatus("完成");
        }

        await applyDoneRefreshHint(donePayload.refresh_hint, finalIntent, donePayload.active_table || "");
      } catch (err) {
        finalizeSteps();
        appendError(normalizeErrorMessage(err.message), "可重试发送，或在设置中测试连接。");
        setStatus("请求失败");
      } finally {
        isLoading.value = false;
        await nextTick();
        inputRef.value?.focus();
      }
    }

    function onInputKeydown(event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    }

    function adjustInputHeight() {
      const input = inputRef.value;
      if (!input) return;
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
    }

    function toggleTheme() {
      const nextTheme = settings.theme === "light" ? "dark" : "light";
      applyTheme(nextTheme);
      setStatus(`已切换到${nextTheme === "light" ? "浅色" : "深色"}主题`);
    }

    function openSettingsModal() {
      settingsModalOpen.value = true;
    }

    function closeSettingsModal() {
      settingsModalOpen.value = false;
    }

    function scrollChatToBottom() {
      nextTick(() => {
        const container = document.getElementById("chat-messages");
        if (container) container.scrollTop = container.scrollHeight;
      });
    }

    onMounted(async () => {
      const localTheme = localStorage.getItem(LOCAL_KEYS.theme) || DEFAULT_SETTINGS.theme;
      applyTheme(localTheme);

      const paneLimit = Number(localStorage.getItem(LOCAL_KEYS.paneLimit) || SESSION_PAGE_SIZE);
      visibleSessionCount.value = Math.max(SESSION_PAGE_SIZE, paneLimit);

      const savedHistoryVisible = localStorage.getItem(LOCAL_KEYS.historyPaneVisible);
      if (savedHistoryVisible !== null) {
        historyPaneVisible.value = savedHistoryVisible !== "0";
      }

      const savedCenterWidth = Number(localStorage.getItem(LOCAL_KEYS.centerPaneWidth));
      if (!Number.isNaN(savedCenterWidth) && savedCenterWidth > 0) {
        centerPaneWidth.value = savedCenterWidth;
      }
      centerPaneWidth.value = clampCenterPaneWidth(centerPaneWidth.value);

      window.addEventListener("mousemove", onResizeMove);
      window.addEventListener("mouseup", stopResize);
      window.addEventListener("resize", onWindowResize);

      resetChatWindow("你好，我是 DataSpeak。你可以直接描述你要查询、插入或更新的数据。", false);

      await loadSettings();
      await loadTablesAndMaybeData();
      setStatus("就绪");
    });

    onBeforeUnmount(() => {
      window.removeEventListener("mousemove", onResizeMove);
      window.removeEventListener("mouseup", stopResize);
      window.removeEventListener("resize", onWindowResize);
    });

    return {
      userInput,
      statusText,
      isLoading,
      displayedSessions,
      remainingSessionCount,
      currentSessionTitle,
      mainStyle,
      historyPaneVisible,
      isDraggingSplitter,
      sessionId,
      allTables,
      currentTable,
      tableData,
      tableLoadingText,
      chatItems,
      settings,
      createModalOpen,
      settingsModalOpen,
      createForm,
      inputRef,
      sendMessage,
      switchSession,
      createNewSession,
      loadMoreSessions,
      toggleTheme,
      toggleHistoryPane,
      startResize,
      openSettingsModal,
      closeSettingsModal,
      loadTableData,
      refreshTable,
      deleteCurrentTable,
      openCreateModal,
      closeCreateModal,
      addColumnRow,
      removeColumnRow,
      submitCreateTable,
      saveSettings,
      testSettings,
      resetSettings,
      onInputKeydown,
      adjustInputHeight,
      handleConfirmRun,
      handleConfirmCancel,
      applyTheme,
    };
  },
}).mount("#app");
