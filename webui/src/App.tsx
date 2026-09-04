import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import AskPage from './pages/AskPage';
import CapturePage from './pages/CapturePage';
import CompilePage from './pages/CompilePage';
import FloatingPage from './pages/FloatingPage';
import GraphPage from './pages/GraphPage';
import KnowledgePage from './pages/KnowledgePage';
import MaterialsPage from './pages/MaterialsPage';
import SettingsPage from './pages/SettingsPage';
import StatusRail from './status/StatusRail';
import { StatusProvider } from './status/StatusContext';

const NAV = [
  { to: '/ask', label: '问答' },
  { to: '/graph', label: '图谱' },
  { to: '/knowledge', label: '知识库' },
  { to: '/compile', label: '编译' },
  { to: '/materials', label: '素材' },
  { to: '/capture', label: '采集控制' },
  { to: '/settings', label: '设置' },
];

export default function App() {
  const { pathname } = useLocation();
  // 悬浮控件窗（T-504 / REQ-504）：裸渲染控件本体——不进 app-shell、
  // 不挂 StatusProvider（避免控制台三路轮询在悬浮窗里重复跑）
  if (pathname === '/floating') {
    return <FloatingPage />;
  }
  return (
    <StatusProvider>
      <div className="app-shell">
        <aside className="app-nav">
          <div className="brand">
            KnowSeq
            <span className="brand-sub">local knowledge agent</span>
          </div>
          <nav>
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => (isActive ? 'active' : '')}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <StatusRail />
        </aside>
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/ask" replace />} />
            <Route path="/ask" element={<AskPage />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/compile" element={<CompilePage />} />
            <Route path="/materials" element={<MaterialsPage />} />
            <Route path="/capture" element={<CapturePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route
              path="*"
              element={
                <div className="page">
                  <div className="empty">
                    <strong>404</strong>页面不存在
                  </div>
                </div>
              }
            />
          </Routes>
        </main>
      </div>
    </StatusProvider>
  );
}
