import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useToasts } from './store'
import { ApiError } from '@/api/client'

export const errText = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e))

/** Mutation with toast feedback + query invalidation. */
export function useAct<A = void, R = any>(fn: (a: A) => Promise<R>, opts: { ok?: string; invalidate?: QueryKey[]; onDone?: (r: R) => void } = {}) {
  const qc = useQueryClient()
  const push = useToasts((s) => s.push)
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      if (opts.ok) push('ok', opts.ok)
      opts.invalidate?.forEach((k) => qc.invalidateQueries({ queryKey: k }))
      opts.onDone?.(r)
    },
    onError: (e) => push('error', errText(e)),
  })
}
export { useQuery }
