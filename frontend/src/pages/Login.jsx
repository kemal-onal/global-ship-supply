import { useState } from 'react'
import { Anchor, Eye, EyeOff, Loader2, LockKeyhole, Mail, Ship, Wifi, ShieldCheck, Globe } from 'lucide-react'
import toast from 'react-hot-toast'

import { apiPost, apiGet } from '../api/client'
import { useAuthStore } from '../store/auth'

export default function LoginPage() {
  const [email, setEmail] = useState('admin@avsglobal.com')
  const [password, setPassword] = useState('admin123')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const setUser = useAuthStore(s => s.setUser)
  const setTokens = useAuthStore(s => s.setTokens)

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      const r = await apiPost('/auth/login', { username: email, password })
      setTokens({ accessToken: r.access_token, refreshToken: r.refresh_token })
      // Login response has no user info — fetch it from /auth/me
      const userData = await apiGet('/auth/me')
      setUser(userData)
      toast.success(`Welcome back, ${userData.full_name || userData.email}`)
    } catch (err) {
      toast.error(typeof err.message === 'string' ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-slate-50 dark:bg-slate-950">
      {/* Hero */}
      <div className="hidden lg:flex relative bg-gradient-to-br from-blue-900 via-blue-800 to-cyan-900 text-white p-12 flex-col justify-between overflow-hidden">
        <div className="absolute inset-0 opacity-20">
          <div className="absolute top-10 left-10 w-96 h-96 rounded-full bg-cyan-400 blur-3xl" />
          <div className="absolute bottom-20 right-10 w-96 h-96 rounded-full bg-blue-400 blur-3xl" />
        </div>

        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-white/10 backdrop-blur flex items-center justify-center">
              <Anchor className="w-6 h-6" />
            </div>
            <div>
              <div className="text-2xl font-bold">AVS Global</div>
              <div className="text-sm text-blue-200">Ship Supply Operations</div>
            </div>
          </div>
        </div>

        <div className="relative space-y-8">
          <div>
            <h1 className="text-4xl xl:text-5xl font-bold leading-tight">
              Maritime logistics,<br/>
              <span className="text-cyan-300">always in reach.</span>
            </h1>
            <p className="text-blue-100 mt-4 text-lg max-w-md">
              Manage vessel supply, dynamic supplier bidding, customs compliance and
              catering provisioning — even when you're at sea.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-3 max-w-md">
            <Feature
              icon={Wifi}
              title="Offline-first"
              desc="Work without VSAT. Replays to the server the moment the link returns."
            />
            <Feature
              icon={ShieldCheck}
              title="Secure by default"
              desc="JWT/RBAC, IDS/IPS-style request inspection, and full audit trail."
            />
            <Feature
              icon={Globe}
              title="IMPA/ISSA catalog"
              desc="Sub-50ms full-text search across millions of product rows."
            />
          </div>
        </div>

        <div className="relative text-xs text-blue-200/70">
          © 2026 AVS Global — Trusted by 1,200+ vessels worldwide
        </div>
      </div>

      {/* Form */}
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <div className="lg:hidden flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-600 to-cyan-500 flex items-center justify-center">
              <Anchor className="w-5 h-5 text-white" />
            </div>
            <div className="font-bold text-xl">AVS Global</div>
          </div>

          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Sign in</h2>
          <p className="text-slate-500 dark:text-slate-400 mt-1 text-sm">
            Use your AVS Global credentials to access the operations dashboard.
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Email or username
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="text"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  className="w-full pl-10 pr-3 py-2.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  placeholder="captain@avsglobal.com"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1.5">
                Password
              </label>
              <div className="relative">
                <LockKeyhole className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  className="w-full pl-10 pr-10 py-2.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPw(s => !s)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium text-sm disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Ship className="w-4 h-4" />}
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="mt-8 p-4 rounded-lg bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
            <div className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2">
              Demo accounts
            </div>
            <div className="space-y-1 text-[11px] text-slate-600 dark:text-slate-400 font-mono">
              <div>admin@avsglobal.com / admin123 <span className="text-slate-400">— super_admin</span></div>
              <div>fleetadmin@avsglobal.com / demo123 <span className="text-slate-400">— fleet_admin</span></div>
              <div>captain@avsglobal.com / demo123 <span className="text-slate-400">— vessel_captain</span></div>
              <div>purchasing@avsglobal.com / demo123 <span className="text-slate-400">— purchasing_officer</span></div>
              <div>steward@avsglobal.com / demo123 <span className="text-slate-400">— chief_steward</span></div>
              <div className="pt-1.5 mt-1.5 border-t border-slate-200 dark:border-slate-700 text-[10px] uppercase tracking-wide text-slate-500">
                Suppliers (use the Supplier Portal in the sidebar)
              </div>
              <div>supplier@apcmarine.sg / demo123 <span className="text-slate-400">— APC Marine (Singapore)</span></div>
              <div>supplier1@avsglobal.com / demo123 <span className="text-slate-400">— Rotterdam Demo Supplies</span></div>
              <div>supplier2@avsglobal.com / demo123 <span className="text-slate-400">— Singapore Demo Supplies</span></div>
              <div>supplier3@avsglobal.com / demo123 <span className="text-slate-400">— Dubai Demo Supplies</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Feature({ icon: Icon, title, desc }) {
  return (
    <div className="flex items-start gap-3 p-3 rounded-lg bg-white/5 backdrop-blur-sm border border-white/10">
      <div className="w-9 h-9 rounded-lg bg-cyan-500/20 flex items-center justify-center flex-shrink-0">
        <Icon className="w-4 h-4 text-cyan-300" />
      </div>
      <div>
        <div className="font-semibold text-sm">{title}</div>
        <div className="text-xs text-blue-200/80">{desc}</div>
      </div>
    </div>
  )
}
