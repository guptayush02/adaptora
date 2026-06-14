import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../hooks/useAuth';

function RegisterForm({ onSuccess, onSwitchToLogin }) {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
  });

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (formData.password !== formData.confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }
    if (formData.password.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }
    setLoading(true);
    const result = await register(
      formData.username,
      formData.email,
      formData.password
    );
    setLoading(false);
    if (result.success) {
      toast.success('Account created!');
      onSuccess?.();
      navigate('/home');
    } else {
      toast.error(result.error || 'Registration failed');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="auth-form">
      <div className="form-group">
        <label htmlFor="reg-username">Username</label>
        <input
          type="text"
          id="reg-username"
          name="username"
          value={formData.username}
          onChange={handleChange}
          placeholder="Choose a username"
          minLength="3"
          required
          autoFocus
        />
      </div>
      <div className="form-group">
        <label htmlFor="reg-email">Email</label>
        <input
          type="email"
          id="reg-email"
          name="email"
          value={formData.email}
          onChange={handleChange}
          placeholder="your@email.com"
          required
        />
      </div>
      <div className="form-row">
        <div className="form-group">
          <label htmlFor="reg-password">Password</label>
          <input
            type="password"
            id="reg-password"
            name="password"
            value={formData.password}
            onChange={handleChange}
            placeholder="Min 8 characters"
            minLength="8"
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="reg-confirm">Confirm</label>
          <input
            type="password"
            id="reg-confirm"
            name="confirmPassword"
            value={formData.confirmPassword}
            onChange={handleChange}
            placeholder="Confirm password"
            required
          />
        </div>
      </div>
      <button
        type="submit"
        className="btn btn-primary auth-submit"
        disabled={loading}
      >
        {loading ? 'Creating account…' : 'Create account'}
      </button>
      {onSwitchToLogin && (
        <p className="auth-link">
          Already have an account?{' '}
          <button
            type="button"
            className="btn-link auth-switch"
            onClick={onSwitchToLogin}
          >
            Sign in
          </button>
        </p>
      )}
    </form>
  );
}

export default RegisterForm;
