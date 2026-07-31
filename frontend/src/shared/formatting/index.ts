export function formatDate(value: string | null): string {
  if (!value) return "时间待确认";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";

  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(date);
}

export function formatSalaryRange(
  min: number | null,
  max: number | null,
  months: number | null,
): string {
  if (min === null && max === null) return "薪资待确认";

  const salary = [min, max]
    .filter((value): value is number => value !== null)
    .map((value) => value.toLocaleString("zh-CN"))
    .join("-");
  const monthly = `${salary} 元/月`;
  return months ? `${monthly}，${months} 薪` : monthly;
}

export function formatJobStatus(status: "OPEN" | "CLOSED" | "UNKNOWN"): string {
  return {
    OPEN: "开放",
    CLOSED: "已关闭",
    UNKNOWN: "状态待确认",
  }[status];
}

export function formatRecommendationStep(step: "PENDING" | "PROFILE" | "FILTER" | "RETRIEVE" | "EVALUATE" | "SAVE" | "COMPLETE" | null): string {
  return {
    PENDING: "等待开始",
    PROFILE: "读取用户画像",
    FILTER: "筛选符合条件的岗位",
    RETRIEVE: "召回候选岗位",
    EVALUATE: "AI 正在评估岗位",
    SAVE: "保存推荐结果",
    COMPLETE: "推荐完成",
  }[step ?? "PENDING"];
}

export function formatRecommendationStatus(status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED"): string {
  return {
    PENDING: "等待开始",
    RUNNING: "运行中",
    SUCCEEDED: "已完成",
    FAILED: "已失败",
  }[status];
}
