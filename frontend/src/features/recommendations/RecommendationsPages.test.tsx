import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RecommendationRunDetailPage } from "./RecommendationsPages";
import { jobsApi } from "../../shared/api/jobs";
import { recommendationsApi } from "../../shared/api/recommendations";

vi.mock("../../shared/api/jobs", () => ({
  jobsApi: {
    list: vi.fn(),
    save: vi.fn(),
    unsave: vi.fn(),
  },
}));

vi.mock("../../shared/api/recommendations", () => ({
  creditsApi: { summary: vi.fn() },
  recommendationsApi: {
    status: vi.fn(),
    results: vi.fn(),
    feedback: vi.fn(),
    remove: vi.fn(),
  },
}));

const failedTask = {
  run_id: "run-1",
  status: "FAILED" as const,
  current_step: "RETRIEVE" as const,
  progress_percent: 45,
  created_at: "2026-08-01T00:00:00Z",
  started_at: "2026-08-01T00:00:01Z",
  finished_at: "2026-08-01T00:00:02Z",
  counts: { evaluated: 0, recommended: 0 },
  credits: { cost: 100, refunded: true, net_spent: 0 },
  error: {
    code: "DEPENDENCY_UNAVAILABLE",
    message: "依赖服务暂时不可用，请稍后重试。",
    details: { dependency: "embedding" },
  },
};

const mockedJobsApi = vi.mocked(jobsApi);
const mockedRecommendationsApi = vi.mocked(recommendationsApi);

describe("RecommendationRunDetailPage", () => {
  it("renders a structured backend failure without crashing the page", async () => {
    mockedJobsApi.list.mockResolvedValue({ items: [], total: 2000, page: 1, page_size: 1, pool_total: 2000 });
    mockedJobsApi.save.mockReset();
    mockedJobsApi.unsave.mockReset();
    mockedRecommendationsApi.status.mockResolvedValue(failedTask);
    mockedRecommendationsApi.results.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 10 });

    render(
      <MemoryRouter initialEntries={["/recommendation-runs/run-1"]}>
        <Routes>
          <Route path="/recommendation-runs/:runId" element={<RecommendationRunDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("推荐任务失败");
    expect(screen.getByText("依赖服务暂时不可用，请稍后重试。")).toBeInTheDocument();
    expect(screen.getByText("本次积分已退回")).toBeInTheDocument();
    expect(screen.getByText("从 2000 个岗位中推荐")).toBeInTheDocument();
  });
});
