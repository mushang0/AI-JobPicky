import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BookmarkSimple,
  Briefcase,
  CheckCircle,
  ListChecks,
  List as Menu,
  SignOut,
  Sparkle,
  UserCircle,
  X,
} from "@phosphor-icons/react";
import { useAuth } from "../adapters/web/AuthProvider";
import { BrandMark } from "./BrandMark";

const navItems = [
  { label: "岗位池", to: "/jobs", icon: Briefcase },
  { label: "全部推荐", to: "/recommendations", icon: Sparkle },
  { label: "推荐任务", to: "/recommendation-runs", icon: ListChecks },
  { label: "我的求职画像", to: "/profile", icon: UserCircle },
  { label: "收藏岗位", to: "/saved-jobs", icon: BookmarkSimple },
];

export function AppShell() {
  const [isNavOpen, setIsNavOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const firstNavLinkRef = useRef<HTMLAnchorElement>(null);
  const { status, user, signOut } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const returnTo = `${location.pathname}${location.search}`;

  useEffect(() => {
    if (!isNavOpen) return;
    firstNavLinkRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setIsNavOpen(false);
      menuButtonRef.current?.focus();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isNavOpen]);

  async function handleAccountAction() {
    if (status !== "authenticated") {
      navigate(`/login?returnTo=${encodeURIComponent(returnTo)}`);
      return;
    }
    navigate("/jobs", { replace: true });
    await signOut();
  }

  return (
    <div className="app-frame">
      {isNavOpen && (
        <button
          className="drawer-backdrop"
          type="button"
          aria-label="关闭导航"
          onClick={() => setIsNavOpen(false)}
          tabIndex={-1}
        />
      )}

      <aside className={`sidebar ${isNavOpen ? "sidebar-open" : ""}`}>
        <div className="sidebar-topline">
          <BrandMark />
          <button
            className="icon-button drawer-close"
            type="button"
            aria-label="关闭导航"
            onClick={() => setIsNavOpen(false)}
          >
            <X size={20} />
          </button>
        </div>

        <div className="sidebar-context">
          <CheckCircle size={16} weight="fill" />
          <span>岗位事实来自公开招聘源</span>
        </div>

        <nav id="primary-navigation" className="primary-nav" aria-label="主导航">
          {navItems.map(({ label, to, icon: Icon }, index) => (
            <NavLink
              ref={index === 0 ? firstNavLinkRef : undefined}
              className={({ isActive }) => `nav-item ${isActive ? "nav-item-active" : ""}`}
              key={to}
              to={to}
              onClick={() => setIsNavOpen(false)}
            >
              <Icon size={20} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="sidebar-footer-label">当前版本</span>
          <span className="sidebar-footer-value">前端工作台</span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            type="button"
            aria-label="打开导航"
            aria-expanded={isNavOpen}
            aria-controls="primary-navigation"
            ref={menuButtonRef}
            onClick={() => setIsNavOpen(true)}
          >
            <Menu size={22} />
          </button>

          <div className="topbar-status">
            <span className="status-orb" aria-hidden="true" />
            <span>{status === "authenticated" ? "已登录" : "公开岗位预览"}</span>
          </div>

          <button
            className="topbar-account topbar-account-button"
            type="button"
            onClick={() => void handleAccountAction()}
            aria-label={status === "authenticated" ? `退出登录 ${user?.email ?? ""}` : "登录"}
          >
            <UserCircle size={20} />
            <span>{user?.email ?? "访客"}</span>
            {status === "authenticated" ? <SignOut size={16} /> : <span className="account-action">登录</span>}
          </button>
        </header>

        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
