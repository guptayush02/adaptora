import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../hooks/useAuth';

function LoginForm({ onSuccess, onSwitchToRegister }) {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({ email: '', password: '' });

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    const result = await login(formData.email, formData.password);
    setLoading(false);
    if (result.success) {
      toast.success('Welcome back!');
      onSuccess?.();
      navigate('/home');
    } else {
      toast.error(result.error || 'Login failed');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="auth-form">
      <div className="form-group">
        <label htmlFor="login-email">Email</label>
        <input
          type="email"
          id="login-email"
          name="email"
          value={formData.email}
          onChange={handleChange}
          placeholder="your@email.com"
          required
          autoFocus
        />
      </div>
      <div className="form-group">
        <label htmlFor="login-password">Password</label>
        <input
          type="password"
          id="login-password"
          name="password"
          value={formData.password}
          onChange={handleChange}
          placeholder="Enter your password"
          required
        />
      </div>
      <button
        type="submit"
        className="btn btn-primary auth-submit"
        disabled={loading}
      >
        {loading ? 'Signing in…' : 'Sign in'}
      </button>
      {onSwitchToRegister && (
        <p className="auth-link">
          Don't have an account?{' '}
          <button
            type="button"
            className="btn-link auth-switch"
            onClick={onSwitchToRegister}
          >
            Create one
          </button>
        </p>
      )}
    </form>
  );
}

export default LoginForm;
