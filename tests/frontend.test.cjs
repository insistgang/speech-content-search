const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8')

function extract(name, nextName, context) {
  const start = source.indexOf(`  async function ${name}(`)
  const end = source.indexOf(`  ${nextName}`, start)
  return new Function(...Object.keys(context), source.slice(start, end) + `\nreturn ${name};`)(...Object.values(context))
}

test('keyword search preserves UUID returned by the backend', async () => {
  const id = '12345678-abcd-4321-abcd-123456789012'
  const elements = { 'search-query': { value: '' }, 'search-keyword-set': { value: id }, 'search-mode': { value: 'exact' }, 'results-empty': {} }
  const requests = []
  const handle = extract('handleSearch', 'async function handleKeywordCreate', {
    byId: name => elements[name] || {},
    searchResults: { replaceChildren() {} }, setMessage() {}, renderSearchResults() {},
    jsonOptions: (method, body) => ({ method, body }), errorText: String,
    requestJson: async (url, options) => { requests.push({ url, options }); return { count: 0, results: [] } }
  })
  const button = { disabled: false }
  await handle({ preventDefault() {}, currentTarget: { querySelector: () => button } })
  assert.equal(requests.length, 1)
  assert.equal(requests[0].options.body.keyword_set_id, id)
  assert.equal(button.disabled, false)
})

test('folder import summary counts the imported array', async () => {
  const messages = []
  const handle = extract('handleFolderImport', 'async function retryVideo', {
    byId: name => name === 'folder-path' ? { value: '访谈资料' } : {},
    setMessage: (_element, text) => messages.push(text), currentProvider: () => 'sidecar',
    jsonOptions: (method, body) => ({ method, body }), errorText: String,
    requestJson: async () => ({ imported: [{ video: { id: 'one' } }, { video: { id: 'two' } }], errors: [] }),
    describeFolderError: String, refreshLists: async () => true, beginTaskPolling() {}
  })
  await handle({ preventDefault() {}, currentTarget: { querySelector: () => ({ disabled: false }) } })
  assert.equal(messages.some(text => text.includes('提交 2 个视频')), true)
})
