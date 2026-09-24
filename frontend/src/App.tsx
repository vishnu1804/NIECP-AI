import React, { useEffect } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { I18nProvider } from "./lib/i18n";
import { AppProvider, useApp } from "./lib/store";
import Layout from "./components/Layout";
import Home from "./pages/Home";
import { Login, Register, Forgot, Reset } from "./pages/Auth";
import Onboarding from "./pages/Onboarding";
import Dashboard from "./pages/Dashboard";
import Projects from "./pages/Projects";
import Profile from "./pages/Profile";
import Analysis from "./pages/Analysis";
import Approvals from "./pages/Approvals";
import Documents from "./pages/Documents";
import Applications from "./pages/Applications";
import Compliance from "./pages/Compliance";
import CalendarPage from "./pages/Calendar";
import Queries from "./pages/Queries";
import Inspections from "./pages/Inspections";
import ProjectSchemes from "./pages/ProjectSchemes";
import SchemesGlobal from "./pages/SchemesGlobal";
import GovPortals from "./pages/GovPortals";
import ChangeRadar from "./pages/ChangeRadar";
import AssistantPage from "./pages/Assistant";
import Notifications from "./pages/Notifications";
import Integrations from "./pages/Integrations";
import MsmePage from "./pages/Msme";
import Settings from "./pages/Settings";
import Admin from "./pages/Admin";

function Protected({ children }: { children: React.ReactNode }) {
  const { user } = useApp();
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function Shell() {
  return (
    <Layout />
  );
}

export default function App() {
  return (
    <I18nProvider>
      <AppProvider>
        <HashRouter>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<Forgot />} />
            <Route path="/reset-password" element={<Reset />} />
            <Route element={<Protected><Shell /></Protected>}>
              <Route path="/onboarding" element={<Onboarding />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/projects" element={<Projects />} />
              <Route path="/projects/:projectId" element={<Projects />} />
              <Route path="/projects/:projectId/profile" element={<Profile />} />
              <Route path="/projects/:projectId/analysis" element={<Analysis />} />
              <Route path="/projects/:projectId/approvals" element={<Approvals />} />
              <Route path="/projects/:projectId/msme" element={<MsmePage />} />
              <Route path="/projects/:projectId/documents" element={<Documents />} />
              <Route path="/projects/:projectId/applications" element={<Applications />} />
              <Route path="/projects/:projectId/compliance" element={<Compliance />} />
              <Route path="/projects/:projectId/calendar" element={<CalendarPage />} />
              <Route path="/projects/:projectId/queries" element={<Queries />} />
              <Route path="/projects/:projectId/inspections" element={<Inspections />} />
              <Route path="/projects/:projectId/schemes" element={<ProjectSchemes />} />
              <Route path="/projects/:projectId/analytics" element={<AnalyticsRoute />} />
              <Route path="/government-portals" element={<GovPortals />} />
              <Route path="/schemes" element={<SchemesGlobal />} />
              <Route path="/change-radar" element={<ChangeRadar />} />
              <Route path="/assistant" element={<AssistantPage />} />
              <Route path="/notifications" element={<Notifications />} />
              <Route path="/settings/integrations" element={<Integrations />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/admin" element={<Admin />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </HashRouter>
      </AppProvider>
    </I18nProvider>
  );
}

function AnalyticsRoute() {
  const Analytics = React.lazy(() => import("./pages/Analytics"));
  return (
    <React.Suspense fallback={<div className="p-10 text-sm text-slate-500">Loading…</div>}>
      <Analytics />
    </React.Suspense>
  );
}
