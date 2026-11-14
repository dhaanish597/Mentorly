import { notFound } from 'next/navigation'
import { PathDetail } from '@/components/dashboard/path-detail'
import { getPath } from '@/lib/data'

export default async function PathPage({ params }: { params: Promise<{ pathId: string }> }) {
  const { pathId } = await params
  const path = getPath(pathId)
  if (!path) notFound()
  return <PathDetail pathId={path.id} />
}
