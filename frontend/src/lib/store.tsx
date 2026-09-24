/**
 * Global app state: session, preferences, active project selection,
 * notifications badge and offline state.
 */
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, setSessionExpiredHandler, setTokens, flushQueue, queueSize, getAccessToken } from "./api";

export interface User {
  id: number;
  email: string;
  full_name: string;
  phone?: string | null;
  platform_role: string;
  status: string;
  email_verified: boolean;
  organization_id: number | null;
  avatar_color: string;
  must_change_password?: boolean;
  onboarding_completed?: boolean;
  is_demo?: boolean;
}

export interface Preferences {
  language: string;
  easy_mode: boolean;
  theme: string;
  voice_enabled: boolean;
  reminder_days: number[];
  timezone: string;
}

export interface ProjectSummary {
  id: number;
  name: string;
  stage?: string;
  is_demo?: boolean;
  readiness_overall?: number | null;
  industry?: string | null;
  state?: string | null;
  counts?: Record<string, number>;
}

interface AppCtx {
  user: User | null;
  prefs: Preferences | null;
  projects: ProjectSummary[];
  activeProject: ProjectSummary | null;
  setActiveProjectId: (id: number | null) => void;
  unread: number;
  refreshNotifications: () => Promise<void>;
  refreshUser: () => Promise<void>;
  refreshProjects: () => Promise<void>;
  logout: () => Promise<void>;
  offline: boolean;
  pendingSync: number;
}

const Ctx = createContext<AppCtx>(null as any);
export const useApp = () => useContext(Ctx);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(
    Number(localStorage.getItem("niecp.activeProject")) || null
  );
  const [unread, setUnread] = useState(0);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [pendingSync, setPendingSync] = useState(queueSize());

  const refreshUser = useCallback(async () => {
    if (!getAccessToken()) {
      setUser(null);
      return;
    }
    try {
      const me = await api<{ user: User; preferences: Preferences }>("/auth/me");
      setUser(me.user);
      setPrefs(me.preferences);
    } catch {
      /* session refresh failed — handler may have cleared tokens */
    }
  }, []);

  const refreshProjects = useCallback(async () => {
    try {
      const r = await api<{ projects: ProjectSummary[] }>("/projects");
      setProjects(r.projects);
      setActiveId((cur) => {
        if (cur && r.projects.some((p) => p.id === cur)) return cur;
        return r.projects[0]?.id ?? null;
      });
    } catch {
      /* offline */
    }
  }, []);

  const refreshNotifications = useCallback(async () => {
    try {
      const r = await api<{ unread: number }>("/notifications?unread_only=true&limit=1");
      setUnread(r.unread);
    } catch {
      /* offline */
    }
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setUser(null);
      window.location.hash = "#/login";
    });
    refreshUser();
    const onOnline = async () => {
      setOffline(false);
      const n = await flushQueue();
      setPendingSync(queueSize());
      if (n > 0) refreshProjects();
    };
    const onOffline = () => setOffline(true);
    const onQueue = (e: any) => setPendingSync(e.detail ?? queueSize());
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("niecp:queue-changed", onQueue);
    const poll = setInterval(refreshNotifications, 45000);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("niecp:queue-changed", onQueue);
      clearInterval(poll);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (user) {
      refreshProjects();
      refreshNotifications();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  useEffect(() => {
    if (activeId != null) localStorage.setItem("niecp.activeProject", String(activeId));
  }, [activeId]);

  const logout = useCallback(async () => {
    try {
      const refresh = localStorage.getItem("niecp.refresh");
      if (refresh) await api("/auth/logout", "POST", { refresh_token: refresh }).catch(() => {});
    } finally {
      setTokens(null, null);
      setUser(null);
      setProjects([]);
    }
  }, []);

  const activeProject = projects.find((p) => p.id === activeId) || null;

  return (
    <Ctx.Provider
      value={{
        user,
        prefs,
        projects,
        activeProject,
        setActiveProjectId: setActiveId,
        unread,
        refreshNotifications,
        refreshUser,
        refreshProjects,
        logout,
        offline,
        pendingSync,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export async function login(email: string, password: string) {
  const r = await api<any>("/auth/login", "POST", { email, password });
  setTokens(r.access_token, r.refresh_token);
  return r;
}
