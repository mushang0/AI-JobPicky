import { useEffect, useState } from "react";
import { ArrowRight, Check, LockKey, ShieldCheck } from "@phosphor-icons/react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../adapters/web/AuthProvider";
import { BrandMark } from "../../components/BrandMark";
import { ApiError } from "../../shared/api/client";
import { getApiErrorMessage } from "../../shared/api/errorMessage";
import { validateCredentials, validateRegistration } from "../../shared/validation/auth";

type AuthMode = "login" | "register";
type FormErrors = Partial<Record<"email" | "password" | "passwordConfirmation", string>>;

function safeReturnTo(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/jobs";
}

export function AuthPage({ mode }: { mode: AuthMode }) {
  const { status, signIn, signUp } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const returnTo = safeReturnTo(searchParams.get("returnTo"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [errors, setErrors] = useState<FormErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (status === "authenticated" && location.pathname !== returnTo) {
      navigate(returnTo, { replace: true });
    }
  }, [location.pathname, navigate, returnTo, status]);

  const isRegister = mode === "register";
  const otherAuthPath = isRegister ? "/login" : "/register";
  const otherAuthLabel = isRegister ? "已有账号，直接登录" : "还没有账号，注册一个";
  const otherAuthUrl = `${otherAuthPath}?returnTo=${encodeURIComponent(returnTo)}`;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = isRegister
      ? validateRegistration({ email, password, passwordConfirmation })
      : validateCredentials({ email, password });

    setErrors(nextErrors);
    setSubmitError(null);
    if (Object.keys(nextErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      if (isRegister) await signUp({ email: email.trim(), password });
      else await signIn({ email: email.trim(), password });
      navigate(returnTo, { replace: true });
    } catch (error: unknown) {
      if (error instanceof ApiError) {
        setSubmitError(getApiErrorMessage(error.code, error.message));
      } else {
        setSubmitError("网络连接失败，请稍后重试。");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-context" aria-label="JobPicky 介绍">
        <BrandMark />
        <p className="auth-kicker">JobPicky 求职工作台</p>
        <h1>登录后查找岗位</h1>
        <p className="auth-context-copy">登录后可以搜索、筛选和收藏岗位，并查看官方投递入口。</p>
        <div className="auth-points">
          <span><Check size={16} weight="bold" />岗位来自公开招聘渠道</span>
          <span><ShieldCheck size={16} weight="bold" />登录状态只保存在当前设备</span>
        </div>
      </section>

      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-panel-heading">
          <div className="auth-icon" aria-hidden="true">
            {isRegister ? <ShieldCheck size={22} /> : <LockKey size={22} />}
          </div>
          <div>
            <p className="auth-kicker">{isRegister ? "创建账号" : "欢迎回来"}</p>
            <h2 id="auth-title">{isRegister ? "注册 JobPicky" : "登录 JobPicky"}</h2>
          </div>
        </div>

        <form className="auth-form" onSubmit={handleSubmit} noValidate>
          <label className="field-group">
            <span>邮箱</span>
            <input
              type="email"
              value={email}
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={Boolean(errors.email)}
              aria-describedby={errors.email ? "email-error" : undefined}
              placeholder="name@example.com"
            />
            {errors.email && <small id="email-error" className="field-error">{errors.email}</small>}
          </label>

          <label className="field-group">
            <span>密码</span>
            <input
              type="password"
              value={password}
              autoComplete={isRegister ? "new-password" : "current-password"}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={Boolean(errors.password)}
              aria-describedby={errors.password ? "password-error" : undefined}
              placeholder="请输入密码"
            />
            {errors.password && <small id="password-error" className="field-error">{errors.password}</small>}
          </label>

          {isRegister && (
            <label className="field-group">
              <span>确认密码</span>
              <input
                type="password"
                value={passwordConfirmation}
                autoComplete="new-password"
                onChange={(event) => setPasswordConfirmation(event.target.value)}
                aria-invalid={Boolean(errors.passwordConfirmation)}
                aria-describedby={errors.passwordConfirmation ? "password-confirmation-error" : undefined}
                placeholder="再次输入密码"
              />
              {errors.passwordConfirmation && <small id="password-confirmation-error" className="field-error">{errors.passwordConfirmation}</small>}
            </label>
          )}

          {submitError && <p className="form-error" role="alert">{submitError}</p>}

          <button className="button button-primary auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "提交中" : isRegister ? "注册并进入" : "登录"}
            {!isSubmitting && <ArrowRight size={18} />}
          </button>
        </form>

        <p className="auth-switch">
          <Link to={otherAuthUrl}>{otherAuthLabel}</Link>
        </p>
      </section>
    </main>
  );
}

export function LoginPage() {
  return <AuthPage mode="login" />;
}

export function RegisterPage() {
  return <AuthPage mode="register" />;
}
