export const API = window.location.origin;

export const LOCAL_KEYS = {
  theme: "ds_theme",
  sessions: "ds_sessions",
  sessionLimit: "ds_session_limit",
  paneLimit: "ds_session_pane_limit",
  historyPaneVisible: "ds_history_pane_visible",
  centerPaneWidth: "ds_center_pane_width",
};

export const DEFAULT_SETTINGS = {
  api_base_url: API,
  api_key: "",
  model_id: "gpt-4o-mini",
  temperature: 0.0,
  max_history_length: 20,
  theme: "dark",
  session_limit: 20,
};

export const SESSION_PAGE_SIZE = 8;
export const MAX_PREVIEW_LEN = 64;
