import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import worker, { WORKFLOW_URL } from './worker.js'

const realFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = realFetch
})

function stubFetch(status, body = '') {
  const calls = []
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init })
    return new Response(status === 204 ? null : body, { status })
  }
  return calls
}

test('dispatches the Hourly workflow on main with the token', async () => {
  const calls = stubFetch(204)
  await worker.scheduled({}, { GITHUB_TOKEN: 'github_pat_x' })

  assert.equal(calls.length, 1)
  const [{ url, init }] = calls
  assert.equal(url, WORKFLOW_URL)
  assert.equal(init.method, 'POST')
  assert.equal(init.headers.Authorization, 'Bearer github_pat_x')
  assert.deepEqual(JSON.parse(init.body), { ref: 'main' })
})

test('fails loudly when GitHub refuses, e.g. an expired token', async () => {
  stubFetch(401, '{"message":"Bad credentials"}')
  await assert.rejects(
    worker.scheduled({}, { GITHUB_TOKEN: 'expired' }),
    /GitHub refused to start the workflow: 401 .*Bad credentials/,
  )
})

test('fails without a token and never calls GitHub', async () => {
  const calls = stubFetch(204)
  await assert.rejects(worker.scheduled({}, {}), /GITHUB_TOKEN secret is not set/)
  assert.equal(calls.length, 0)
})

test('is not a website', async () => {
  assert.equal((await worker.fetch()).status, 404)
})
