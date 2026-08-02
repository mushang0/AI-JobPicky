import { request } from "./client";
import type {
  CreditSummary,
  PageResponse,
  RecommendationCardView,
  RecommendationFeedback,
  RecommendationFeedbackResponse,
  RecommendationListQuery,
  RecommendationResultQuery,
  RecommendationResultView,
  RecommendationRunAccepted,
  RecommendationRunCreateRequest,
  RecommendationRunListQuery,
  RecommendationTaskView,
} from "./types";

function queryString(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, String(value));
  });
  return params.toString();
}

export const creditsApi = {
  summary(): Promise<CreditSummary> {
    return request<CreditSummary>("/api/v1/user/credits");
  },
};

export const recommendationsApi = {
  list(query: RecommendationListQuery = {}): Promise<PageResponse<RecommendationCardView>> {
    const search = queryString({ page: query.page ?? 1, page_size: query.page_size ?? 10, sort: query.sort ?? "match_score_desc" });
    return request<PageResponse<RecommendationCardView>>(`/api/v1/user/recommendations?${search}`);
  },

  runs(query: RecommendationRunListQuery = {}): Promise<PageResponse<RecommendationTaskView>> {
    const search = queryString({ page: query.page ?? 1, page_size: query.page_size ?? 20 });
    return request<PageResponse<RecommendationTaskView>>(`/api/v1/user/recommendation-runs?${search}`);
  },

  create(input: RecommendationRunCreateRequest, idempotencyKey: string): Promise<RecommendationRunAccepted> {
    return request<RecommendationRunAccepted>("/api/v1/user/recommendation-runs", {
      method: "POST",
      body: input,
      idempotencyKey,
    });
  },

  status(runId: string): Promise<RecommendationTaskView> {
    return request<RecommendationTaskView>(`/api/v1/user/recommendation-runs/${encodeURIComponent(runId)}`);
  },

  results(runId: string, query: RecommendationResultQuery = {}): Promise<PageResponse<RecommendationResultView>> {
    const search = queryString({ page: query.page ?? 1, page_size: query.page_size ?? 10 });
    return request<PageResponse<RecommendationResultView>>(`/api/v1/user/recommendation-runs/${encodeURIComponent(runId)}/results?${search}`);
  },

  feedback(recommendationId: string, feedback: RecommendationFeedback): Promise<RecommendationFeedbackResponse> {
    return request<RecommendationFeedbackResponse>(`/api/v1/user/recommendations/${encodeURIComponent(recommendationId)}/feedback`, {
      method: "PUT",
      body: { feedback },
    });
  },

  remove(recommendationId: string): Promise<void> {
    return request<void>(`/api/v1/user/recommendations/${encodeURIComponent(recommendationId)}`, { method: "DELETE" });
  },
};
