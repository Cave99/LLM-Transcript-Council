import { RouterProvider, createBrowserRouter } from "react-router-dom";
import { AppShell } from "./components/app-shell";
import { ProjectsPage } from "./features/projects/projects-page";
import { ProjectDetailPage } from "./features/projects/project-detail-page";
import { NewGraphPage } from "./features/graphs/new-graph-page";
import { GraphDetailPage } from "./features/graphs/graph-detail-page";
import { GraphRunPage } from "./features/graph-runs/graph-run-page";

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <ProjectsPage /> },
      { path: "/projects/:projectId", element: <ProjectDetailPage /> },
      { path: "/graphs/new", element: <NewGraphPage /> },
      { path: "/graphs/:graphId", element: <GraphDetailPage /> },
      { path: "/graph-runs/:graphRunId", element: <GraphRunPage /> }
    ]
  }
]);

export function App() {
  return <RouterProvider router={router} />;
}

