import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation, useNavigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Screening from './pages/Screening'
import Interviews from './pages/Interviews'
import Onboarding from './pages/Onboarding'
import Communications from './pages/Communications'
import Settings from './pages/Settings'
import Assessment from './pages/Assessment'
import ClientReview from './pages/ClientReview'
import GlobalCandidateTimelineModal from './components/GlobalCandidateTimelineModal'
import CandidateDashboard from './pages/CandidateDashboard'
import JobPostings from './pages/JobPostings'
import Investigator from './pages/Investigator'
import { api } from './api/client'
import './App.css'
import Login from './pages/Login'

window.onerror = function(msg, src, lineno, colno, error) {
  document.body.innerHTML += `<div style="position:fixed;top:0;left:0;right:0;background:red;color:white;z-index:9999;padding:20px;font-family:monospace"><b>Global Error:</b> ${msg}<br/>${error?.stack}</div>`;
};

window.addEventListener("unhandledrejection", function(event) {
  document.body.innerHTML += `<div style="position:fixed;top:0;left:0;right:0;background:orange;color:white;z-index:9999;padding:20px;font-family:monospace"><b>Unhandled Promise:</b> ${event.reason?.message || event.reason}</div>`;
});

import { AuthProvider, useAuth } from './contexts/AuthContext'
import ChangePasswordModal from './components/ChangePasswordModal'
import { ErrorBoundary } from './components/ErrorBoundary'
const pageNames = {
  '/dashboard': 'Dashboard',
  '/screening': 'AI Screening',
  '/interviews': 'Interviews',
  '/client-review': 'Client Review',
  '/onboarding': 'Onboarding',
  '/communications': 'Communications',
  '/settings': 'Settings',
  '/candidate-portal': 'Candidate Portal',
  '/job-postings': 'Job Postings',
  '/investigator': 'Investigator Agent'
}


