import type { ApiErrorCode } from "./types";

const messages: Partial<Record<ApiErrorCode, string>> = {
  AUTHENTICATION_REQUIRED: "请登录后继续。",
  SESSION_EXPIRED: "登录会话已过期，请重新登录。",
  ACCOUNT_DISABLED: "账号已停用。",
  INVALID_CREDENTIALS: "邮箱或密码不正确。",
  EMAIL_ALREADY_REGISTERED: "该邮箱已经注册，请直接登录。",
  TOO_MANY_ATTEMPTS: "尝试次数过多，请稍后再试。",
  INSUFFICIENT_CREDITS: "积分余额不足，请先补充积分后再试。",
  PROFILE_NOT_FOUND: "还没有求职画像，请先填写。",
  PROFILE_VERSION_CONFLICT: "求职画像已在其他页面更新，请刷新后重试。",
  PROFILE_PARSE_FAILED: "暂时无法生成求职画像，请稍后重试。",
  IDEMPOTENCY_CONFLICT: "请求正在处理，请稍后重试。",
  RECOMMENDATION_FAILED: "推荐失败，请稍后重试。",
  VALIDATION_ERROR: "请检查表单内容。",
  NOT_FOUND: "请求的内容不存在。",
  FORBIDDEN: "当前账号没有执行此操作的权限。",
  INTERNAL_ERROR: "服务不可用，请稍后重试。",
  DEPENDENCY_UNAVAILABLE: "相关服务不可用，请稍后重试。",
};

export function getApiErrorMessage(code: ApiErrorCode, fallback: string): string {
  if (messages[code]) return messages[code];
  return /[\u4e00-\u9fff]/.test(fallback) ? fallback : "服务不可用，请稍后重试。";
}
