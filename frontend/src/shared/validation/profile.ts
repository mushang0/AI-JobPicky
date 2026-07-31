import type { ProfileSaveRequest } from "../api/types";

const allowedRecruitmentTypes = new Set(["校招", "社招", "实习"]);

function cleanTags(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function tagError(values: string[], max: number, label: string): string | null {
  const cleaned = cleanTags(values);
  if (cleaned.length > max) return `${label}最多填写 ${max} 项。`;
  if (cleaned.some((value) => Array.from(value).length > 100)) return `${label}单项不能超过 100 个字符。`;
  return null;
}

export function normalizeProfile(input: ProfileSaveRequest): ProfileSaveRequest {
  return {
    ...input,
    target_roles: cleanTags(input.target_roles),
    target_locations: cleanTags(input.target_locations),
    recruitment_types: cleanTags(input.recruitment_types),
    skills: cleanTags(input.skills),
    excluded_roles: cleanTags(input.excluded_roles),
    education: input.education?.trim() || null,
    experience_summary: input.experience_summary?.trim() || null,
    extra_request: input.extra_request?.trim() || null,
  };
}

export function validateProfile(input: ProfileSaveRequest): string | null {
  const normalized = normalizeProfile(input);
  const rolesError = tagError(normalized.target_roles, 10, "目标岗位");
  if (rolesError) return rolesError;
  const locationsError = tagError(normalized.target_locations, 10, "目标城市");
  if (locationsError) return locationsError;
  const recruitmentError = tagError(normalized.recruitment_types, 3, "招聘类型");
  if (recruitmentError) return recruitmentError;
  if (normalized.recruitment_types.some((value) => !allowedRecruitmentTypes.has(value))) return "招聘类型不在可选范围内。";
  const skillsError = tagError(normalized.skills, 50, "技能");
  if (skillsError) return skillsError;
  const excludedError = tagError(normalized.excluded_roles, 20, "排除岗位");
  if (excludedError) return excludedError;
  if (normalized.target_roles.length < 1) return "至少填写一个目标岗位。";
  if (normalized.expected_salary_min !== null && (normalized.expected_salary_min < 0 || normalized.expected_salary_min > 1000000)) return "期望月薪下限需要在 0 到 1000000 之间。";
  if (normalized.graduation_year !== null && (normalized.graduation_year < new Date().getFullYear() - 80 || normalized.graduation_year > new Date().getFullYear() + 10)) return "毕业年份不在可选范围内。";
  if (normalized.experience_summary && Array.from(normalized.experience_summary).length > 5000) return "经历与项目摘要不能超过 5000 个字符。";
  if (normalized.extra_request && Array.from(normalized.extra_request).length > 1000) return "其他长期要求不能超过 1000 个字符。";
  if (normalized.skills.length === 0 && !normalized.experience_summary) return "技能和经历与项目摘要至少填写一项。";
  return null;
}
