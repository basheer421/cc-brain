const INSTALL_SCRIPT_URL =
  'https://api.github.com/repos/basheer421/cc-brain/contents/install.sh'

const CLI_AGENTS = ['curl', 'wget', 'httpie', 'fetch']

export const onRequest: PagesFunction = async (context) => {
  const ua = (context.request.headers.get('user-agent') || '').toLowerCase()
  const isCli = CLI_AGENTS.some((agent) => ua.includes(agent))

  if (isCli) {
    const script = await fetch(INSTALL_SCRIPT_URL, {
      headers: {
        'Accept': 'application/vnd.github.v3.raw',
        'User-Agent': 'cc-brain-installer',
      },
    })
    return new Response(script.body, {
      headers: {
        'content-type': 'text/plain; charset=utf-8',
        'cache-control': 'no-cache',
      },
    })
  }

  return context.next()
}
