import { buildJobsQuery } from "./jobs";
import { formatSalaryRange } from "../formatting";
import { validateJobQuery } from "../validation/jobs";

describe("jobs API helpers", () => {
  it("uses repeated query keys for multi-select filters", () => {
    const query = buildJobsQuery({
      page: 2,
      page_size: 30,
      q: "  Python  ",
      city: ["上海", "杭州"],
      company_nature: ["民营企业"],
      batch: ["秋招提前批"],
    });

    expect(query).toContain("page=2");
    expect(query).toContain("q=Python");
    expect(query.match(/city=/g)).toHaveLength(2);
    expect(query).toContain("company_nature=%E6%B0%91%E8%90%A5%E4%BC%81%E4%B8%9A");
    expect(query).toContain("batch=%E7%A7%8B%E6%8B%9B%E6%8F%90%E5%89%8D%E6%89%B9");
  });

  it("keeps missing salary explicit instead of inventing a value", () => {
    expect(formatSalaryRange(null, null, null)).toBe("薪资待确认");
    expect(formatSalaryRange(18000, 28000, 13)).toBe("18,000-28,000 元/月，13 薪");
  });

  it("validates the documented query limits", () => {
    expect(validateJobQuery({ q: "x".repeat(201) })).toBe("搜索内容不能超过 200 个字符。");
    expect(validateJobQuery({ city: Array.from({ length: 51 }, (_, index) => `城市${index}`) })).toBe("单个筛选最多选择 50 项。");
    expect(validateJobQuery({ q: "Python", city: ["上海", "北京"] })).toBeNull();
  });
});
