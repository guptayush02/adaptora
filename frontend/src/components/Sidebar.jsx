import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  FiHome,
  FiMessageSquare,
  FiKey,
  FiSettings,
  FiX,
  FiZap,
  FiCpu,
  FiServer,
} from 'react-icons/fi';
import { useAuth } from '../hooks/useAuth';

const NAV_ITEMS = [
  { to: '/home', label: 'Home', icon: FiHome },
  { to: '/prompts', label: 'Prompts', icon: FiMessageSquare },
  { to: '/agent', label: 'Dynamic Agent', icon: FiCpu },
  { to: '/tools', label: 'Cached Tools', icon: FiServer },
  { to: '/keys', label: 'API Keys', icon: FiKey },
  { to: '/settings', label: 'Settings', icon: FiSettings },
];

function Sidebar({ open, onClose }) {
  const { user } = useAuth();

  return (
    <>
      <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <FiZap className="sidebar-brand-icon" />
            <span>{import.meta.env.VITE_APP_NAME || 'Token Optimizer'}</span>
          </div>
          <button
            type="button"
            className="sidebar-close"
            onClick={onClose}
            aria-label="Close menu"
          >
            <FiX />
          </button>
        </div>

        <nav className="sidebar-nav">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className={({ isActive }) =>
                `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`
              }
            >
              <Icon className="sidebar-link-icon" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="sidebar-user">
            <div className="sidebar-avatar">
              {(user?.username || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="sidebar-user-meta">
              <div className="sidebar-user-name">{user?.username || 'User'}</div>
              <div className="sidebar-user-email">{user?.email || ''}</div>
            </div>
          </div>
        </div>
      </aside>

      {open && <div className="sidebar-backdrop" onClick={onClose} />}
    </>
  );
}

export default Sidebar;
