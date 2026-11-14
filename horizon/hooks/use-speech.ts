'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { UserSettings } from '@/lib/types'

interface RecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}

export function useSpeech(settings: Pick<UserSettings, 'voiceName' | 'speechRate' | 'autoSpeak'>) {
  const [speaking, setSpeaking] = useState(false)
  const [listening, setListening] = useState(false)
  const [micError, setMicError] = useState('')
  const [supportsTts, setSupportsTts] = useState(false)
  const [supportsStt, setSupportsStt] = useState(false)
  const recRef = useRef<RecognitionLike | null>(null)
  const fallbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setSupportsTts(typeof window !== 'undefined' && 'speechSynthesis' in window)
    setSupportsStt(typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window))
    return () => {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) speechSynthesis.cancel()
      recRef.current?.stop()
      if (fallbackTimer.current) clearTimeout(fallbackTimer.current)
    }
  }, [])

  const cancel = useCallback(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) speechSynthesis.cancel()
    if (fallbackTimer.current) clearTimeout(fallbackTimer.current)
    setSpeaking(false)
  }, [])

  const speak = useCallback(
    (text: string) => {
      if (!settings.autoSpeak) return
      cancel()
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        const u = new SpeechSynthesisUtterance(text)
        u.rate = settings.speechRate
        const voice = speechSynthesis.getVoices().find((v) => v.name === settings.voiceName)
        if (voice) u.voice = voice
        u.onstart = () => setSpeaking(true)
        u.onend = () => setSpeaking(false)
        u.onerror = () => setSpeaking(false)
        speechSynthesis.speak(u)
      } else {
        setSpeaking(true)
        fallbackTimer.current = setTimeout(() => setSpeaking(false), Math.min(5000, text.length * 40))
      }
    },
    [settings.autoSpeak, settings.speechRate, settings.voiceName, cancel],
  )

  const stopListening = useCallback(() => {
    recRef.current?.stop()
    setListening(false)
  }, [])

  const startListening = useCallback(
    (onText: (text: string, final: boolean) => void) => {
      setMicError('')
      const w = window as unknown as { SpeechRecognition?: new () => RecognitionLike; webkitSpeechRecognition?: new () => RecognitionLike }
      const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
      if (!Ctor) {
        setMicError('Voice input is not supported in this browser. You can type your answer instead.')
        return
      }
      cancel()
      const rec = new Ctor()
      rec.lang = 'en-US'
      rec.continuous = true
      rec.interimResults = true
      rec.onresult = (e) => {
        let text = ''
        let final = false
        for (let i = 0; i < e.results.length; i++) {
          text += e.results[i][0].transcript
          final = e.results[i].isFinal
        }
        onText(text, final)
      }
      rec.onerror = (e) => {
        setListening(false)
        setMicError(
          e.error === 'not-allowed' || e.error === 'service-not-allowed'
            ? 'Microphone access was blocked. Allow it in your browser, or type your answer instead.'
            : e.error === 'no-speech'
              ? 'I did not hear anything. Try again, or type your answer.'
              : 'Voice input stopped unexpectedly. You can keep going by typing.',
        )
      }
      rec.onend = () => setListening(false)
      recRef.current = rec
      try {
        rec.start()
        setListening(true)
      } catch {
        setMicError('Could not start the microphone. Please try again.')
      }
    },
    [cancel],
  )

  return { speak, cancel, speaking, listening, startListening, stopListening, micError, setMicError, supportsTts, supportsStt }
}
