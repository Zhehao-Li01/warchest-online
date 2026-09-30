// BP selections are tentative until confirmed against the server revision.
let selection = [], revisionKey = '';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const phases = ['先手 Ban 1', '后手 Ban 1', '先手 Pick 1', '后手 Pick 2', '先手 Pick 2', '后手 Pick 2', '先手 Pick 1'];

function publicSetup(draft, player, meta) {
 const setup = draft.setup;
 if (!setup || (!setup.decrees.length && !setup.forts.length)) return '';
 const decrees = setup.decrees.map(id => `<li><strong>${esc(meta.decrees[id][0])}</strong>：${esc(meta.decrees[id][1])}</li>`).join('');
 const controls = new Map(meta.preview.controls.map(c => [c.pos.join(','), c.owner]));
 const forts = new Set(setup.forts.map(p => p.join(',')));
 const sign = player === 0 ? -1 : 1;
 const map = setup.forts.length ? `<svg class="draft-map" viewBox="-130 -145 260 290" role="img" aria-label="本局堡垒布局，己方起点在下方">${meta.hexes.map(([q,r]) => {
  const key = [q,r].join(','), owner = controls.get(key), fort = forts.has(key);
  const x = sign*q*33, y = sign*(2*r+q)*19;
  const points = Array.from({length:6},(_,i) => `${x+21*Math.cos(i*Math.PI/3)},${y+21*Math.sin(i*Math.PI/3)}`).join(' ');
  return `<g><polygon points="${points}" fill="${owner===player?'#345b50':owner===1-player?'#793e3e':'#252b32'}" stroke="#899096" stroke-width="${fort?3:0.6}" ${fort?'stroke-dasharray="3 2"':''}/><text x="${x}" y="${y+5}" text-anchor="middle" fill="#fff" font-size="13">${fort?'堡':controls.has(key)?'○':''}</text></g>`;
 }).join('')}</svg><p>虚线「堡」为堡垒；绿色为己方起点，红色为对手起点。</p>` : '';
 return `<section class="draft-public-setup"><h3>本局公开设置 · 选兵前确定</h3>${decrees?`<ul class="draft-decrees">${decrees}</ul>`:''}${map}</section>`;
}

export function renderDraft(el, snapshot, player, meta, coinHTML, ready, onConfirm) {
 const draft = snapshot?.draft;
 el.hidden = !draft || !!snapshot.view;
 if (el.hidden) return;
 const key = `${snapshot.room}:${snapshot.game}:${snapshot.revision}`;
 if (key !== revisionKey) { selection = []; revisionKey = key; }
 const ownTurn = snapshot.status === 'drafting' && draft.current === player;
 const active = ownTurn && ready;
 const verb = draft.kind === 'ban' ? '禁用' : '选取';
 const sideName = side => `${side === draft.first ? '先手' : '后手'} · ${snapshot.seats[side]?.name || '等待入席'}${side === player ? '（你）' : ''}`;
 const names = units => units.map(u => meta.units[u].name).join('、') || '尚无';
 const status = snapshot.status === 'waiting' ? '等待好友入席后开始 BP' : snapshot.status === 'finished' ? '本局已结束，可在房间中发起再战' : ownTurn ? `轮到你${verb} ${draft.count} 种兵种` : `等待${sideName(draft.current)}${verb} ${draft.count} 种兵种`;
 const draw = () => {
  const scrollTop = el.scrollTop;
  el.innerHTML = `<div class="draft-heading"><span class="eyebrow">BAN / PICK</span><h2>十选八 · 组建军队</h2><p>从启用扩展中随机抽取 10 种兵种。双方各禁用 1 种，再按顺序选满各 4 种。</p></div>
   ${publicSetup(draft, player, meta)}
   <ol class="draft-phases">${phases.map((label, i) => `<li class="${i === draft.step ? 'current' : i < draft.step ? 'done' : ''}" ${i === draft.step ? 'aria-current="step"' : ''}>${label}</li>`).join('')}</ol>
   <div class="draft-rosters">${[draft.first, 1-draft.first].map(side => `<section><strong>${esc(sideName(side))}</strong><p data-draft-roster="${side}">已选 ${draft.picks[side].length}/4：${esc(names(draft.picks[side]))}</p><small>禁用：${esc(names(draft.bans[side]))}</small></section>`).join('')}</div>
   <p class="draft-status" role="status">${esc(status)}</p>
   <div class="draft-grid">${draft.pool.map(u => {
    const available = draft.available.includes(u), chosen = selection.includes(u);
    const banned = draft.bans.flat().includes(u), pickedBy = draft.picks.findIndex(units => units.includes(u));
    const label = banned ? '已禁用' : pickedBy >= 0 ? `${pickedBy === draft.first ? '先手' : '后手'}已选` : chosen ? '待确认' : '可选';
    return `<button class="draft-card ${chosen ? 'selected' : ''} ${banned ? 'banned' : ''}" data-draft-unit="${u}" aria-pressed="${chosen}" ${!active || !available || (!chosen && selection.length >= draft.count) ? 'disabled' : ''}>${coinHTML(u)}<strong>${esc(meta.units[u].name)}</strong><span class="draft-coin-count">共 ${meta.units[u].coins} 枚币</span><small>${esc(meta.expansions[meta.units[u].expansion])} · ${label}</small><span>${esc(meta.units[u].help)}</span></button>`;
   }).join('')}</div>
   <div class="draft-confirm"><span>${ownTurn ? `已选择 ${selection.length}/${draft.count} · ${esc(names(selection))}` : esc(status)}</span><button id="confirm-draft" class="button primary" ${!active || selection.length !== draft.count ? 'disabled' : ''}>确认${verb}${ownTurn ? ` ${draft.count} 种` : ''}</button></div>`;
  el.querySelectorAll('[data-draft-unit]').forEach(button => button.onclick = () => {
   const unit = button.dataset.draftUnit;
   selection = selection.includes(unit) ? selection.filter(u => u !== unit) : [...selection, unit];
   draw();
  });
  el.querySelector('#confirm-draft').onclick = () => onConfirm([...selection]);
  el.scrollTop = scrollTop;
 };
 draw();
}
