export function formatDate(value: string | null): string {
  if (!value) return "时间待确认";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间待确认";

  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(date);
}

export function formatPublishedDate(value: string | null): string {
  return value ? `发布于 ${formatDate(value)}` : "发布日期未注明";
}

export function formatRecommendationDeadline(
  deadline: string | null,
  status: "OPEN" | "CLOSED" | "UNKNOWN",
): string {
  if (status === "CLOSED") return "已截止";
  if (!deadline) return "建议尽快投递";
  const timestamp = new Date(deadline).getTime();
  if (!Number.isFinite(timestamp) || timestamp <= Date.now()) return "已截止";
  return `截止 ${formatDate(deadline)}`;
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
    PROFILE: "正在理解你的求职方向",
    FILTER: "正在排除不符合要求的岗位",
    RETRIEVE: "正在寻找相关岗位",
    EVALUATE: "正在比较你的经历和岗位要求",
    SAVE: "正在整理推荐结果",
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
