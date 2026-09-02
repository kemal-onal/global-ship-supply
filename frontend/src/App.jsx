import { Navigate, Route, Routes } from 'react-router-dom'
import { useEffect } from 'react'

import { useAuthStore } from './store/auth'
import LoginPage from './pages/Login'
import Layout from './components/Layout'
import DashboardPage from './pages/Dashboard'
import CatalogPage from './pages/Catalog'
import ProductDetailPage from './pages/ProductDetail'
import OrdersPage from './pages/Orders'
import OrderDetailPage from './pages/OrderDetail'
import OrderCreatePage from './pages/OrderCreate'
import VesselsPage from './pages/Vessels'
import FleetMapPage from './pages/FleetMap'
import PortsPage from './pages/Ports'
import CateringPage from './pages/Catering'
import RFQPage from './pages/RFQ'
import CustomsPage from './pages/Customs'
import SyncPage from './pages/Sync'
import SettingsPage from './pages/Settings'

export default function App() {
  const accessToken = useAuthStore(s => s.accessToken)

  // Lock body background to theme
  useEffect(() => {
    document.documentElement.classList.add('antialiased')
  }, [])

  if (!accessToken) {
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/catalog/:id" element={<ProductDetailPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/orders/new" element={<OrderCreatePage />} />
        <Route path="/orders/:id" element={<OrderDetailPage />} />
        <Route path="/vessels" element={<VesselsPage />} />
        <Route path="/fleet-map" element={<FleetMapPage />} />
        <Route path="/ports" element={<PortsPage />} />
        <Route path="/catering" element={<CateringPage />} />
        <Route path="/rfq" element={<RFQPage />} />
        <Route path="/customs" element={<CustomsPage />} />
        <Route path="/sync" element={<SyncPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  )
}
