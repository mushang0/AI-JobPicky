import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "../adapters/web/AuthProvider";
import { AppShell } from "../components/AppShell";
import { LoginPage, RegisterPage } from "../features/auth/AuthPage";
import { JobDetailPage } from "../features/jobs/JobDetailPage";
import { JobsPage } from "../features/jobs/JobsPage";
import { ProfilePage } from "../features/profile/ProfilePage";
import { AllRecommendationsPage, NewRecommendationPage, RecommendationRunDetailPage, RecommendationRunsPage } from "../features/recommendations/RecommendationsPages";
import { SavedJobsPage } from "../features/saved/SavedJobsPage";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route element={<AppShell />}>
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/recommendations" element={<AllRecommendationsPage />} />
            <Route path="/recommendation-runs" element={<RecommendationRunsPage />} />
            <Route path="/recommendation-runs/new" element={<NewRecommendationPage />} />
            <Route path="/recommendation-runs/:runId" element={<RecommendationRunDetailPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/saved-jobs" element={<SavedJobsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/jobs" replace />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") return <div className="route-loading" role="status">正在恢复登录状态</div>;
  if (status !== "authenticated") {
    const returnTo = `${location.pathname}${location.search}`;
    return <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }
  return <Outlet />;
}
