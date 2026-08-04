import { fireEvent, render, screen } from "@testing-library/react";
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
      batches: [],
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

    expect(await screen.findByText("没有找到岗位")).toBeInTheDocument();
    expect(screen.queryByText("Python 后端工程师")).not.toBeInTheDocument();
  });

  it("opens the city picker from province to city", async () => {
    mockedJobsApi.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 30, pool_total: 0 });
    mockedJobsApi.filterOptions.mockResolvedValue({
      cities: ["上海", "杭州"],
      company_natures: ["民营企业"],
      sources: [{ platform: "公开招聘源", source_ids: ["source-1"] }],
      batches: ["秋招提前批"],
      recruitment_types: ["社招"],
      educations: ["本科"],
      graduation_years: [2027],
      limits: { visible_pool_limit: 5000, default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "城市" }));

    fireEvent.click(screen.getByRole("button", { name: "浙江" }));
    expect(screen.getByRole("option", { name: "杭州" })).toBeInTheDocument();
  });

  it("keeps the published date control consistent and hides low-value filters", async () => {
    mockedJobsApi.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 30, pool_total: 0 });
    mockedJobsApi.filterOptions.mockResolvedValue({
      cities: [],
      company_natures: [],
      sources: [{ platform: "北森", source_ids: ["beisen-a", "beisen-b"] }],
      batches: [],
      recruitment_types: [],
      educations: [],
      graduation_years: [],
      limits: { visible_pool_limit: 5000, default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    const publishedDate = await screen.findByRole("combobox", { name: "发布日期" });
    expect(publishedDate.parentElement).toHaveClass("select-control-wrap");
    expect(screen.queryByText("更多筛选")).not.toBeInTheDocument();
    expect(screen.queryByText("来源")).not.toBeInTheDocument();
    expect(screen.getByText("招聘批次")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "每页显示岗位数" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "应用筛选" })).toHaveLength(2);
  });

  it("keeps detailed filters collapsed until the mobile toggle is opened", async () => {
    mockedJobsApi.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 30, pool_total: 0 });
    mockedJobsApi.filterOptions.mockResolvedValue({
      cities: [],
      company_natures: [],
      sources: [],
      batches: [],
      recruitment_types: ["社招"],
      educations: ["本科"],
      graduation_years: [2027],
      limits: { visible_pool_limit: 5000, default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    await screen.findByText("没有找到岗位");
    const toggle = screen.getByRole("button", { name: "筛选" });
    const panel = document.getElementById("job-filter-panel");
    expect(panel).not.toBeNull();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toHaveClass("is-open");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toHaveClass("is-open");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toHaveClass("is-open");
  });
});
