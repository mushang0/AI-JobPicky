import { useEffect, useRef, useState } from "react";
import { Check, FloppyDisk, WarningCircle, X } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { createIdempotencyKey } from "../../shared/api/idempotency";
import { jobsApi } from "../../shared/api/jobs";
import { profileApi } from "../../shared/api/profile";
import type { JobFilterOptions, ProfileSaveRequest, ProfileView } from "../../shared/api/types";
import { formatDate } from "../../shared/formatting";
import { normalizeProfile, validateProfile } from "../../shared/validation/profile";
import { CityPicker } from "../../components/CityPicker";

const emptyProfile: ProfileSaveRequest = {
  base_version: null,
  target_roles: [],
  target_locations: [],
  recruitment_types: [],
  skills: [],
  education: null,
  graduation_year: null,
  expected_salary_min: null,
  experience_summary: null,
  excluded_roles: [],
  extra_request: null,
};

function profileToForm(profile: ProfileView): ProfileSaveRequest {
  return {
    base_version: profile.version,
    target_roles: profile.target_roles,
    target_locations: profile.target_locations,
    recruitment_types: profile.recruitment_types,
    skills: profile.skills,
    education: profile.education,
    graduation_year: profile.graduation_year,
    expected_salary_min: profile.expected_salary_min,
    experience_summary: profile.experience_summary,
    excluded_roles: profile.excluded_roles,
    extra_request: profile.extra_request,
  };
}

const wizardSteps = [
  "目标岗位",
  "目标城市",
  "招聘类型",
  "学历与毕业时间",
  "掌握技能",
  "项目与经历",
  "薪资期望",
  "排除项与其他要求",
  "确认画像",
];

