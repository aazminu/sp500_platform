import { Outlet, Link, useLocation } from 'react-router-dom';
import { useState, useEffect } from 'react';
import logo from './oracle zero.png';

export default function Layout() {
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  
  // Close mobile menu when location changes
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);
  
  return (
    <div className="app-shell">
      <header className="header">
        <div className="header-inner">
          <nav className="nav">
          <div className="nav-logo">
            <img src={logo} alt="Oracle Zero" className="nav-logo-img" />
          </div>
          
          {/* Mobile menu button */}
          <button 
            className="mobile-menu-btn"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle mobile menu"
          >
            <span className={`hamburger ${mobileMenuOpen ? 'open' : ''}`}></span>
          </button>
          
          <div className={`nav-links ${mobileMenuOpen ? 'mobile-open' : ''}`}>
            <Link 
              to="/portfolio" 
              className={`nav-link ${location.pathname === '/portfolio' ? 'active' : ''}`}
            >
              Overview
            </Link>
            <Link 
              to="/portfolio/history" 
              className={`nav-link ${location.pathname === '/portfolio/history' ? 'active' : ''}`}
            >
              History
            </Link>
            <Link 
              to="/portfolio/statistics" 
              className={`nav-link ${location.pathname === '/portfolio/statistics' ? 'active' : ''}`}
            >
              Statistics
            </Link>
            <Link 
              to="/portfolio/analysis" 
              className={`nav-link ${location.pathname === '/portfolio/analysis' ? 'active' : ''}`}
            >
              Weight Analysis
            </Link>
            <Link 
              to="/portfolio/flowchart" 
              className={`nav-link ${location.pathname === '/portfolio/flowchart' ? 'active' : ''}`}
            >
              How it Works
            </Link>
            <Link 
              to="/portfolio/system-design" 
              className={`nav-link ${location.pathname === '/portfolio/system-design' ? 'active' : ''}`}
            >
              System Design
            </Link>
            <Link 
              to="/portfolio/timeline" 
              className={`nav-link ${location.pathname === '/portfolio/timeline' ? 'active' : ''}`}
            >
              How I Built It
            </Link>
            <span className="nav-sep" aria-hidden="true" />
            <a 
              href="https://github.com/aazminu/sp500_platform" 
              target="_blank" 
              rel="noopener noreferrer"
              className="nav-link nav-external"
            >
              <svg 
                width="14" 
                height="14" 
                viewBox="0 0 24 24" 
                fill="currentColor"
                style={{ flexShrink: 0 }}
              >
                <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
              </svg>
              GitHub
            </a>
          </div>
          </nav>
        </div>
      </header>
      <main>
        <div className="container">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
