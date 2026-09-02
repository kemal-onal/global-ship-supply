import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Moon, Sun, Monitor, LogOut, User as UserIcon, Languages } from 'lucide-react'
import toast from 'react-hot-toast'

import { useAuthStore } from '../store/auth'
import { useThemeStore } from '../store/theme'

export default function SettingsPage() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  const { theme, setTheme } = useThemeStore()
  const [language, setLanguage] = useState('en')

  const handleLogout = () => {
    logout()
    toast.success('Signed out')
    navigate('/login')
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-3xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-slate-500 text-sm">Profile, theme, and language preferences</p>
      </header>

      <div className="space-y-4">
        {/* Profile */}
        <Section title="Profile" icon={<UserIcon className="w-4 h-4" />}>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <Field label="Name" value={user?.name || user?.username || '—'} />
            <Field label="Email" value={user?.email || '—'} />
            <Field label="Role" value={user?.role || '—'} />
            <Field label="Vessel ID" value={useAuthStore.getState().vesselId || '—'} />
          </div>
        </Section>

        {/* Theme */}
        <Section title="Appearance" icon={theme === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}>
          <div className="grid grid-cols-3 gap-2">
            {[
              { value: 'light', label: 'Light', icon: <Sun className="w-4 h-4" /> },
              { value: 'dark', label: 'Dark', icon: <Moon className="w-4 h-4" /> },
              { value: 'system', label: 'System', icon: <Monitor className="w-4 h-4" /> },
            ].map(opt => (
              <button
                key={opt.value}
                onClick={() => setTheme(opt.value)}
                className={`p-3 border rounded-lg text-sm flex flex-col items-center gap-1.5 ${
                  theme === opt.value
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700'
                    : 'border-slate-200 dark:border-slate-700 hover:border-slate-300'
                }`}
              >
                {opt.icon}{opt.label}
              </button>
            ))}
          </div>
        </Section>

        {/* Language */}
        <Section title="Language" icon={<Languages className="w-4 h-4" />}>
          <select
            value={language}
            onChange={e => setLanguage(e.target.value)}
            className="w-full px-3 py-2.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
          >
            <option value="en">English</option>
            <option value="tr">Türkçe</option>
            <option value="fil">Filipino</option>
            <option value="hi">हिन्दी (Hindi)</option>
          </select>
        </Section>

        {/* Sign out */}
        <Section title="Session">
          <button
            onClick={handleLogout}
            className="px-4 py-2 bg-rose-50 dark:bg-rose-900/20 text-rose-600 text-sm font-medium rounded-lg inline-flex items-center gap-2 hover:bg-rose-100"
          >
            <LogOut className="w-4 h-4" /> Sign out
          </button>
        </Section>
      </div>
    </div>
  )
}

function Section({ title, icon, children }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
      <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">{icon}{title}</h2>
      {children}
    </div>
  )
}

function Field({ label, value }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  )
}
