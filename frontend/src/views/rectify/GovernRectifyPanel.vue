<template>
  <section class="rectify-panel" data-testid="govern-rectify-panel">
    <h3>治理待办 · 整改项</h3>
    <p class="panel-desc">
      整改项由质量审计的整改批次证据生成，可依证据分批领取；交付修正回执后按实际处理的关系错误类型核销。
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th>项编号</th>
          <th>批次编号</th>
          <th>边号</th>
          <th>错误类型</th>
          <th>涉及报告</th>
          <th>样本数</th>
          <th>状态</th>
          <th>处理人</th>
          <th>核销回执</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.项编号" :data-testid="`rectify-${item.项编号}`">
          <td>{{ item.项编号 }}</td>
          <td>{{ item.批次编号 }}</td>
          <td>{{ item.边号 }}</td>
          <td>{{ item.错误类型 }}</td>
          <td>{{ item.涉及报告.join('、') }}</td>
          <td>{{ item.样本列表.length }}</td>
          <td>{{ item.状态 }}</td>
          <td>{{ item.处理人 || '—' }}</td>
          <td>{{ item.核销回执.length ? item.核销回执.join('、') : '—' }}</td>
          <td>
            <button
              v-if="item.状态 === '待领取'"
              class="link"
              type="button"
              :data-testid="`claim-${item.项编号}`"
              @click="submitClaim(item.项编号)"
            >
              领取
            </button>
            <span v-else>—</span>
          </td>
        </tr>
        <tr v-if="!items.length">
          <td colspan="10" class="empty-state">暂无整改项，等待质量审计派工同步</td>
        </tr>
      </tbody>
    </table>

    <h3>交付修正回执</h3>
    <form class="receipt-form" @submit.prevent="submitReceipt">
      <label>
        <span>回执编号（幂等键）</span>
        <input v-model="receiptForm.回执编号" data-testid="receipt-code" required placeholder="如 RCPT-0001" />
      </label>
      <label>
        <span>边号</span>
        <input v-model="receiptForm.边号" data-testid="receipt-edge" required placeholder="如 R7" />
      </label>
      <label>
        <span>图代（可选，先定断链所在版本）</span>
        <input v-model="receiptForm.图代" data-testid="receipt-generation" placeholder="如 G3" />
      </label>
      <label>
        <span>处理人</span>
        <input v-model="receiptForm.处理人" data-testid="receipt-handler" placeholder="处理人" />
      </label>
      <fieldset class="receipt-types">
        <legend>实际处理的关系错误类型</legend>
        <label v-for="t in errorTypeOptions" :key="t">
          <input v-model="receiptForm.错误类型" type="checkbox" :value="t" :data-testid="`receipt-type-${t}`" />
          {{ t }}
        </label>
      </fieldset>
      <label class="receipt-note">
        <span>说明</span>
        <input v-model="receiptForm.说明" placeholder="修复说明（可选）" />
      </label>
      <button class="btn primary" data-testid="deliver-receipt" type="submit" :disabled="delivering">
        {{ delivering ? '交付中…' : '交付回执' }}
      </button>
    </form>

    <div v-if="receiptResult" class="receipt-result" data-testid="receipt-result">
      <p class="panel-message">{{ receiptResult.message }}</p>
      <template v-if="receiptResult.receipt">
        <p v-if="receiptResult.receipt.重复回执" class="dup-hint">
          同一回执只核销一次，以下为首次核销的报告样本：
        </p>
        <table class="data-table">
          <thead>
            <tr>
              <th>样本编号</th>
              <th>报告编号</th>
              <th>错误类型</th>
              <th>图代</th>
              <th>抽样口径</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in receiptResult.receipt.核销样本" :key="s.样本编号">
              <td>{{ s.样本编号 }}</td>
              <td>{{ s.报告编号 }}</td>
              <td>{{ s.错误类型 }}</td>
              <td>{{ s.图代 }}</td>
              <td>{{ s.抽样口径 }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="receiptResult.剩余待整改.length" class="remaining">
          剩余待整改：
          <span v-for="r in receiptResult.剩余待整改" :key="r.项编号" class="remaining-item">
            {{ r.项编号 }}（{{ r.边号 }} {{ r.错误类型 }} · {{ r.状态 }}）
          </span>
        </p>
      </template>
    </div>

    <h3>回执台账</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>回执编号</th>
          <th>边号</th>
          <th>实际处理错误类型</th>
          <th>图代</th>
          <th>核销样本</th>
          <th>涉及整改项</th>
          <th>核销时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in receipts" :key="r.回执编号">
          <td>{{ r.回执编号 }}</td>
          <td>{{ r.边号 }}</td>
          <td>{{ r.错误类型.join('、') }}</td>
          <td>{{ r.图代 || '—' }}</td>
          <td>{{ r.核销样本.map((s) => `${s.样本编号}(${s.报告编号})`).join('、') }}</td>
          <td>{{ r.涉及整改项.join('、') }}</td>
          <td>{{ r.核销时间 }}</td>
        </tr>
        <tr v-if="!receipts.length">
          <td colspan="7" class="empty-state">暂无回执</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  claimRectifyItem,
  deliverReceipt,
  listReceipts,
  listRectifyItems,
  type ReceiptRecord,
  type RectifyItem,
  type RemainingItem,
} from '@/api/rectify'

const items = ref<RectifyItem[]>([])
const receipts = ref<ReceiptRecord[]>([])
const delivering = ref(false)
const errorTypeOptions = ['断链', '误连']
const receiptForm = reactive({
  回执编号: '',
  边号: '',
  图代: '',
  处理人: '处理人',
  错误类型: [] as string[],
  说明: '',
})
const receiptResult = ref<{
  message: string
  receipt: ReceiptRecord | null
  剩余待整改: RemainingItem[]
} | null>(null)

async function submitClaim(itemCode: string) {
  const result = await claimRectifyItem(itemCode, receiptForm.处理人)
  receiptResult.value = { message: result.message, receipt: null, 剩余待整改: [] }
  await reload()
}

async function submitReceipt() {
  delivering.value = true
  try {
    const result = await deliverReceipt({
      回执编号: receiptForm.回执编号,
      边号: receiptForm.边号,
      错误类型: receiptForm.错误类型,
      图代: receiptForm.图代 || undefined,
      处理人: receiptForm.处理人,
      说明: receiptForm.说明 || undefined,
    })
    receiptResult.value = {
      message: result.message,
      receipt: result.receipt,
      剩余待整改: result.剩余待整改,
    }
    await reload()
  } finally {
    delivering.value = false
  }
}

async function reload() {
  items.value = await listRectifyItems()
  receipts.value = await listReceipts()
}

onMounted(reload)
</script>

<style scoped>
.rectify-panel {
  margin-top: 20px;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}
.panel-desc {
  color: var(--muted);
  font-size: 12px;
  margin: 4px 0 10px;
}
.receipt-form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  padding: 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 12px;
}
.receipt-form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}
.receipt-form input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.receipt-types {
  display: flex;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--muted);
}
.receipt-types label {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 4px;
  color: #1f2937;
}
.receipt-result {
  margin-bottom: 12px;
}
.panel-message {
  font-size: 13px;
  color: var(--brand);
}
.dup-hint {
  font-size: 12px;
  color: var(--muted);
}
.remaining {
  font-size: 12px;
  color: var(--muted);
}
.remaining-item {
  margin-right: 10px;
}
</style>