export function ProfilePage() {
  const [form, setForm] = useState<ProfileSaveRequest>(emptyProfile);
  const [filters, setFilters] = useState<JobFilterOptions | null>(null);
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [mode, setMode] = useState<"summary" | "edit">("edit");
  const [step, setStep] = useState(0);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [isSaving, setIsSaving] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [validationMessage, setValidationMessage] = useState<string | null>(null);
  const saveKeyRef = useRef<string | null>(null);
  const graduationYears = filters?.graduation_years
    ? [...new Set(form.graduation_year && !filters.graduation_years.includes(form.graduation_year) ? [form.graduation_year, ...filters.graduation_years] : filters.graduation_years)]
    : [];

  useEffect(() => {
    let active = true;
    Promise.all([
      jobsApi.filterOptions(),
      profileApi.current().catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "PROFILE_NOT_FOUND") return null;
        throw error;
      }),
    ]).then(([filterOptions, currentProfile]) => {
      if (!active) return;
      setFilters(filterOptions);
      setProfile(currentProfile);
      setForm(currentProfile ? profileToForm(currentProfile) : { ...emptyProfile });
      setMode(currentProfile ? "summary" : "edit");
      setStep(0);
      setLoadState("ready");
    }).catch((error: unknown) => {
      if (!active) return;
      setLoadState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "求职画像暂时无法加载，请稍后重试。");
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!isDirty) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  function markDirty(nextForm: ProfileSaveRequest) {
    setForm(nextForm);
    setIsDirty(true);
    setMessage(null);
    setErrorMessage(null);
    setValidationMessage(null);
    saveKeyRef.current = null;
  }

  function updateField<K extends keyof ProfileSaveRequest>(field: K, value: ProfileSaveRequest[K]) {
    markDirty({ ...form, [field]: value });
  }

  function toggleListValue(field: "target_locations" | "recruitment_types", value: string) {
    const values = form[field];
    updateField(field, values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  }

  function beginEditing() {
    if (!profile) return;
    setForm(profileToForm(profile));
    setMode("edit");
    setStep(0);
    setIsDirty(false);
    setMessage(null);
    setErrorMessage(null);
    setValidationMessage(null);
  }

  function cancelEditing() {
    if (profile) {
      setForm(profileToForm(profile));
      setMode("summary");
      setStep(0);
      setIsDirty(false);
      setMessage(null);
      setValidationMessage(null);
    }
  }

  function goToNextStep() {
    setValidationMessage(null);
    if (step === 0 && form.target_roles.length === 0) {
      setValidationMessage("先填写至少一个想找的岗位。");
      return;
    }
    setStep((current) => Math.min(current + 1, wizardSteps.length - 1));
  }

  function goToPreviousStep() {
    setValidationMessage(null);
    if (step === 0) {
      if (profile) cancelEditing();
      return;
    }
    setStep((current) => current - 1);
  }

  async function reloadProfile() {
    setLoadState("loading");
    setErrorMessage(null);
    try {
      const currentProfile = await profileApi.current().catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "PROFILE_NOT_FOUND") return null;
        throw error;
      });
      setProfile(currentProfile);
      setForm(currentProfile ? profileToForm(currentProfile) : { ...emptyProfile });
      setMode(currentProfile ? "summary" : "edit");
      setStep(0);
      setIsDirty(false);
      saveKeyRef.current = null;
      setLoadState("ready");
    } catch (error: unknown) {
      setLoadState("error");
      setErrorMessage(error instanceof ApiError ? getApiErrorMessage(error.code, error.message) : "求职画像暂时无法加载，请稍后重试。");
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = normalizeProfile(form);
    const validation = validateProfile(normalized);
    if (validation) {
      setValidationMessage(validation);
      return;
    }

    const key = saveKeyRef.current ?? createIdempotencyKey("profile");
    saveKeyRef.current = key;
    setIsSaving(true);
    setValidationMessage(null);
    setMessage(null);
    setErrorMessage(null);
    try {
      const savedProfile = await profileApi.save(normalized, key);
      setProfile(savedProfile);
      setForm(profileToForm(savedProfile));
      setMode("summary");
      setStep(0);
      setIsDirty(false);
      setMessage("已保存。接下来可以开始寻找合适的岗位。");
      saveKeyRef.current = null;
    } catch (error: unknown) {
      if (error instanceof ApiError && error.code === "PROFILE_VERSION_CONFLICT") {
        setErrorMessage("画像已在其他页面更新，请刷新后重试。");
      } else if (error instanceof ApiError) {
        setErrorMessage(getApiErrorMessage(error.code, error.message));
      } else {
        setErrorMessage("画像保存失败，请稍后重试。");
      }
    } finally {
      setIsSaving(false);
    }
  }

  if (loadState === "loading") return <ProfileSkeleton />;
  if (loadState === "error") return <StatePanel title="求职画像暂时无法加载" description={errorMessage ?? "请稍后重试。"} actionLabel="重新加载" onAction={() => void reloadProfile()} />;

  return (
    <div className="profile-page">
      <section className="page-intro profile-intro">
        <div>
          <div className="eyebrow"><span className="eyebrow-dot" aria-hidden="true" />我的求职画像</div>
          <h1>{mode === "summary" ? "这是你正在寻找的工作。" : profile ? "调整你的求职方向。" : "告诉我们你想找什么工作。"}</h1>
          <p>{mode === "summary" ? "我们会根据这些信息寻找岗位，你可以随时修改。" : "按步骤填写即可，暂时不确定的内容可以先跳过。"}</p>
        </div>
        {mode === "summary" && <div className="intro-note"><Check size={20} /><div><strong>画像已准备好</strong><span>可以开始寻找岗位</span></div></div>}
      </section>

      {mode === "summary" ? (
        <>
          {message && <p className="profile-success" role="status"><Check size={17} />{message}</p>}
          <ProfileSummary form={form} createdAt={profile?.created_at ?? null} warnings={profile?.warnings ?? []} onEdit={beginEditing} />
        </>
      ) : (
        <form className="profile-form profile-wizard" onSubmit={handleSubmit}>
          <div className="profile-wizard-progress"><div><span>第 {step + 1} 步，共 {wizardSteps.length} 步</span><strong>{wizardSteps[step]}</strong></div><div className="profile-wizard-progress-track" aria-hidden="true"><span style={{ width: `${((step + 1) / wizardSteps.length) * 100}%` }} /></div></div>
          {step === 0 && <ProfileSection title="你想找什么岗位？" description="可以填写一个或多个方向，尽量使用具体岗位名称。"><TagInput label="目标岗位" values={form.target_roles} placeholder="例如 后端工程师" onChange={(values) => updateField("target_roles", values)} /></ProfileSection>}
          {step === 1 && <ProfileSection title="你希望在哪些城市工作？" description="不填写表示地点不限。"><div className="field-group city-picker-field"><span>目标城市</span><CityPicker label="目标城市" values={form.target_locations} onChange={(values) => updateField("target_locations", values)} /></div></ProfileSection>}
          {step === 2 && <ProfileSection title="你准备找哪种机会？" description="不选择表示招聘类型不限。"><ChoiceField label="招聘类型" options={filters?.recruitment_types ?? []} values={form.recruitment_types} onToggle={(value) => toggleListValue("recruitment_types", value)} emptyText="可以多选，也可以先跳过" /></ProfileSection>}
          {step === 3 && <ProfileSection title="你的教育背景是什么？" description="这些信息会帮助我们排除明显不合适的岗位。"><label className="field-group"><span>最高学历</span><select value={form.education ?? ""} onChange={(event) => updateField("education", event.target.value || null)}><option value="">暂不填写</option>{(filters?.educations ?? []).map((option) => <option key={option} value={option}>{option}</option>)}</select></label><label className="field-group"><span>毕业年份</span><select value={form.graduation_year ?? ""} onChange={(event) => updateField("graduation_year", event.target.value ? Number(event.target.value) : null)}><option value="">暂不填写</option>{graduationYears.map((year) => <option key={year} value={year}>{year}</option>)}</select></label></ProfileSection>}
          {step === 4 && <ProfileSection title="你擅长什么？" description="写下与你目标岗位相关的技能，越具体越有帮助。"><TagInput label="掌握技能" values={form.skills} placeholder="例如 Python、FastAPI" onChange={(values) => updateField("skills", values)} /></ProfileSection>}
          {step === 5 && <ProfileSection title="你做过哪些相关项目或工作？" description="用几句话描述负责过的事情、项目和结果。"><TextAreaField label="项目与经历" value={form.experience_summary ?? ""} placeholder="例如：负责服务端接口、数据建模和异步任务链路" onChange={(value) => updateField("experience_summary", value || null)} /></ProfileSection>}
          {step === 6 && <ProfileSection title="薪资有什么期望？" description="可以先不填写，之后仍能修改。"><NumberField label="期望税前月薪下限" value={form.expected_salary_min} placeholder="元/月，可不填" onChange={(value) => updateField("expected_salary_min", value)} /></ProfileSection>}
          {step === 7 && <ProfileSection title="有什么岗位不考虑？" description="补充明确排除项或长期要求，帮助我们减少无关结果。"><TagInput label="排除岗位" values={form.excluded_roles} placeholder="例如 客服、销售" onChange={(values) => updateField("excluded_roles", values)} /><TextAreaField label="其他长期要求" value={form.extra_request ?? ""} placeholder="例如 不接受长期出差" onChange={(value) => updateField("extra_request", value || null)} /></ProfileSection>}
          {step === 8 && <ProfileSection title="确认你的求职画像" description="确认无误后保存，之后可以开始寻找岗位。"><ProfileSummary form={form} createdAt={null} warnings={[]} onEdit={() => setStep(0)} compact /></ProfileSection>}

          {profile?.warnings.map((warning) => <p className="profile-warning" key={warning}><WarningCircle size={17} />{warning}</p>)}
          {validationMessage && <p className="form-error profile-form-error" role="alert">{validationMessage}</p>}
          {errorMessage && <p className="form-error profile-form-error" role="alert">{errorMessage}</p>}
          <div className="profile-actions profile-wizard-actions">
            <button className="button button-secondary" type="button" onClick={goToPreviousStep}>{step === 0 && profile ? "取消修改" : "上一步"}</button>
            <span className="profile-save-hint">{isDirty ? "内容只会在保存后用于推荐" : "可以随时返回修改"}</span>
            {step < wizardSteps.length - 1 ? <button className="button button-primary" type="button" onClick={goToNextStep}>下一步</button> : <button className="button button-primary" type="submit" disabled={isSaving}><FloppyDisk size={17} />{isSaving ? "保存中" : "保存画像"}</button>}
          </div>
        </form>
      )}
    </div>
  );
}

