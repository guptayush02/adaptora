import React, { useState, useEffect, useMemo } from 'react';
import toast from 'react-hot-toast';
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
} from 'recharts';
import {
  FiActivity,
  FiCpu,
  FiDatabase,
  FiHardDrive,
  FiRefreshCw,
  FiTrendingDown,
} from 'react-icons/fi';
import { queryService, dynamicAgentService } from '../services/api';
import { useAuth } from '../hooks/useAuth';

const RANGE_OPTIONS = [
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
  { value: 'all', label: 'All time' },
];

const COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

const formatNumber = (n) =>
  n === null || n === undefined ? '0' : Number(n).toLocaleString();

function StatCard({ label, value, icon: Icon, accent }) {
  return (
    <div className="stat-card">
      <div className={`stat-card-icon stat-accent-${accent}`}>
        <Icon />
      </div>
      <div className="stat-card-body">
        <div className="stat-card-label">{label}</div>
        <div className="stat-card-value">{value}</div>
      </div>
    </div>
  );
}

function ChartCard({ title, action, children, empty }) {
  return (
    <div className="chart-card">
      <div className="chart-card-header">
        <h3>{title}</h3>
        {action}
      </div>
      <div className="chart-card-body">
        {empty ? (
          <div className="chart-empty">No data for the current filters.</div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}

function HomePage() {
  const { user } = useAuth();
  const [stats, setStats] = useState(null);
  const [savings, setSavings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    range: '30d',
    model: '',
    complexity: '',
  });

  useEffect(() => {
    if (!user?.id) return;
    loadStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, filters.range, filters.model, filters.complexity]);

  const loadStats = async () => {
    try {
      setLoading(true);
      const params = { range: filters.range };
      if (filters.model) params.model = filters.model;
      if (filters.complexity) params.complexity = filters.complexity;
      const data = await queryService.getUserStats(user.id, params);
      setStats(data);
    } catch (error) {
      toast.error('Failed to load statistics');
      console.error('Stats error:', error);
    } finally {
      setLoading(false);
    }
    // Response-compaction savings — separate endpoint, never block stats on it.
    try {
      setSavings(await dynamicAgentService.getSavings());
    } catch (error) {
      console.error('Savings error:', error);
    }
  };

  const handleFilterChange = (key) => (e) =>
    setFilters((prev) => ({ ...prev, [key]: e.target.value }));

  const availableModels = stats?.available_models || [];
  const availableComplexities = stats?.available_complexities || [];

  const summary = useMemo(
    () => [
      {
        label: 'Total Queries',
        value: formatNumber(stats?.total_queries),
        icon: FiActivity,
        accent: 'indigo',
      },
      {
        label: 'Total Tokens',
        value: formatNumber(stats?.total_tokens),
        icon: FiCpu,
        accent: 'emerald',
      },
      {
        label: 'Avg Tokens / Query',
        value: stats?.avg_tokens_per_query
          ? Number(stats.avg_tokens_per_query).toFixed(1)
          : '0',
        icon: FiDatabase,
        accent: 'amber',
      },
      {
        label: 'Cache Hit Rate',
        value: `${(stats?.cache_hit_rate || 0).toFixed(1)}%`,
        icon: FiHardDrive,
        accent: 'violet',
      },
      {
        label: 'Prompt Tokens Saved',
        value: `${formatNumber(
          stats?.optimization_summary?.saved_tokens
        )} (${(stats?.optimization_summary?.savings_percentage || 0).toFixed(1)}%)`,
        icon: FiTrendingDown,
        accent: 'rose',
      },
      {
        label: 'Response Tokens Saved',
        value: `${formatNumber(savings?.tokens_saved)} (${(
          savings?.reduction_pct || 0
        ).toFixed(1)}%)`,
        icon: FiTrendingDown,
        accent: 'emerald',
      },
    ],
    [stats, savings]
  );

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Welcome back, {user?.username || 'there'} 👋</h1>
          <p className="page-subtitle">
            Track how Adaptora is routing your prompts and saving tokens.
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary btn-icon"
          onClick={loadStats}
          disabled={loading}
        >
          <FiRefreshCw className={loading ? 'spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      <div className="filters-bar">
        <div className="filter-group">
          <label>Range</label>
          <select value={filters.range} onChange={handleFilterChange('range')}>
            {RANGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-group">
          <label>Model</label>
          <select value={filters.model} onChange={handleFilterChange('model')}>
            <option value="">All models</option>
            {availableModels.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-group">
          <label>Complexity</label>
          <select
            value={filters.complexity}
            onChange={handleFilterChange('complexity')}
          >
            <option value="">All complexity</option>
            {availableComplexities.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        {(filters.model || filters.complexity) && (
          <button
            type="button"
            className="btn btn-link"
            onClick={() =>
              setFilters((prev) => ({ ...prev, model: '', complexity: '' }))
            }
          >
            Clear filters
          </button>
        )}
      </div>

      <div className="stat-grid">
        {summary.map((s) => (
          <StatCard key={s.label} {...s} />
        ))}
      </div>

      <div className="charts-grid">
        <ChartCard
          title="Tokens over time"
          empty={!stats?.tokens_over_time?.length}
        >
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={stats?.tokens_over_time || []}>
              <defs>
                <linearGradient id="tokensGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Area
                type="monotone"
                dataKey="tokens"
                stroke="#6366f1"
                strokeWidth={2}
                fill="url(#tokensGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Queries over time"
          empty={!stats?.queries_over_time?.length}
        >
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={stats?.queries_over_time || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="queries"
                stroke="#10b981"
                strokeWidth={2}
                dot={{ fill: '#10b981', r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Tokens by model"
          empty={!stats?.tokens_by_model?.length}
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={stats?.tokens_by_model || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="model" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="tokens" fill="#6366f1" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Model distribution"
          empty={!stats?.model_distribution?.length}
        >
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={stats?.model_distribution || []}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) =>
                  `${name} (${(percent * 100).toFixed(0)}%)`
                }
                outerRadius={90}
                fill="#8884d8"
                dataKey="queries"
              >
                {(stats?.model_distribution || []).map((entry, index) => (
                  <Cell key={`c-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Complexity breakdown"
          empty={!stats?.complexity_distribution?.length}
        >
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={stats?.complexity_distribution || []}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={90}
                paddingAngle={4}
                dataKey="queries"
                label={({ name, percent }) =>
                  `${name} (${(percent * 100).toFixed(0)}%)`
                }
              >
                {(stats?.complexity_distribution || []).map((entry, index) => (
                  <Cell key={`cc-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Prompt optimization (original vs optimized)"
          empty={!stats?.optimization_over_time?.length}
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={stats?.optimization_over_time || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Bar
                dataKey="original"
                name="Original"
                fill="#ef4444"
                radius={[6, 6, 0, 0]}
              />
              <Bar
                dataKey="optimized"
                name="Optimized"
                fill="#10b981"
                radius={[6, 6, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="MCP response tokens (raw vs sent)"
          empty={!savings?.recent?.length}
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={savings?.recent || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={0} angle={-25} textAnchor="end" height={60} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend />
              <Bar
                dataKey="raw"
                name="Raw (before)"
                fill="#ef4444"
                radius={[6, 6, 0, 0]}
              />
              <Bar
                dataKey="sent"
                name="Sent (after)"
                fill="#10b981"
                radius={[6, 6, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Model performance" empty={!stats?.model_stats?.length}>
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Queries</th>
                  <th>Tokens</th>
                  <th>Avg</th>
                  <th>Cache hits</th>
                </tr>
              </thead>
              <tbody>
                {(stats?.model_stats || []).map((row) => (
                  <tr key={row.model}>
                    <td>{row.model}</td>
                    <td>{formatNumber(row.query_count)}</td>
                    <td>{formatNumber(row.total_tokens)}</td>
                    <td>{row.avg_tokens?.toFixed(1) || 0}</td>
                    <td>{row.cache_hits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ChartCard>
      </div>
    </div>
  );
}

export default HomePage;
