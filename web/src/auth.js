// 访问令牌：前端统一携带身份凭证。后端每人一个令牌（.env AGENT_TOKENS=uid:token）。
// 未配令牌时后端鉴权关闭，这里不带头也能正常用（本地自用零摩擦）。
const KEY = 'agent_token'

export function getToken() {
  return localStorage.getItem(KEY) || ''
}

export function setToken(t) {
  localStorage.setItem(KEY, (t || '').trim())
}

export function clearToken() {
  localStorage.removeItem(KEY)
}

// 显示名：纯本地，仅用于界面识别当前用户（让令牌登录更像账号体系）。
const NAME_KEY = 'agent_user_name'
export function getUserName() {
  return localStorage.getItem(NAME_KEY) || ''
}
export function setUserName(n) {
  localStorage.setItem(NAME_KEY, (n || '').trim().slice(0, 24))
}
export function clearUserName() {
  localStorage.removeItem(NAME_KEY)
}

// Authorization 头（无令牌返回空对象）
export function authHeader() {
  const t = getToken()
  return t ? { Authorization: 'Bearer ' + t } : {}
}

function fireUnauthorized() {
  window.dispatchEvent(new CustomEvent('agent-unauthorized'))
}

// 统一 fetch：自动附加令牌头；遇 401 广播 agent-unauthorized（App 弹令牌门）。
export async function authFetch(url, init = {}) {
  const headers = new Headers(init.headers || {})
  const t = getToken()
  if (t && !headers.has('Authorization')) headers.set('Authorization', 'Bearer ' + t)
  const res = await fetch(url, { ...init, headers })
  if (res.status === 401) fireUnauthorized()
  return res
}

// 给下载链接追加 ?t= 令牌：浏览器直接导航（<a href>）无法带 Authorization 头。
export function withToken(url) {
  const t = getToken()
  if (!t) return url
  const sep = url.includes('?') ? '&' : '?'
  return url + sep + 't=' + encodeURIComponent(t)
}

// 邀请链接自动登录：若地址栏带 ?t=<token>，静默存入 localStorage 并抹掉该参数，
// 用户全程无感（体感≈点魔法链接登录）。需在挂载前调用，确保首个数据请求即带令牌。
// 无效令牌会在后续 authFetch 收到 401 时自动弹回令牌门兜底。
export function consumeInviteToken() {
  try {
    const url = new URL(window.location.href)
    const t = url.searchParams.get('t')
    if (!t) return
    const prev = getToken()
    setToken(t)
    // 切换到另一个用户：清掉上一用户残留的当前会话 id，避免落到空白/越权 id
    if (prev && prev !== t.trim()) localStorage.removeItem('convId')
    url.searchParams.delete('t')
    window.history.replaceState({}, '', url.pathname + url.search + url.hash)
  } catch (e) {  /* 非浏览器环境或 URL 解析失败：静默忽略，不影响正常启动 */ }
}

// 退出登录：清除令牌、显示名与残留会话 id 后整页重载，回到登录门。
export function logout() {
  clearToken()
  clearUserName()
  localStorage.removeItem('convId')
  location.reload()
}
