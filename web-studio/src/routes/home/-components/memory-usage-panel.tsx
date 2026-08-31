import { Brain } from 'lucide-react'

import { Skeleton } from '#/components/ui/skeleton'
import { cn } from '#/lib/utils'

import { MEMORY_USAGE_DAYS } from '../-constants/dashboard'
import type {
  HomeT,
  MemoryUnusedItem,
  MemoryUsage,
  MemoryUsageItem,
} from '../-types/dashboard'
import { asNumber, formatNumber, isDisabledPayload } from '../-lib/format'
import {
  memoryUriLabel,
  normalizeMemoryUnused,
  normalizeMemoryUsage,
} from '../-lib/normalize'
import { EmptyState, Panel, SectionHeading } from './panel'

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[oklch(0.68_0.12_232/0.12)] bg-background/55 px-3 py-2 dark:border-white/10 dark:bg-white/[0.05]">
      <div className="text-xl font-semibold tabular-nums leading-tight">
        {value}
      </div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground">
        {label}
      </div>
    </div>
  )
}

function CategoryBadge({ category }: { category: string }) {
  return (
    <span className="shrink-0 rounded-full border border-[oklch(0.68_0.12_232/0.2)] px-2 py-0.5 text-[11px] text-muted-foreground">
      {category}
    </span>
  )
}

function UsageRow({
  item,
  peak,
  t,
}: {
  item: Required<MemoryUsageItem>
  peak: number
  t: HomeT
}) {
  // Bars are scaled against the top row rather than the total, so the shape of
  // the ranking stays readable when one memory dominates the window.
  const width =
    peak > 0 ? Math.max(4, Math.round((item.total / peak) * 100)) : 0
  return (
    <li className="rounded-lg px-2 py-1.5 transition-colors hover:bg-background/60 dark:hover:bg-white/[0.05]">
      <div className="flex items-center gap-2">
        <span className="min-w-0 grow truncate text-xs" title={item.uri}>
          {memoryUriLabel(item.uri)}
        </span>
        <CategoryBadge category={item.category} />
        <span className="w-10 shrink-0 text-right text-xs font-medium tabular-nums">
          {formatNumber(item.total)}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <div className="h-1.5 grow overflow-hidden rounded-full bg-[oklch(0.68_0.12_232/0.12)]">
          <div
            className="h-full rounded-full bg-[oklch(0.58_0.13_238)]"
            style={{ width: `${width}%` }}
          />
        </div>
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {t('memoryUsage.breakdown', {
            found: item.found,
            injected: item.injected,
            read: item.read,
          })}
        </span>
      </div>
    </li>
  )
}

function UnusedRow({ item }: { item: MemoryUnusedItem }) {
  const uri = item.uri ?? ''
  return (
    <li className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-background/60 dark:hover:bg-white/[0.05]">
      <span className="min-w-0 grow truncate text-muted-foreground" title={uri}>
        {memoryUriLabel(uri)}
      </span>
      <CategoryBadge category={item.category ?? 'memories'} />
    </li>
  )
}

function Column({
  children,
  className,
  title,
}: {
  children: React.ReactNode
  className?: string
  title: string
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h3>
      {children}
    </div>
  )
}

export function MemoryUsagePanel({
  data,
  disabled: disabledProp,
  disabledMessage,
  isError,
  isLoading,
  t,
}: {
  data: MemoryUsage | undefined
  disabled?: boolean
  disabledMessage?: string
  isError: boolean
  isLoading: boolean
  t: HomeT
}) {
  const disabled = Boolean(disabledProp) || isDisabledPayload(data)
  const top = normalizeMemoryUsage(data?.top)
  const unused = normalizeMemoryUnused(data?.unused)
  const totals = data?.totals
  const peak = top.length > 0 ? top[0].total : 0
  const days = asNumber(data?.days) || MEMORY_USAGE_DAYS

  return (
    <Panel>
      <SectionHeading
        action={
          <span className="flex items-center gap-1.5 rounded-full border border-[oklch(0.68_0.12_232/0.2)] bg-background/70 px-3 py-1 text-xs tabular-nums text-muted-foreground shadow-xs dark:bg-white/[0.06]">
            <Brain className="size-3.5" />
            {t('memoryUsage.window', { count: days })}
          </span>
        }
        description={t('memoryUsage.description')}
        title={t('memoryUsage.title')}
      />

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <EmptyState>{t('requestFailed')}</EmptyState>
      ) : disabled ? (
        <EmptyState>{disabledMessage ?? t('usageDisabled')}</EmptyState>
      ) : (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <StatTile
              label={t('memoryUsage.stats.injections')}
              value={formatNumber(totals?.injections)}
            />
            <StatTile
              label={t('memoryUsage.stats.found')}
              value={formatNumber(totals?.found)}
            />
            <StatTile
              label={t('memoryUsage.stats.reads')}
              value={formatNumber(totals?.reads)}
            />
            <StatTile
              label={t('memoryUsage.stats.unused')}
              value={`${formatNumber(totals?.unused)} / ${formatNumber(totals?.inventory)}`}
            />
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <Column title={t('memoryUsage.topTitle')}>
              {top.length === 0 ? (
                <EmptyState>{t('memoryUsage.topEmpty')}</EmptyState>
              ) : (
                <ul className="flex flex-col gap-1">
                  {top.map((item) => (
                    <UsageRow item={item} key={item.uri} peak={peak} t={t} />
                  ))}
                </ul>
              )}
            </Column>

            <Column title={t('memoryUsage.unusedTitle')}>
              {unused.length === 0 ? (
                <EmptyState>{t('memoryUsage.unusedEmpty')}</EmptyState>
              ) : (
                <ul className="flex flex-col gap-1">
                  {unused.map((item) => (
                    <UnusedRow item={item} key={item.uri} />
                  ))}
                </ul>
              )}
            </Column>
          </div>
        </div>
      )}
    </Panel>
  )
}
