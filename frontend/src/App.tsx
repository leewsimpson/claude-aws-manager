import { Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/AppLayout'
import { HomeRedirect } from './components/HomeRedirect'
import { CostCentresPage } from './pages/CostCentresPage'
import { KeyRequestsPage } from './pages/KeyRequestsPage'
import { KeysPage } from './pages/KeysPage'
import { LoginPage } from './pages/LoginPage'
import { UsagePage } from './pages/UsagePage'

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <HomeRedirect />
          </ProtectedRoute>
        }
      />
      <Route
        path="/usage"
        element={
          <ProtectedRoute requireRoles={['admin']}>
            <AppLayout>
              <UsagePage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cost-centres"
        element={
          <ProtectedRoute requireRoles={['admin', 'cco']}>
            <AppLayout>
              <CostCentresPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/key-requests"
        element={
          <ProtectedRoute>
            <AppLayout>
              <KeyRequestsPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/keys"
        element={
          <ProtectedRoute>
            <AppLayout>
              <KeysPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
