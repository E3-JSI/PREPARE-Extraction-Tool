import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import AuthProvider from "components/AuthProvider";
import ProtectedRoute from "components/ProtectedRoute"; 

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
const Model_Settings = lazy(() => import("pages/Model_Settings"));

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
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
              path="/model_settings"
              element={
                <ProtectedRoute>
                  <Model_Settings />
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
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
