import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { JobsPage } from "./JobsPage";
import { jobsApi } from "../../shared/api/jobs";

vi.mock("../../adapters/web/AuthProvider", () => ({
  useAuth: () => ({ status: "anonymous" }),
}));

vi.mock("../../shared/api/jobs", () => ({
  jobsApi: {
    list: vi.fn(),
    companies: vi.fn(),
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
      limits: { default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("没有找到岗位")).toBeInTheDocument();
    expect(screen.queryByText("Python 后端工程师")).not.toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "岗位数量" });
    expect(within(summary).getByText("岗位池")).toBeInTheDocument();
    expect(within(summary).getByText("当前视图")).toBeInTheDocument();
    expect(screen.queryByText("岗位池总数")).not.toBeInTheDocument();
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
      limits: { default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByPlaceholderText("搜索岗位、公司或关键词"));
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
      limits: { default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByPlaceholderText("搜索岗位、公司或关键词"));
    const publishedDate = await screen.findByRole("combobox", { name: "发布日期" });
    expect(publishedDate.parentElement).toHaveClass("select-control-wrap");
    expect(screen.queryByText("更多筛选")).not.toBeInTheDocument();
    expect(screen.queryByText("来源")).not.toBeInTheDocument();
    expect(screen.getByText("招聘批次")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "每页显示岗位数" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "应用筛选" })).toHaveLength(1);
  });

  it("keeps detailed filters collapsed until the search field is opened", async () => {
    mockedJobsApi.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 30, pool_total: 0 });
    mockedJobsApi.filterOptions.mockResolvedValue({
      cities: [],
      company_natures: [],
      sources: [],
      batches: [],
      recruitment_types: ["社招"],
      educations: ["本科"],
      graduation_years: [2027],
      limits: { default_page_size: 30, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>,
    );

    await screen.findByText("没有找到岗位");
    const searchInput = screen.getByPlaceholderText("搜索岗位、公司或关键词");
    const panel = document.getElementById("job-filter-panel");
    expect(panel).not.toBeNull();
    expect(panel).not.toHaveClass("is-open");

    fireEvent.click(searchInput);
    expect(panel).toHaveClass("is-open");

    fireEvent.keyDown(searchInput, { key: "Escape" });
    expect(panel).not.toHaveClass("is-open");
  });

  it("switches to the company view and links to grouped jobs", async () => {
    mockedJobsApi.list.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 12, pool_total: 0 });
    mockedJobsApi.companies.mockResolvedValue({
      items: [{
        group_id: "feishu:rec-1",
        company_name: "同一公司",
        company_nature: "民营企业",
        company_natures: ["民营企业"],
        batches: ["秋招提前批"],
        job_titles: ["后端工程师", "算法工程师"],
        job_count: 2,
        latest_published_at: "2026-08-01T08:00:00Z",
      }],
      total: 1,
      page: 1,
      page_size: 12,
      pool_total: 1,
    });
    mockedJobsApi.filterOptions.mockResolvedValue({
      cities: [],
      company_natures: [],
      sources: [],
      batches: [],
      recruitment_types: [],
      educations: [],
      graduation_years: [],
      limits: { default_page_size: 12, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter initialEntries={["/jobs?view=company"]}>
        <JobsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("同一公司")).toBeInTheDocument();
    expect(screen.getByText("后端工程师")).toBeInTheDocument();
    expect(screen.getByText("算法工程师")).toBeInTheDocument();
    const companyLink = screen.getByRole("link", { name: /同一公司/ });
    expect(companyLink).toHaveAttribute(
      "href",
      expect.stringContaining("company_group_id=feishu%3Arec-1"),
    );
    expect(companyLink).toHaveAttribute(
      "href",
      expect.stringContaining("company_return_to=%2Fjobs%3Fview%3Dcompany"),
    );
    expect(within(companyLink).getByText("秋招提前批")).toBeInTheDocument();
    expect(within(companyLink).queryByText("招聘类型")).not.toBeInTheDocument();
  });

  it("offers a return link from a company's job list", async () => {
    mockedJobsApi.list.mockResolvedValue({
      items: [{
        id: "job-1",
        title: "后端工程师",
        company_name: "同一公司",
        company_nature: "民营企业",
        locations: ["上海"],
        source: { id: "source-1", name: "飞书招聘" },
        batch: "秋招提前批",
        recruitment_type: "校招",
        education_requirement: "本科",
        graduation_years: [],
        salary_min: null,
        salary_max: null,
        salary_months: null,
        description_preview: "岗位描述",
        published_at: null,
        last_confirmed_at: "2026-08-01T08:00:00Z",
        is_saved: null,
      }],
      total: 1,
      page: 1,
      page_size: 12,
      pool_total: 1,
    });
    mockedJobsApi.filterOptions.mockResolvedValue({
      cities: [],
      company_natures: [],
      sources: [],
      batches: [],
      recruitment_types: [],
      educations: [],
      graduation_years: [],
      limits: { default_page_size: 12, public_page_size_max: 30, authenticated_page_size_max: 100 },
    });

    render(
      <MemoryRouter initialEntries={["/jobs?view=job&company_group_id=name%3A%E5%90%8C%E4%B8%80%E5%85%AC%E5%8F%B8&company_return_to=%2Fjobs%3Fview%3Dcompany%26page%3D2"]}>
        <JobsPage />
      </MemoryRouter>,
    );

    const backLink = await screen.findByRole("link", { name: /返回公司视图/ });
    expect(backLink).toHaveAttribute("href", "/jobs?view=company&page=2");
  });
});
