import { Navigate, Route, Routes } from 'react-router-dom'
import { useEffect } from 'react'

import { useAuthStore } from './store/auth'
import LoginPage from './pages/Login'
import Layout from './components/Layout'
import DashboardPage from './pages/Dashboard'
// IMPA-first redesign: the Catalog + ProductDetail pages are now
// deprecation stubs. The imports stay so the /catalog and
// /catalog/:id routes can still render the deprecation banner,
// but the sidebar entry is dropped (see Layout.jsx). The original
// implementations are preserved as *.jsx.removed for reference.
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
import MarketplacePage from './pages/Marketplace'
import SupplierPortalPage from './pages/SupplierPortal'
import CustomsPage from './pages/Customs'
import SyncPage from './pages/Sync'
import SettingsPage from './pages/Settings'
import PermissionsPage from './pages/Permissions'

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
        <Route path="/marketplace" element={<MarketplacePage />} />
        <Route path="/marketplace/:rfqId" element={<MarketplacePage />} />
        <Route path="/supplier" element={<SupplierPortalPage />} />
        <Route path="/supplier/rfq/:rfqId" element={<SupplierPortalPage />} />
        <Route path="/customs" element={<CustomsPage />} />
        <Route path="/sync" element={<SyncPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/permissions" element={<PermissionsPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  )
}
