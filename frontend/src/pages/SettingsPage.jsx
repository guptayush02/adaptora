import React from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { FiLogOut, FiUser, FiMail, FiCalendar, FiKey } from 'react-icons/fi';
import { useAuth } from '../hooks/useAuth';

function formatDate(value) {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    toast.success('Logged out');
    navigate('/');
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p className="page-subtitle">
            Your account profile and session controls.
          </p>
        </div>
      </div>

      <div className="card profile-card">
        <div className="profile-avatar">
          {(user?.username || 'U').charAt(0).toUpperCase()}
        </div>
        <div className="profile-meta">
          <div className="profile-name">{user?.username || 'User'}</div>
          <div className="profile-email">{user?.email || ''}</div>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">Profile</h2>
        <dl className="profile-list">
          <div className="profile-item">
            <dt>
              <FiUser /> Username
            </dt>
            <dd>{user?.username || '—'}</dd>
          </div>
          <div className="profile-item">
            <dt>
              <FiMail /> Email
            </dt>
            <dd>{user?.email || '—'}</dd>
          </div>
          <div className="profile-item">
            <dt>
              <FiCalendar /> Member since
            </dt>
            <dd>{formatDate(user?.created_at)}</dd>
          </div>
          <div className="profile-item">
            <dt>
              <FiKey /> User ID
            </dt>
            <dd>{user?.id || '—'}</dd>
          </div>
        </dl>
      </div>

      <div className="card">
        <h2 className="card-title">Session</h2>
        <p className="muted">
          Signing out clears your session token from this device.
        </p>
        <button
          type="button"
          className="btn btn-danger btn-icon"
          onClick={handleLogout}
        >
          <FiLogOut />
          <span>Log out</span>
        </button>
      </div>
    </div>
  );
}

export default SettingsPage;
