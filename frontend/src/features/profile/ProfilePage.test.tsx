import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { jobFilterOptions, mockProfile } from "../../mocks/fixtures";
import { ApiError } from "../../shared/api/client";
import { jobsApi } from "../../shared/api/jobs";
import { profileApi } from "../../shared/api/profile";
import { ProfilePage } from "./ProfilePage";

vi.mock("../../shared/api/jobs", () => ({
  jobsApi: { filterOptions: vi.fn() },
}));

vi.mock("../../shared/api/profile", () => ({
  profileApi: {
    current: vi.fn(),
    save: vi.fn(),
    importResume: vi.fn(),
  },
}));

const mockedJobsApi = vi.mocked(jobsApi);
const mockedProfileApi = vi.mocked(profileApi);

describe("ProfilePage resume import", () => {
  beforeEach(() => {
    mockedJobsApi.filterOptions.mockResolvedValue(jobFilterOptions);
    mockedProfileApi.current.mockResolvedValue(mockProfile);
    mockedProfileApi.importResume.mockResolvedValue({
      draft: {
        target_roles: ["数据平台工程师"],
        target_locations: ["杭州"],
        recruitment_types: ["社招"],
        skills: ["Python", "Airflow"],
        education: "本科",
        graduation_year: 2024,
        expected_salary_min: null,
        experience_summary: "负责数据任务编排和质量监控。",
        excluded_roles: [],
        extra_request: null,
      },
      warnings: ["未从简历中确认期望薪资，请补充或校对。"],
    });
  });

  afterEach(() => vi.clearAllMocks());

  it("loads the parsed draft into the existing review form without saving it", async () => {
    const { container } = render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "我的求职画像", level: 1 });
    expect(screen.getByText("快速生成求职画像")).toBeInTheDocument();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: { files: [new File(["resume text"], "resume.txt", { type: "text/plain" })] },
    });

    expect(await screen.findByText("简历已生成画像草稿，请确认内容后保存。")).toBeInTheDocument();
    expect(screen.getByText("数据平台工程师")).toBeInTheDocument();
    expect(screen.getByText("未从简历中确认期望薪资，请补充或校对。")).toBeInTheDocument();
    expect(mockedProfileApi.importResume).toHaveBeenCalledOnce();
    expect(mockedProfileApi.save).not.toHaveBeenCalled();
  });

  it("opens a direct editor for an existing profile instead of restarting the wizard", async () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "我的求职画像", level: 1 });
    fireEvent.click(screen.getByRole("button", { name: "修改画像" }));

    expect(screen.getByText("选择要修改的字段")).toBeInTheDocument();
    expect(screen.queryByText("第 1 步，共 9 步")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一步" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /薪资期望/ }));
    expect(screen.getByRole("spinbutton", { name: "期望税前月薪下限" })).toHaveValue(18000);
  });

  it("explains the PDF page limit when the server rejects an oversized PDF", async () => {
    mockedProfileApi.importResume.mockRejectedValueOnce(
      new ApiError(422, {
        code: "PROFILE_PARSE_FAILED",
        message: "PDF exceeds page limit",
        details: { max_pdf_pages: 4 },
      }),
    );
    const { container } = render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { name: "我的求职画像", level: 1 });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: { files: [new File(["pdf"], "resume.pdf", { type: "application/pdf" })] },
    });

    expect(await screen.findByText("PDF 简历最多支持 4 页，请压缩或拆分后重试。")).toBeInTheDocument();
  });
});
