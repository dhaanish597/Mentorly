import { notFound } from 'next/navigation'
import { Arena } from '@/components/arena/arena'
import { getChallenge } from '@/lib/data'

export default async function ChallengePage({ params }: { params: Promise<{ challengeId: string }> }) {
  const { challengeId } = await params
  if (!getChallenge(challengeId)) notFound()
  return <Arena key={challengeId} challengeId={challengeId} />
}
