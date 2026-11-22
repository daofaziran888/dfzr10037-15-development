<template>
  <section class="rectify-panel" data-testid="audit-rectify-panel">
    <h3>跨报告关系样本归并</h3>
    <p class="panel-desc">
      多选来自多份质量报告的关系样本，批量归并成整改批次证据；同一关系的冲突判断可共存，
      边号相同但未选中的样本（如未受影响图代）不会划入整改。
    </p>

    <div class="merge-bar">
      <label class="merge-field">
        <span>处理人</span>
        <input v-model="handler" data-testid="merge-handler" placeholder="归并/派工处理人" />
      </label>
      <button
        class="btn primary"
        data-testid="merge-samples"
        type="button"
        :disabled="!selected.size || merging"
        @click="submitMerge"
      >
        {{ merging ? '归并中…' : `归并所选为整改批次（已选 ${selected.size}）` }}
      </button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>选择</th>
          <th>样本编号</th>
          <th>报告编号</th>
          <th>边号</th>
          <th>关系描述</th>
          <th>错误类型</th>
          <th>图代</th>
          <th>抽样口径</th>
          <th>状态</th>
          <th>批次编号</th>
          <th>核销回执</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="sample in samples" :key="sample.样本编号" :data-testid="`sample-${sample.样本编号}`">
          <td>
            <input
              type="checkbox"
              :data-testid="`pick-${sample.样本编号}`"
              :checked="selected.has(sample.样本编号)"
              :disabled="sample.状态 !== '待归并'"
              @change="toggle(sample.样本编号)"
            />
          </td>
          <td>{{ sample.样本编号 }}</td>
          <td>{{ sample.报告编号 }}</td>
          <td>{{ sample.边号 }}</td>
          <td>{{ sample.关系描述 }}</td>
          <td>{{ sample.错误类型 }}</td>
          <td>{{ sample.图代 }}</td>
          <td>{{ sample.抽样口径 }}</td>
          <td>{{ sample.状态 }}</td>
          <td>{{ sample.批次编号 || '—' }}</td>
          <td>{{ sample.核销回执 || '—' }}</td>
        </tr>
        <tr v-if="!samples.length">
          <td colspan="11" class="empty-state">暂无关系样本</td>
        </tr>
      </tbody>
    </table>

    <h3>整改批次证据</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th>批次编号</th>
          <th>边号</th>
          <th>错误类型</th>
          <th>冲突</th>
          <th>涉及报告</th>
          <th>样本溯源</th>
          <th>状态</th>
          <th>处理人</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="batch in batches" :key="batch.批次编号">
          <tr :data-testid="`batch-${batch.批次编号}`">
            <td>{{ batch.批次编号 }}</td>
            <td>{{ batch.边号 }}</td>
            <td>{{ batch.错误类型.join('、') }}</td>
            <td>{{ batch.冲突标记 ? '冲突' : '一致' }}</td>
            <td>{{ batch.涉及报告.join('、') }}</td>
            <td>
              <button class="link" type="button" @click="toggleTrace(batch.批次编号)">
                {{ expanded.has(batch.批次编号) ? '收起' : `查看 ${batch.样本列表.length} 个样本` }}
              </button>
            </td>
            <td>{{ batch.状态 }}</td>
            <td>{{ batch.处理人 || '—' }}</td>
            <td>
              <button
                v-if="batch.状态 === '待派工'"
                class="link"
                type="button"
                :data-testid="`dispatch-${batch.批次编号}`"
                @click="submitDispatch(batch.批次编号)"
              >
                整组派工
              </button>
              <span v-else>—</span>
            </td>
          </tr>
          <tr v-if="expanded.has(batch.批次编号)" class="trace-row">
            <td colspan="9">
              <table class="data-table trace-table">
                <thead>
                  <tr>
                    <th>样本编号</th>
                    <th>原报告</th>
                    <th>抽样口径</th>
                    <th>图代</th>
                    <th>错误类型</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="ref in batch.样本列表" :key="ref.样本编号">
                    <td>{{ ref.样本编号 }}</td>
                    <td>{{ ref.报告编号 }}</td>
                    <td>{{ ref.抽样口径 }}</td>
                    <td>{{ ref.图代 }}</td>
                    <td>{{ ref.错误类型 }}</td>
                  </tr>
                </tbody>
              </table>
            </td>
          </tr>
        </template>
        <tr v-if="!batches.length">
          <td colspan="9" class="empty-state">暂无整改批次，可先在上方多选样本归并</td>
        </tr>
      </tbody>
    </table>

    <p v-if="message" class="panel-message" data-testid="audit-panel-message">{{ message }}</p>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  dispatchBatch,
  listAuditSamples,
  listRectifyBatches,
  mergeSamples,
  type AuditSample,
  type RectifyBatch,
} from '@/api/rectify'

const samples = ref<AuditSample[]>([])
const batches = ref<RectifyBatch[]>([])
const selected = ref<Set<string>>(new Set())
const expanded = ref<Set<string>>(new Set())
const handler = ref('审计员')
const merging = ref(false)
const message = ref('')

function toggle(code: string) {
  if (selected.value.has(code)) {
    selected.value.delete(code)
  } else {
    selected.value.add(code)
  }
  selected.value = new Set(selected.value)
}

function toggleTrace(code: string) {
  if (expanded.value.has(code)) {
    expanded.value.delete(code)
  } else {
    expanded.value.add(code)
  }
  expanded.value = new Set(expanded.value)
}

async function submitMerge() {
  merging.value = true
  message.value = ''
  try {
    const result = await mergeSamples([...selected.value], handler.value)
    message.value = result.message
    if (result.ok) {
      selected.value = new Set()
      await reload()
    }
  } finally {
    merging.value = false
  }
}

async function submitDispatch(batchCode: string) {
  message.value = ''
  const result = await dispatchBatch(batchCode, handler.value)
  message.value = result.message
  await reload()
}

async function reload() {
  samples.value = await listAuditSamples()
  batches.value = await listRectifyBatches()
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
.merge-bar {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  margin-bottom: 10px;
}
.merge-field span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.merge-field input {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
}
.trace-row td {
  background: #f8fafc;
}
.trace-table th,
.trace-table td {
  font-size: 12px;
}
.panel-message {
  margin-top: 10px;
  font-size: 13px;
  color: var(--brand);
}
</style>
