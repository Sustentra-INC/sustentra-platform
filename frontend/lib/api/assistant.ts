import { apiRequest } from "./client";

export interface AssistantResponse {
  engagement_id: string;
  answer: string;
}

export function sendAssistantMessage(
  engagementId: string,
  message: string
): Promise<AssistantResponse> {
  return apiRequest<AssistantResponse>("/v1/assistant/chat", {
    method: "POST",
    body: JSON.stringify({ engagement_id: engagementId, message })
  });
}
