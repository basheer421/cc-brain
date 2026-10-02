// `curl cc-brain.bachir.me | bash` gets the installer; browsers get the site.
// install.sh is copied into the build (`pnpm build`), so this never depends on GitHub: the unauthenticated
// GitHub API is rate-limited per IP, and Cloudflare's shared egress IPs hit that limit.
const CLI_AGENTS = ['curl', 'wget', 'httpie', 'fetch']

const UNAVAILABLE = 'echo "cc-brain: installer unavailable, see https://github.com/basheer421/cc-brain#install" >&2\nexit 1\n'

export const onRequest: PagesFunction<{ ASSETS: Fetcher }> = async (context) => {
  const ua = (context.request.headers.get('user-agent') || '').toLowerCase()
  if (!CLI_AGENTS.some((agent) => ua.includes(agent))) return context.next()

  const script = await context.env.ASSETS.fetch(new URL('/install.sh', context.request.url))
  const ok = script.ok && (await script.clone().text()).startsWith('#!')
  return new Response(ok ? script.body : UNAVAILABLE, {
    status: ok ? 200 : 503,
    headers: {
      'content-type': 'text/plain; charset=utf-8',
      'cache-control': 'no-cache',
    },
  })
}