function ProfileSummary({ form, createdAt, warnings, onEdit, compact = false }: { form: ProfileSaveRequest; createdAt: string | null; warnings: string[]; onEdit: () => void; compact?: boolean }) {
  return <section className={`profile-summary${compact ? " profile-summary-compact" : ""}`}>
    <div className="profile-summary-heading"><div><span className="profile-summary-kicker">你的求职方向</span><h2>这些信息会帮助我们找岗位</h2></div>{!compact && <button className="button button-secondary" type="button" onClick={onEdit}>修改画像</button>}</div>
    <div className="profile-summary-grid">
      <SummaryItem label="目标岗位" value={form.target_roles.join("、")} />
      <SummaryItem label="目标城市" value={form.target_locations.join("、")} />
      <SummaryItem label="招聘类型" value={form.recruitment_types.join("、")} />
      <SummaryItem label="教育背景" value={[form.education, form.graduation_year ? `${form.graduation_year} 年毕业` : null].filter(Boolean).join(" · ")} />
      <SummaryItem label="掌握技能" value={form.skills.join("、")} />
      <SummaryItem label="薪资期望" value={form.expected_salary_min !== null ? `${form.expected_salary_min.toLocaleString("zh-CN")} 元/月起` : ""} />
      <SummaryItem label="项目与经历" value={form.experience_summary ?? ""} wide />
      <SummaryItem label="排除岗位" value={form.excluded_roles.join("、")} />
      <SummaryItem label="其他要求" value={form.extra_request ?? ""} />
    </div>
    {warnings.map((warning) => <p className="profile-warning" key={warning}><WarningCircle size={17} />{warning}</p>)}
    {!compact && <div className="profile-summary-footer"><span>{createdAt ? `最近更新于 ${formatDate(createdAt)}` : ""}</span><Link className="button button-primary" to="/recommendation-runs/new">开始推荐</Link></div>}
  </section>;
}

