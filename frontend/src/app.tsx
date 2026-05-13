import { lazy, Suspense, type ReactNode } from "react";
import { RouterProvider, createBrowserRouter } from "react-router-dom";
import { AppShell } from "./components/app-shell";

const ProjectsPage = lazy(() => import("./features/projects/projects-page").then((module) => ({ default: module.ProjectsPage })));
const ProjectDetailPage = lazy(() => import("./features/projects/project-detail-page").then((module) => ({ default: module.ProjectDetailPage })));
const NewGraphPage = lazy(() => import("./features/graphs/new-graph-page").then((module) => ({ default: module.NewGraphPage })));
const GraphDetailPage = lazy(() => import("./features/graphs/graph-detail-page").then((module) => ({ default: module.GraphDetailPage })));
const GraphRunPage = lazy(() => import("./features/graph-runs/graph-run-page").then((module) => ({ default: module.GraphRunPage })));

function lazyPage(page: ReactNode) {
  return <Suspense fallback={<p className="text-sm text-muted">Loading...</p>}>{page}</Suspense>;
}

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: lazyPage(<ProjectsPage />) },
      { path: "/projects/:projectId", element: lazyPage(<ProjectDetailPage />) },
      { path: "/graphs/new", element: lazyPage(<NewGraphPage />) },
      { path: "/graphs/:graphId", element: lazyPage(<GraphDetailPage />) },
      { path: "/graph-runs/:graphRunId", element: lazyPage(<GraphRunPage />) }
    ]
  }
]);

export function App() {
  return <RouterProvider router={router} />;
}
