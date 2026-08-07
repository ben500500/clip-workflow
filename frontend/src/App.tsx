import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { App as AntApp } from 'antd';
import { AuthProvider } from './contexts/AuthContext';
import AuthGuard from './components/AuthGuard';
import AppLayout from './components/AppLayout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import EpisodeDetail from './pages/EpisodeDetail';
import ClipReviewPage from './pages/ClipReview';
import IntervalDetectionPage from './pages/IntervalDetection';
import SliceTasksPage from './pages/SliceTasks';
import OutputPreviewPage from './pages/OutputPreview';
import PublishManagement from './pages/PublishManagement';
import DashboardOverview from './pages/DashboardOverview';
import ContentAnalysis from './pages/ContentAnalysis';
import DramaMonetization from './pages/DramaMonetization';
import FunnelAnalysis from './pages/FunnelAnalysis';
import Ecosystem from './pages/Ecosystem';
import DataImport from './pages/DataImport';
import DashboardSettings from './pages/DashboardSettings';
import Settings from './pages/Settings';
import Profile from './pages/Profile';
import UserManagement from './pages/UserManagement';
import Workers from './pages/Workers';
import Monitor from './pages/Monitor';
import Maintenance from './pages/Maintenance';
import Watermark from './pages/Watermark';
import NotFound from './pages/NotFound';

const App: React.FC = () => {
  return (
    <AntApp>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <AuthGuard>
                <AppLayout />
              </AuthGuard>
            }
          >
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="projects" element={<Projects />} />
            <Route path="projects/:id" element={<ProjectDetail />} />
            <Route path="episodes/:id" element={<EpisodeDetail />} />
            <Route path="episodes/:episodeId/clips" element={<ClipReviewPage />} />
            <Route path="episodes/:episodeId/intervals" element={<IntervalDetectionPage />} />
            <Route path="episodes/:episodeId/slice" element={<SliceTasksPage />} />
            <Route path="episodes/:episodeId/preview" element={<OutputPreviewPage />} />
            <Route path="publish" element={<PublishManagement />} />
            <Route path="analytics/overview" element={<DashboardOverview />} />
            <Route path="analytics/content" element={<ContentAnalysis />} />
            <Route path="analytics/monetization" element={<DramaMonetization />} />
            <Route path="analytics/funnel" element={<FunnelAnalysis />} />
            <Route path="analytics/ecosystem" element={<Ecosystem />} />
            <Route path="analytics/import" element={<DataImport />} />
            <Route path="analytics/settings" element={<DashboardSettings />} />
            <Route path="profile" element={<Profile />} />
            <Route path="user-management" element={<UserManagement />} />
            <Route path="workers" element={<Workers />} />
            <Route path="monitor" element={<Monitor />} />
            <Route path="maintenance" element={<Maintenance />} />
            <Route path="watermark" element={<Watermark />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </AntApp>
  );
};

export default App;