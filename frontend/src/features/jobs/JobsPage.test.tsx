import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { JobsPage } from "./JobsPage";
import { jobsApi } from "../../shared/api/jobs";

vi.mock("../../adapters/web/AuthProvider", () => ({
  useAuth: () => ({ status: "anonymous" }),
}));

vi.mock("../../shared/api/jobs", () => ({
  jobsApi: {
    list: vi.fn(),
    filterOptions: vi.fn(),
  },
}));

const mockedJobsApi = vi.mocked(jobsApi);

describe("JobsPage", () => {
  it("renders the empty state without inventing a result", async () => {
    mockedJobsApi.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 30, pool_total: 0 });
    mockedJobsApi.filterOptions.mockResolvedValue({
      cities: [],
      company_natures: [],
      sources: [],
      recruitment_types: ["校招", "社招", "实习"],
      educations: [],
      graduation_years: [],
      limits: { visible_pool_limit: 5000, default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("当前没有匹配岗位")).toBeInTheDocument();
    expect(screen.queryByText("Python 后端工程师")).not.toBeInTheDocument();
  });
});
