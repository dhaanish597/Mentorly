'use client'

import { Page } from '@/components/app-shell'
import { PathCard } from '@/components/dashboard/widgets'
import { PageHeader } from '@/components/ui-kit'
import { PATHS } from '@/lib/data'

export default function PathsPage() {
  return (
    <Page>
      <PageHeader eyebrow="Learning paths" title="Choose what to sharpen today" description="Each path has three levels. Finish two challenges in a level to unlock the next." />
      <div className="grid gap-5 md:grid-cols-3">
        {PATHS.map((p) => (
          <PathCard key={p.id} path={p} />
        ))}
      </div>
    </Page>
  )
}
