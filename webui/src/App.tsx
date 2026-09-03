import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import AskPage from './pages/AskPage';
import CapturePage from './pages/CapturePage';
import CompilePage from './pages/CompilePage';
import GraphPage from './pages/GraphPage';
import KnowledgePage from './pages/KnowledgePage';
import MaterialsPage from './pages/MaterialsPage';
import SettingsPage from './pages/SettingsPage';

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
  return (
    <div className="app-shell">
      <aside className="app-nav">
        <div className="brand">KnowSeq</div>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            {item.label}
          </NavLink>
        ))}
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
          <Route path="*" element={<div className="page">页面不存在</div>} />
        </Routes>
      </main>
    </div>
  );
}
