import { Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/AppLayout'
import { HomePage } from './pages/HomePage'
import { CostCentresPage } from './pages/CostCentresPage'
import { KeyRequestsPage } from './pages/KeyRequestsPage'
import { KeysPage } from './pages/KeysPage'
import { LoginPage } from './pages/LoginPage'

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout>
              <HomePage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/cost-centres"
        element={
          <ProtectedRoute>
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
