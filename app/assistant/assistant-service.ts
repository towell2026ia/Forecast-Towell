export type AssistantStatus = "ready" | "processing" | "disabled" | "error";

export type AssistantRole = "manager" | "editor" | "reader";

export type AssistantContext = {
  user: string;
  role: AssistantRole;
  screen: string;
  activeFilters: Record<string, string | null>;
  chain: string | null;
  category: string | null;
  product: string | null;
  color: string | null;
  period: string | null;
};

export type AssistantAction = {
  type: "navigate" | "apply_filter" | "open_record";
  label: string;
  payload: Record<string, string>;
};

export type AssistantResponse = {
  message: string;
  status: AssistantStatus;
  source: "mock" | "future-ai";
  actions: AssistantAction[];
  metadata: Record<string, string | number | boolean | null>;
};

export type AssistantMode = "mock" | "future-ai";

export interface AssistantProvider {
  send(message: string, context: AssistantContext): Promise<AssistantResponse>;
}

export class MockProvider implements AssistantProvider {
  async send(_message: string, context: AssistantContext): Promise<AssistantResponse> {
    await new Promise((resolve) => window.setTimeout(resolve, 360));
    return {
      message: "El asistente está en preparación para la siguiente fase. En este piloto no se envían datos ni se generan análisis automáticos.",
      status: "disabled",
      source: "mock",
      actions: [],
      metadata: { screen: context.screen, apiEnabled: false },
    };
  }
}

export class FutureAIProvider implements AssistantProvider {
  async send(): Promise<AssistantResponse> {
    throw new Error("FutureAIProvider no está habilitado en PRD 08A.");
  }
}

export async function sendAssistantMessage(
  message: string,
  context: AssistantContext,
  options: { mode: AssistantMode; apiEnabled: boolean },
): Promise<AssistantResponse> {
  if (!message.trim()) {
    return { message: "Escribe una pregunta para continuar.", status: "ready", source: "mock", actions: [], metadata: {} };
  }

  const provider: AssistantProvider = options.mode === "future-ai" && options.apiEnabled
    ? new FutureAIProvider()
    : new MockProvider();

  return provider.send(message, context);
}
