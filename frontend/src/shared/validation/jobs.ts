import type { JobQuery } from "../api/types";

export function validateJobQuery(query: JobQuery): string | null {
  const page = query.page ?? 1;
  const pageSize = query.page_size ?? 30;

  if (!Number.isInteger(page) || page < 1) return "页码必须是正整数。";
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
    return "每页数量必须在 1 到 100 之间。";
  }
  if (query.q && query.q.length > 200) return "搜索内容不能超过 200 个字符。";
  const multiSelectValues = [
    query.city,
    query.company_nature,
    query.source_id,
    query.batch,
    query.recruitment_type,
    query.education,
    query.graduation_year,
  ];
  if (multiSelectValues.some((values) => values && values.length > 50)) {
    return "单个筛选最多选择 50 项。";
  }
  if (
    query.salary_min !== null &&
    query.salary_min !== undefined &&
    query.salary_max !== null &&
    query.salary_max !== undefined &&
    query.salary_min > query.salary_max
  ) {
    return "薪资下限不能高于薪资上限。";
  }

  return null;
}
