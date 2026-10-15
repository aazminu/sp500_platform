import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import logo from './oracle zero.png';

export default function LandingPage() {
  const [showContent, setShowContent] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const handleKeyPress = () => {
      setShowContent(true);
      // Navigate to portfolio page after a brief delay
      setTimeout(() => {
        navigate('/portfolio');
      }, 1000);
    };

    // Listen for any key press
    document.addEventListener('keydown', handleKeyPress);
    
    // Also listen for mouse clicks as an alternative
    document.addEventListener('click', handleKeyPress);

    return () => {
      document.removeEventListener('keydown', handleKeyPress);
      document.removeEventListener('click', handleKeyPress);
    };
  }, [navigate]);

  return (
    <div className="landing-page">
      <div className="landing-content">
        <div className="logo-container">
          <img src={logo} alt="Oracle Zero" className="logo" />
        </div>
        
        {!showContent ? (
          <div className="press-key-prompt">
            <p>Press any key to continue</p>
            <div className="pulse-dot"></div>
          </div>
        ) : (
          <div className="loading-transition">
            <div className="spinner"></div>
          </div>
        )}
      </div>
    </div>
  );
}