function SummaryItem({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return <div className={`profile-summary-item${wide ? " profile-summary-item-wide" : ""}`}><span>{label}</span><strong>{value || "暂未填写"}</strong></div>;
}

function ProfileSection({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return <section className="profile-section"><div className="profile-section-heading"><h2>{title}</h2><p>{description}</p></div><div className="profile-section-fields">{children}</div></section>;
}

function TagInput({ label, values, placeholder, onChange }: { label: string; values: string[]; placeholder: string; onChange: (values: string[]) => void }) {
  const [draft, setDraft] = useState("");
  function addDraft() {
    const value = draft.trim();
    if (!value) return;
    if (values.includes(value)) {
      setDraft("");
      return;
    }
    onChange([...values, value]);
    setDraft("");
  }
  return <div className="field-group tag-field"><span>{label}</span><div className="tag-input-wrap">{values.map((value) => <span className="profile-tag" key={value}>{value}<button type="button" aria-label={`移除${value}`} onClick={() => onChange(values.filter((item) => item !== value))}><X size={13} /></button></span>)}<input aria-label={label} value={draft} placeholder={values.length ? "继续添加" : placeholder} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === ",") { event.preventDefault(); addDraft(); } }} onBlur={addDraft} /></div></div>;
}

function ChoiceField({ label, options, values, onToggle, emptyText }: { label: string; options: string[]; values: string[]; onToggle: (value: string) => void; emptyText: string }) {
  return <div className="field-group choice-field"><span>{label}</span><div className="choice-options">{options.map((option) => <button className={`choice-option ${values.includes(option) ? "choice-option-selected" : ""}`} key={option} type="button" aria-pressed={values.includes(option)} onClick={() => onToggle(option)}>{values.includes(option) && <Check size={14} />}{option}</button>)}</div><small>{emptyText}</small></div>;
}

function NumberField({ label, value, placeholder, onChange }: { label: string; value: number | null; placeholder: string; onChange: (value: number | null) => void }) {
  return <label className="field-group"><span>{label}</span><input type="number" min="0" max="1000000" value={value ?? ""} placeholder={placeholder} onChange={(event) => onChange(event.target.value ? Number(event.target.value) : null)} /></label>;
}

function TextAreaField({ label, value, placeholder, onChange }: { label: string; value: string; placeholder: string; onChange: (value: string) => void }) {
  return <label className="field-group"><span>{label}</span><textarea value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function ProfileSkeleton() {
  return <section className="profile-skeleton" aria-busy="true" aria-label="正在加载求职画像"><span className="skeleton-line skeleton-short" /><span className="skeleton-line detail-skeleton-title" /><div className="profile-skeleton-block"><span className="skeleton-line skeleton-medium" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div><div className="profile-skeleton-block"><span className="skeleton-line skeleton-medium" /><span className="skeleton-line skeleton-body" /><span className="skeleton-line skeleton-body" /></div></section>;
}

function StatePanel({ title, description, actionLabel, onAction }: { title: string; description: string; actionLabel: string; onAction: () => void }) {
  return <section className="state-panel" role="status"><WarningCircle size={28} /><h2>{title}</h2><p>{description}</p><button className="button button-secondary" type="button" onClick={onAction}>{actionLabel}</button></section>;
}
