// Cloudflare Worker: starts the Hourly GitHub Actions workflow on Cloudflare's cron schedule,
// because GitHub's own schedule skips most runs.
//
// Needs the GITHUB_TOKEN secret: a fine-grained token for s-chen/curated-bytes with only
// "Actions: read and write". It can start workflow runs and nothing else.

export const WORKFLOW_URL =
  'https://api.github.com/repos/s-chen/curated-bytes/actions/workflows/hourly.yml/dispatches'

export async function dispatch(token) {
  const response = await fetch(WORKFLOW_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'curatedbytes-trigger',
    },
    body: JSON.stringify({ ref: 'main' }),
  })
  if (response.status !== 204) {
    // Shows as a failed invocation in the Worker's logs, e.g. 401 once the token expires.
    throw new Error(`GitHub refused to start the workflow: ${response.status} ${await response.text()}`)
  }
}

export default {
  async scheduled(controller, env) {
    if (!env.GITHUB_TOKEN) throw new Error('GITHUB_TOKEN secret is not set')
    await dispatch(env.GITHUB_TOKEN)
  },
  // Not meant to be visited.
  async fetch() {
    return new Response('Not found', { status: 404 })
  },
}