function ProtectedRoute({ children }) {
  const { user } = useAuth();
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function Topbar() {
  const location = useLocation()
  const navigate = useNavigate()
  const currentPage = pageNames[location.pathname] || 'Dashboard'

  // Theme state
  const [theme, setTheme] = useState(localStorage.getItem('theme') || 'light')

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  function toggleTheme() {
    setTheme(prev => prev === 'light' ? 'dark' : 'light')
  }

  // Notifications states
  const [notifOpen, setNotifOpen] = useState(false)
  const [activities, setActivities] = useState([])
  const [hasNewNotif, setHasNewNotif] = useState(true)

  // Search states
  const [searchQuery, setSearchQuery] = useState('')
  const [candidates, setCandidates] = useState([])
  const [searchResults, setSearchResults] = useState([])
  const [showSearchDropdown, setShowSearchDropdown] = useState(false)

  // Fetch activities
  async function fetchActivities() {
    try {
      const data = await api.getActivity()
      setActivities(data)
    } catch (e) {
      console.error(e)
    }
  }

  // Handle bell click
  function handleBellClick() {
    setNotifOpen(!notifOpen)
    setHasNewNotif(false)
    if (!notifOpen) {
      fetchActivities()
    }
  }

  // Fetch all candidates on search focus
  async function handleSearchFocus() {
    try {
      const cands = await api.getCandidates()
      setCandidates(cands)
      setShowSearchDropdown(true)
    } catch (e) {
      console.error(e)
    }
  }

  // Real-time search filter
  function handleSearchChange(e) {
    const val = e.target.value
    setSearchQuery(val)
    if (!val.trim()) {
      setSearchResults([])
      return
    }
    const filtered = candidates.filter(c => 
      c.name.toLowerCase().includes(val.toLowerCase()) ||
      (c.role && c.role.toLowerCase().includes(val.toLowerCase())) ||
      c.status.toLowerCase().includes(val.toLowerCase())
    )
    setSearchResults(filtered)
  }

  // Routing candidate selection
  function handleSelectCandidate(cand) {
    setSearchQuery('')
    setSearchResults([])
    setShowSearchDropdown(false)
    window.showCandidateTimeline(cand.id)
  }

  return (
    <div className="topbar">
      <div className="topbar-left">
        <div className="topbar-breadcrumb">
          Derisk360 / <span>{currentPage}</span>
        </div>
      </div>
      
      {/* Search Input Container */}
      <div className="topbar-search" style={{ position: 'relative' }}>
        <span className="topbar-search-icon">🔍</span>
        <input 
          placeholder="Search candidates, jobs..." 
          value={searchQuery}
          onChange={handleSearchChange}
          onFocus={handleSearchFocus}
          onBlur={() => setTimeout(() => setShowSearchDropdown(false), 200)}
        />
        <span className="topbar-search-kbd">⌘K</span>

        {/* Search Autocomplete Dropdown */}
        {showSearchDropdown && searchQuery.trim() && (
          <div className="search-dropdown-panel" onMouseDown={e => e.preventDefault()}>
            {searchResults.length === 0 ? (
              <div className="search-dropdown-empty">No candidates found matching "{searchQuery}"</div>
            ) : (
              searchResults.map(c => (
                <div 
                  key={c.id} 
                  className="search-dropdown-item" 
                  onClick={() => handleSelectCandidate(c)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className="search-cand-name">{c.name}</span>
                    <span className={`status-badge status-${c.status}`} style={{ fontSize: '.6rem', padding: '.15rem .45rem', textTransform: 'uppercase' }}>
                      {c.status}
                    </span>
                  </div>
                  <div className="search-cand-role">{c.role || 'General Position'}</div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <div className="topbar-right" style={{ position: 'relative' }}>
        <div className="topbar-btn" onClick={toggleTheme} title="Toggle Light/Dark Theme">
          {theme === 'light' ? '🌙' : '☀️'}
        </div>
        <div className="topbar-btn" onClick={handleBellClick}>
          🔔
          {hasNewNotif && <div className="notif-dot"></div>}
        </div>
        <div className="topbar-avatar">S</div>

        {/* Notifications Dropdown */}
        {notifOpen && (
          <div className="notif-dropdown-panel" onMouseDown={e => e.preventDefault()}>
            <div className="notif-dropdown-header">
              <span>Notifications</span>
              <button onClick={() => setNotifOpen(false)} style={{ background: 'none', border: 'none', color: 'var(--blue)', fontSize: '.75rem', cursor: 'pointer' }}>Close</button>
            </div>
            <div className="notif-dropdown-list">
              {activities.length === 0 ? (
                <div className="notif-dropdown-empty">No recent activity logs</div>
              ) : (
                activities.slice(0, 8).map(act => (
                  <div key={act.id} className="notif-dropdown-item">
                    <div className="notif-item-icon" style={{ background: `${act.color}15`, color: act.color }}>
                      {act.icon}
                    </div>
                    <div className="notif-item-content">
                      <div className="notif-item-title">{act.action}</div>
                      <div className="notif-item-desc">{act.description}</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function AppContent() {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const { user, logout } = useAuth();
  const activeRole = user?.role === 'recruiter' ? 'Recruiting' : user?.role === 'delivery_head' ? 'Operational head' : user?.role === 'candidate' ? 'candidate' : 'Technical panel';
  const [toast, setToast] = useState(null)
  const [globalCandidateId, setGlobalCandidateId] = useState(null)
  const location = useLocation()
  const navigate = useNavigate()
  const isAssessmentPage = location.pathname.startsWith('/assessment/')

  useEffect(() => {
    window.showCandidateTimeline = (candidateId) => {
      setGlobalCandidateId(candidateId)
    }
    return () => {
      delete window.showCandidateTimeline
    }
  }, [])

  function showToast(message) {
    setToast(message)
    setTimeout(() => {
      setToast(null)
    }, 3000)
  }

  function handleRoleChange(newRole) {
    setActiveRole(newRole)
    localStorage.setItem('activeRole', newRole)
    // Dispatch a custom event to notify components that the role changed
    window.dispatchEvent(new Event('roleChanged'))
    navigate('/dashboard')
  }

  const isLoginPage = location.pathname === '/login';

  if (isAssessmentPage) {
    return (
      <div className="app-container">
        <main className="main-content" style={{ margin: 0, padding: 0 }}>
          <Routes>
            <Route path="/assessment/:token" element={<Assessment />} />
          </Routes>
        </main>
      </div>
    )
  }

  if (isLoginPage) {
    return (
      <div className="app-container">
        <main className="main-content" style={{ margin: 0, padding: 0 }}>
          <Routes>
            <Route path="/login" element={<Login />} />
          </Routes>
        </main>
      </div>
    )
  }

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <img src="/derisk_logo.png" alt="Derisk360 Logo" style={{ width: '28px', height: '28px', borderRadius: '6px', objectFit: 'contain' }} />
            {sidebarOpen && (
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span className="sidebar-title">Derisk360</span>
                <span className="sidebar-subtitle" style={{ fontSize: '0.65rem', color: 'var(--t3)', fontWeight: '500', marginTop: '2px' }}>
                  {activeRole === 'Recruiting' 
                    ? 'Enterprise Recruitment' 
                    : activeRole === 'Technical panel' 
                      ? 'Technical Evaluator Portal' 
                      : 'Operations & Delivery Hub'}
                </span>
              </div>
            )}
          </div>
          <button className="sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)}>
            {sidebarOpen ? '◁' : '▷'}
          </button>
        </div>



        <nav className="sidebar-nav">
          {activeRole === 'candidate' ? (
            <NavLink to="/candidate-portal" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon">🎯</span>
              {sidebarOpen && <span>Candidate Portal</span>}
            </NavLink>
          ) : (
            <NavLink to="/dashboard" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon">📊</span>
              {sidebarOpen && (
                <span>
                  {activeRole === 'Recruiting' 
                    ? 'Recruitment Board' 
                    : activeRole === 'Operational head' 
                      ? 'Delivery Board' 
                      : 'My Interviews'}
                </span>
              )}
            </NavLink>
          )}
          
          {activeRole === 'Recruiting' && (
            <>
              <NavLink to="/job-postings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span className="nav-icon">📢</span>
                {sidebarOpen && <span>Job Postings</span>}
              </NavLink>
              <NavLink to="/screening" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span className="nav-icon">🧠</span>
                {sidebarOpen && <span>AI Screening</span>}
              </NavLink>
              <NavLink to="/investigator" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span className="nav-icon">🕵️</span>
                {sidebarOpen && <span>Investigator Agent</span>}
              </NavLink>
              <NavLink to="/interviews" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span className="nav-icon">💻</span>
                {sidebarOpen && <span>Tech Panel</span>}
              </NavLink>
              <NavLink to="/client-review" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span className="nav-icon">💼</span>
                {sidebarOpen && <span>Client Review</span>}
              </NavLink>
              <NavLink to="/onboarding" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span className="nav-icon">👥</span>
                {sidebarOpen && <span>Onboarding</span>}
              </NavLink>
              <NavLink to="/communications" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                <span className="nav-icon">💬</span>
                {sidebarOpen && <span>Communications</span>}
              </NavLink>
            </>
          )}

          {activeRole !== 'Technical panel' && activeRole !== 'candidate' && (
            <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-icon">⚙️</span>
              {sidebarOpen && <span>Settings</span>}
            </NavLink>
          )}


        </nav>

        {sidebarOpen && (
          <div className="sidebar-user" style={{ display: 'flex', flexDirection: 'column', alignItems: 'stretch', padding: '12px', gap: '8px', borderTop: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div className="sidebar-user-avatar">{user?.email ? user.email[0].toUpperCase() : 'U'}</div>
              <div className="sidebar-user-info" style={{ overflow: 'hidden' }}>
                <div className="sidebar-user-name" title={user?.email} style={{ textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                  {user?.email?.split('@')[0] || 'User'}
                </div>
                <div className="sidebar-user-role" style={{ textTransform: 'none', color: 'var(--blue)' }}>
                  {activeRole === 'Recruiting' ? 'Recruiter' : activeRole === 'Operational head' ? 'Delivery Head' : activeRole === 'candidate' ? 'Candidate' : 'Tech Panel'}
                </div>
              </div>
            </div>
            
            <button 
              onClick={() => {
                logout();
                navigate('/login');
              }}
              style={{
                marginTop: '4px',
                padding: '6px',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                color: 'var(--t2)',
                cursor: 'pointer',
                fontSize: '0.75rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                fontWeight: 600,
                transition: 'all 0.2s'
              }}
              onMouseEnter={e => { e.currentTarget.style.background = '#fee2e2'; e.currentTarget.style.color = '#ef4444'; e.currentTarget.style.borderColor = '#fca5a5'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg)'; e.currentTarget.style.color = 'var(--t2)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
            >
              <span style={{ fontSize: '0.9rem' }}>🚪</span> Logout
            </button>
          </div>
        )}

        <div className="sidebar-footer">
          {sidebarOpen && <span className="sidebar-version">v1.0.0</span>}
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <Topbar />
        <div className="content-area">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
            <Route path="/screening" element={<ProtectedRoute><Screening /></ProtectedRoute>} />
            <Route path="/job-postings" element={<ProtectedRoute><JobPostings /></ProtectedRoute>} />
            <Route path="/interviews" element={<ProtectedRoute><Interviews /></ProtectedRoute>} />
            <Route path="/client-review" element={<ProtectedRoute><ClientReview /></ProtectedRoute>} />
            <Route path="/onboarding" element={<ProtectedRoute><Onboarding /></ProtectedRoute>} />
            <Route path="/communications" element={<ProtectedRoute><Communications /></ProtectedRoute>} />
            <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
            <Route path="/candidate-portal" element={<ProtectedRoute><CandidateDashboard /></ProtectedRoute>} />
            <Route path="/investigator" element={<ProtectedRoute><Investigator /></ProtectedRoute>} />
          </Routes>
        </div>
      </main>

      {/* Toast Notification */}
      {toast && (
        <div className="toast-notification">
          <span>ℹ️</span>
          <span>{toast}</span>
        </div>
      )}

      {/* Global Candidate Timeline Modal */}
      {globalCandidateId && (
        <GlobalCandidateTimelineModal 
          candidateId={globalCandidateId} 
          onClose={() => setGlobalCandidateId(null)} 
        />
      )}
    </div>
  )
}

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <ChangePasswordModal />
          <AppContent />
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
