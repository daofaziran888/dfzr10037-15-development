/** 跨报告整改链路接口：关系样本归并、批次派工、治理领取与修正回执。 */
import { request } from './client'

export type AuditSample = {
  id: number
  样本编号: string
  报告编号: string
  边号: string
  关系描述: string
  错误类型: string
  图代: string
  抽样口径: string
  状态: string
  批次编号: string
  核销回执: string
  核销时间: string
}

export type SampleRef = {
  样本编号: string
  报告编号: string
  边号: string
  错误类型: string
  图代: string
  抽样口径: string
}

export type RectifyBatch = {
  id: number
  批次编号: string
  边号: string
  关系描述: string
  错误类型: string[]
  冲突标记: boolean
  涉及报告: string[]
  样本列表: SampleRef[]
  状态: string
  处理人: string
  归并时间: string
  派工时间: string
}

export type RectifyItem = {
  id: number
  项编号: string
  批次编号: string
  边号: string
  关系描述: string
  错误类型: string
  涉及报告: string[]
  样本列表: SampleRef[]
  状态: string
  处理人: string
  领取时间: string
  核销回执: string[]
}

export type ReceiptRecord = {
  id: number
  回执编号: string
  边号: string
  错误类型: string[]
  图代: string
  处理人: string
  说明: string
  核销时间: string
  核销样本: (SampleRef & { 批次编号: string })[]
  涉及整改项: string[]
  重复回执?: boolean
  本次核销样本?: (SampleRef & { 批次编号: string })[]
}

export type RemainingItem = { 项编号: string; 边号: string; 错误类型: string; 状态: string }

async function parse<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

export async function listAuditSamples(edge = ''): Promise<AuditSample[]> {
  const query = edge ? `?边号=${encodeURIComponent(edge)}` : ''
  const data = await parse<{ items: AuditSample[] }>(await request(`/api/quality_audit/samples${query}`))
  return data.items
}

export async function mergeSamples(sampleCodes: string[], handler: string) {
  return await parse<{ ok: boolean; message: string; batch: RectifyBatch | null }>(
    await request('/api/quality_audit/batches/merge', {
      method: 'POST',
      body: JSON.stringify({ 样本编号: sampleCodes, 处理人: handler }),
    }),
  )
}

export async function listRectifyBatches(): Promise<RectifyBatch[]> {
  const data = await parse<{ items: RectifyBatch[] }>(await request('/api/quality_audit/batches'))
  return data.items
}

export async function dispatchBatch(batchCode: string, handler: string) {
  return await parse<{ ok: boolean; message: string; items: RectifyItem[] }>(
    await request(`/api/quality_audit/batches/${encodeURIComponent(batchCode)}/dispatch`, {
      method: 'POST',
      body: JSON.stringify({ 处理人: handler }),
    }),
  )
}

export async function listRectifyItems(): Promise<RectifyItem[]> {
  const data = await parse<{ items: RectifyItem[] }>(await request('/api/govern_dash/rectify-items'))
  return data.items
}

export async function claimRectifyItem(itemCode: string, handler: string) {
  return await parse<{ ok: boolean; message: string; item: RectifyItem | null }>(
    await request(`/api/govern_dash/rectify-items/${encodeURIComponent(itemCode)}/claim`, {
      method: 'POST',
      body: JSON.stringify({ 处理人: handler }),
    }),
  )
}

export async function listReceipts(): Promise<ReceiptRecord[]> {
  const data = await parse<{ items: ReceiptRecord[] }>(await request('/api/govern_dash/rectify-receipts'))
  return data.items
}

export type ReceiptPayload = {
  回执编号: string
  边号: string
  错误类型: string[]
  图代?: string
  处理人: string
  说明?: string
}

export async function deliverReceipt(payload: ReceiptPayload) {
  return await parse<{
    ok: boolean
    message: string
    receipt: ReceiptRecord | null
    剩余待整改: RemainingItem[]
  }>(
    await request('/api/govern_dash/rectify-receipts', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  )
}
