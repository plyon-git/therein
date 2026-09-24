(config) => {
  // Read only approved completed-history link text and numeric game IDs.
  // Do not inspect inputs, account balances, player rows, cookies, or storage.
  const allowed = ['ethercrash.io', 'www.ethercrash.io'];
  if (!config.testMode && !allowed.includes(location.hostname)) {
    return {ok: false, error: 'This page is not an approved EtherCrash origin.', rows: []};
  }
  const selector = config.selector || 'a[href*="/game/"]';
  let nodes;
  try { nodes = [...document.querySelectorAll(selector)]; }
  catch (_) { return {ok: false, error: 'Invalid CSS history selector.', rows: []}; }
  if (nodes.length > 5000) return {ok: false, error: 'Selector is too broad: over 5,000 elements.', rows: []};
  const rows = new Map();
  let ignored = 0;
  for (const node of nodes) {
    if (node.tagName !== 'A') { ignored++; continue; }
    const rect = node.getBoundingClientRect();
    if (!rect.width || !rect.height || getComputedStyle(node).visibility === 'hidden') continue;
    let url;
    try { url = new URL(node.getAttribute('href'), document.baseURI); } catch (_) { ignored++; continue; }
    if (!allowed.includes(url.hostname)) { ignored++; continue; }
    const idMatch = url.pathname.match(/^\/game\/(\d{1,15})\/?$/);
    const text = (node.textContent || '').trim();
    const value = text.match(/^(\d{1,10}(?:\.\d{1,2})?)\s*[x×]?$/i);
    if (!idMatch || !value) { ignored++; continue; }
    const id = Number(idMatch[1]);
    if (!Number.isSafeInteger(id) || id <= 0) { ignored++; continue; }
    const parts = value[1].split('.');
    const cents = Number(parts[0])*100 + Number((parts[1] || '').padEnd(2, '0'));
    if (rows.has(id) && rows.get(id).cents !== cents) {
      return {ok: false, error: `Conflicting visible values for round ${id}. Narrow the selector to completed round history.`, rows: []};
    }
    rows.set(id, {round_id: id, cents, text});
  }
  const result = [...rows.values()].sort((a,b) => a.round_id-b.round_id);
  return {ok: result.length >= 2, rows: result,
          error: result.length < 2 ? 'Need at least two visible completed-history links with numeric /game/ IDs. Open the round-history view or adjust the selector.' : '',
          ignored, candidate_count: result.length, selector,
          origin: location.origin, path: location.pathname};
}
