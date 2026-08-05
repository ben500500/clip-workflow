import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { App as AntApp } from 'antd';
import AppLayout from './components/AppLayout';
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
import DataImport from './pages/DataImport';
import Settings from './pages/Settings';
import NotFound from './pages/NotFound';

const App: React.FC = () => {
  return (
    <AntApp>
      <Routes>
        <Route path="/" element={<AppLayout />}>
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
          <Route path="analytics/import" element={<DataImport />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AntApp>
  );
};

export default App;