import { createHashRouter, Navigate, type RouteObject } from "react-router-dom";
import { AppShell } from "@/components/shell/AppShell";
import OverviewPage from "@/sections/OverviewPage";
import PositionsPage from "@/sections/PositionsPage";
import StrategiesPage from "@/sections/StrategiesPage";
import ActivityPage from "@/sections/ActivityPage";
import SettingsPage from "@/sections/SettingsPage";

/**
 * Shared route tree: consumed by the app's `createHashRouter` (hash history avoids needing
 * a server rewrite rule) and reusable by tests that prefer a `MemoryRouter` (e.g.
 * `createMemoryRouter(routes, { initialEntries: [...] })`).
 */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/overview" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "positions", element: <PositionsPage /> },
      { path: "strategies", element: <StrategiesPage /> },
      { path: "activity", element: <ActivityPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/overview" replace /> },
    ],
  },
];

export const router = createHashRouter(routes);
