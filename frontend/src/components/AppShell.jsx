import React, { useState } from 'react';
import { FiMenu } from 'react-icons/fi';
import { useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import { useAuth } from '../hooks/useAuth';

const PAGE_TITLES = {
  '/home': 'Home',
  '/prompts': 'Prompts',
  '/keys': 'API Keys',
  '/settings': 'Settings',
};

function AppShell({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const { user } = useAuth();

  const title =
    PAGE_TITLES[location.pathname] ||
    Object.entries(PAGE_TITLES).find(([path]) =>
      location.pathname.startsWith(path)
    )?.[1] ||
    'Adaptora';

  return (
    <div className="app-shell">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="app-main">
        <header className="app-topbar">
          <button
            type="button"
            className="topbar-menu-btn"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
          >
            <FiMenu />
          </button>
          <h2 className="topbar-title">{title}</h2>
          <div className="topbar-user">
            <span className="topbar-user-name">{user?.username || 'User'}</span>
            <div className="topbar-avatar">
              {(user?.username || 'U').charAt(0).toUpperCase()}
            </div>
          </div>
        </header>

        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}

export default AppShell;
