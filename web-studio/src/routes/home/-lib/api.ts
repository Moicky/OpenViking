import {
  getConsoleContextCommits,
  getConsoleDashboardSummary,
  getConsoleTokens,
  getOvResult,
  ovClient,
} from '#/lib/ov-client'

import {
  COMMIT_SERIES_DAYS,
  MEMORY_USAGE_DAYS,
  MEMORY_USAGE_LIMIT,
  TOKEN_SERIES_DAYS,
} from '../-constants/dashboard'
import type {
  ConsoleSeriesQuery,
  ConsoleContextCommitsResult,
  ConsoleDashboardSummaryResult,
  ConsoleMemoryUsageResult,
  ConsoleTokenSeriesResult,
} from '@ov-server/api/v1/console'
import { getLastDaysRange, getViewerTimezone } from './format'

export function fetchConsoleDashboardSummary(): Promise<ConsoleDashboardSummaryResult> {
  return getOvResult<ConsoleDashboardSummaryResult>(
    getConsoleDashboardSummary({ query: { timezone: getViewerTimezone() } }),
  )
}

export function fetchConsoleTokenSeries(): Promise<ConsoleTokenSeriesResult> {
  const tz = getViewerTimezone()
  const range = getLastDaysRange(TOKEN_SERIES_DAYS, tz)
  const query: ConsoleSeriesQuery = {
    bucket: 'day',
    end_date: range.endDate,
    start_date: range.startDate,
    timezone: tz,
  }
  return getOvResult<ConsoleTokenSeriesResult>(getConsoleTokens({ query }))
}

export function fetchConsoleContextCommits(): Promise<ConsoleContextCommitsResult> {
  const tz = getViewerTimezone()
  const range = getLastDaysRange(COMMIT_SERIES_DAYS, tz)
  const query: ConsoleSeriesQuery = {
    bucket: '4h',
    end_date: range.endDate,
    start_date: range.startDate,
    timezone: tz,
  }
  return getOvResult<ConsoleContextCommitsResult>(
    getConsoleContextCommits({ query }),
  )
}

// ponytail: hand-rolled because the endpoint post-dates the last
// `pnpm gen-server-client` run, which needs a live server. Fold it into
// sdk.gen.ts at the next regeneration.
export function fetchConsoleMemoryUsage(): Promise<ConsoleMemoryUsageResult> {
  return getOvResult<ConsoleMemoryUsageResult>(
    ovClient.client.get({
      query: { days: MEMORY_USAGE_DAYS, limit: MEMORY_USAGE_LIMIT },
      responseType: 'json',
      url: '/api/v1/console/memory-usage',
    }),
  )
}
