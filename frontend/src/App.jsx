// src/App.jsx
import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import LandingPage from './components/LandingPage';
import BuildTimelinePage from './pages/BuildTimelinePage';
import StatisticalAnalysisPage from './pages/StatisticalAnalysisPage';
import PortfolioSnapshot from './components/PortfolioSnapshot';
import History from './components/History';
import PortfolioAnalysis from './components/PortfolioAnalysis';
import SystemFlowchart from './components/SystemFlowchart';
import SystemDesign from './components/SystemDesign';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/portfolio" element={<Layout />}>
        <Route index element={<PortfolioSnapshot />} />
        <Route path="history" element={<History />} />
        <Route path="analysis" element={<PortfolioAnalysis />} />
        <Route path="statistics" element={<StatisticalAnalysisPage />} />
        <Route path="flowchart" element={<SystemFlowchart />} />
        <Route path="system-design" element={<SystemDesign />} />
        <Route path="timeline" element={<BuildTimelinePage />} />
      </Route>
    </Routes>
  );
}
