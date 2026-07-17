import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import AuthProvider from "components/AuthProvider";
import ProtectedRoute from "components/ProtectedRoute";
import ToastProvider from "components/Toast/ToastProvider";
import MonitorProvider from "pages/Monitor/components/MonitorProvider";

const Login = lazy(() => import("pages/Login"));
const Datasets = lazy(() => import("pages/Datasets"));
const DatasetOverview = lazy(() => import("pages/DatasetOverview"));
const DatasetTermExtraction = lazy(() => import("pages/DatasetTermExtraction"));
const DatasetTermClustering = lazy(() => import("pages/DatasetTermClustering"));
const DatasetConceptMapping = lazy(() => import("pages/DatasetConceptMapping"));
const DatasetUpload = lazy(() => import("pages/DatasetUpload"));
const Vocabularies = lazy(() => import("pages/Vocabularies"));
const VocabularyDetail = lazy(() => import("pages/VocabularyDetail"));
const VocabularyUpload = lazy(() => import("pages/VocabularyUpload"));
const Monitor = lazy(() => import("pages/Monitor"));
const UserProfile = lazy(() => import("pages/UserProfile"));

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        {/* ToastProvider hosts toast state outside MonitorProvider so showing/
            dismissing a toast never rerenders the Monitor context consumers.
            MonitorProvider is mounted above the router so training state + the
            training websocket survive page navigation (progress persists when
            leaving Monitor and returning). Inside AuthProvider so it reads the
            auth token. */}
        <ToastProvider>
          <MonitorProvider>
            <Suspense fallback={<div>Loading...</div>}>
              <Routes>
                {/* Public routes */}
                <Route path="/login" element={<Login />} />

                {/* Protected routes */}
                <Route
                  path="/datasets"
                  element={
                    <ProtectedRoute>
                      <Datasets />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/datasets/upload"
                  element={
                    <ProtectedRoute>
                      <DatasetUpload />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/datasets/:datasetId"
                  element={
                    <ProtectedRoute>
                      <DatasetOverview />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/datasets/:datasetId/records"
                  element={
                    <ProtectedRoute>
                      <DatasetTermExtraction />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/datasets/:datasetId/clusters"
                  element={
                    <ProtectedRoute>
                      <DatasetTermClustering />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/datasets/:datasetId/mapping"
                  element={
                    <ProtectedRoute>
                      <DatasetConceptMapping />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/vocabularies"
                  element={
                    <ProtectedRoute>
                      <Vocabularies />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/vocabularies/upload"
                  element={
                    <ProtectedRoute>
                      <VocabularyUpload />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/vocabularies/:vocabularyId"
                  element={
                    <ProtectedRoute>
                      <VocabularyDetail />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/monitor"
                  element={
                    <ProtectedRoute>
                      <Monitor />
                    </ProtectedRoute>
                  }
                />
                <Route
                  path="/profile"
                  element={
                    <ProtectedRoute>
                      <UserProfile />
                    </ProtectedRoute>
                  }
                />

                {/* Default redirect */}
                <Route path="/" element={<Navigate to="/datasets" replace />} />
                <Route path="*" element={<Navigate to="/datasets" replace />} />
              </Routes>
            </Suspense>
          </MonitorProvider>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
