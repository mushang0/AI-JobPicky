import type { ProfileSaveRequest } from "../api/types";
import { normalizeProfile, validateProfile } from "./profile";

const validProfile: ProfileSaveRequest = {
  base_version: null,
  target_roles: ["Python 后端工程师"],
  target_locations: ["上海"],
  recruitment_types: ["社招"],
  skills: ["Python"],
  education: "本科",
  graduation_year: 2024,
  expected_salary_min: 18000,
  experience_summary: null,
  excluded_roles: [],
  extra_request: null,
};

describe("profile validation", () => {
  it("normalizes tags and optional text before saving", () => {
    const normalized = normalizeProfile({
      ...validProfile,
      target_roles: [" Python 后端工程师 ", "", "Python 后端工程师"],
      experience_summary: "  有服务端项目经验。 ",
    });

    expect(normalized.target_roles).toEqual(["Python 后端工程师"]);
    expect(normalized.experience_summary).toBe("有服务端项目经验。");
  });

  it("requires a target role and either skills or experience", () => {
    expect(validateProfile({ ...validProfile, target_roles: [] })).toBe("至少填写一个目标岗位。");
    expect(validateProfile({ ...validProfile, skills: [], experience_summary: null })).toBe("技能和经历与项目摘要至少填写一项。");
  });

  it("rejects unsupported recruitment types and oversized lists", () => {
    expect(validateProfile({ ...validProfile, recruitment_types: ["兼职"] })).toBe("招聘类型不在可选范围内。");
    expect(validateProfile({ ...validProfile, target_roles: Array.from({ length: 11 }, (_, index) => `岗位${index}`) })).toBe("目标岗位最多填写 10 项。");
  });
});
