import { Topbar }    from '@/components/layout/topbar'
import { Sidebar }   from '@/components/layout/sidebar'
import { MobileNav } from '@/components/layout/mobile-nav'
import { AuthGuard } from '@/components/auth-guard'

// All authenticated dashboard pages share this shell.
// Route groups: (dashboard) — never appears in the URL.

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div className="app-shell min-h-screen bg-bg flex flex-col">
        <Topbar />

        <div className="flex flex-1 overflow-hidden">
          <Sidebar />

          {/* Main content */}
          <main className="flex-1 overflow-y-auto pb-20 md:pb-0">
            <div className="content-area">
              {children}
            </div>
          </main>
        </div>

        <MobileNav />
      </div>
    </AuthGuard>
  )
}
