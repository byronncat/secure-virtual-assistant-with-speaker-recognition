/**
 * Central API client for the backend at API_BASE.
 *
 * `authorizedFetch` attaches the persisted JWT (see `auth-context.tsx`)
 * to every call; on a 401 it clears the stored session so the app falls
 * back to the login screen instead of silently failing. All typed
 * endpoint helpers below go through it, so there is exactly one place
 * that knows how auth headers are attached.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const TOKEN_STORAGE_KEY = "voice_assistant_token";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Fetch wrapper that attaches `Authorization: Bearer <token>` and
 * normalizes error bodies. Throws `ApiError` on non-2xx responses. */
export async function authorizedFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = getStoredToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    if (res.status === 401) {
      // Session expired/invalid -- drop it so AuthContext re-renders as
      // logged out rather than the app quietly failing every call.
      setStoredToken(null);
    }
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON; keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await authorizedFetch(path, init);
  return res.json() as Promise<T>;
}

// --- Types mirroring the backend's Pydantic schemas -----------------------

export interface UserPublic {
  username: string;
  name: string;
  speaker_id: string;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserPublic;
}

export interface EnrollmentSample {
  index: number;
  filename: string;
  recorded_at: string;
}

export interface EnrollmentStatus {
  samples: EnrollmentSample[];
  sample_count: number;
  required_samples: number;
  centroid_ready: boolean;
}

export interface CommandDefinition {
  id: string;
  intent: string;
  label: string;
  icon: string;
  description: string;
  important: boolean;
}

export interface PipelineResult {
  text: string;
  language: string | null;
  speaker_id: string | null;
  command: string | null;
  rejected: boolean;
  answer: string;
}

// --- Auth -------------------------------------------------------------

export function login(
  username: string,
  password: string,
): Promise<AuthResponse> {
  return json<AuthResponse>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function register(
  username: string,
  name: string,
  password: string,
): Promise<AuthResponse> {
  return json<AuthResponse>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, name, password }),
  });
}

export function fetchCurrentUser(): Promise<UserPublic> {
  return json<UserPublic>("/api/auth/me");
}

export async function logout(): Promise<void> {
  await authorizedFetch("/api/auth/logout", { method: "POST" }).catch(() => {
    // Session may already be invalid server-side; that's fine, we're
    // discarding the local token regardless.
  });
}

// --- Enrollment ---------------------------------------------------------

export function fetchEnrollmentStatus(): Promise<EnrollmentStatus> {
  return json<EnrollmentStatus>("/api/enroll/status");
}

export async function addEnrollmentSample(
  pcm: ArrayBuffer,
  sampleRate: number,
): Promise<EnrollmentStatus> {
  const formData = new FormData();
  formData.append(
    "audio",
    new Blob([pcm], { type: "application/octet-stream" }),
    "sample.pcm",
  );
  formData.append("sample_rate", String(sampleRate));
  formData.append("channels", "1");

  const res = await authorizedFetch("/api/enroll/samples", {
    method: "POST",
    body: formData,
  });
  return res.json();
}

export async function deleteEnrollmentSample(
  index: number,
): Promise<EnrollmentStatus> {
  const res = await authorizedFetch(`/api/enroll/samples/${index}`, {
    method: "DELETE",
  });
  return res.json();
}

// --- Command management --------------------------------------------------

export function fetchCommands(): Promise<CommandDefinition[]> {
  return json<CommandDefinition[]>("/api/commands");
}

export function createCommand(
  intent: string,
  label: string,
  icon: string,
  description: string,
  important: boolean,
): Promise<CommandDefinition> {
  return json<CommandDefinition>("/api/commands", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ intent, label, icon, description, important }),
  });
}

export function updateCommand(
  intent: string,
  patch: {
    label?: string;
    icon?: string;
    description?: string;
    important?: boolean;
  },
): Promise<CommandDefinition> {
  return json<CommandDefinition>(
    `/api/commands/${encodeURIComponent(intent)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
}

export async function deleteCommand(intent: string): Promise<void> {
  await authorizedFetch(`/api/commands/${encodeURIComponent(intent)}`, {
    method: "DELETE",
  });
}

// --- Voice / chat streaming (SSE) ----------------------------------------

export interface SseHandlers {
  onMeta?: (payload: Partial<PipelineResult>) => void;
  onAnswerChunk?: (chunk: string) => void;
  onDone?: (result: PipelineResult) => void;
}

/** Reads a fetch Response body as SSE frames (`event: ...\ndata: ...\n\n`)
 * and dispatches to the matching handler. Shared by voice and chat since
 * both endpoints emit the same event shapes. */
async function consumeSse(res: Response, handlers: SseHandlers): Promise<void> {
  if (!res.body) throw new Error("Response has no body to stream.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!eventLine || !dataLine) continue;

      const type = eventLine.slice("event: ".length).trim();
      let data: unknown;
      try {
        data = JSON.parse(dataLine.slice("data: ".length));
      } catch {
        continue;
      }

      if (type === "meta") handlers.onMeta?.(data as Partial<PipelineResult>);
      else if (type === "answer_chunk")
        handlers.onAnswerChunk?.((data as { chunk: string }).chunk);
      else if (type === "done") handlers.onDone?.(data as PipelineResult);
    }
  }
}

export async function sendChatMessage(
  text: string,
  language: string | null,
  handlers: SseHandlers,
): Promise<void> {
  const res = await authorizedFetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language }),
  });
  await consumeSse(res, handlers);
}

export async function sendVoiceClip(
  pcm: ArrayBuffer,
  sampleRate: number,
  language: string | null,
  handlers: SseHandlers,
): Promise<void> {
  const formData = new FormData();
  formData.append(
    "audio",
    new Blob([pcm], { type: "application/octet-stream" }),
    "recording.pcm",
  );
  formData.append("sample_rate", String(sampleRate));
  formData.append("channels", "1");
  if (language) formData.append("language", language);

  const res = await authorizedFetch("/api/voice", {
    method: "POST",
    body: formData,
  });
  await consumeSse(res, handlers);
}
