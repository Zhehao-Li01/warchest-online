// Local editing only. The server repeats every roster and expansion validation.
export function configureGame(meta, config, onSave, coinHTML) {
 const dialog=document.querySelector('#general-dialog'), content=document.querySelector('#general-content');
 const draft=structuredClone(config), selected=new Set(draft.expansions||['base']);
 draft.armies=draft.armies||meta.armies.map(a=>[...a]);let side=0;
 const family=u=>meta.units[u].family||u;
 const draw=()=>{
  draft.armies=draft.armies.map(a=>a.filter(u=>selected.has(meta.units[u].expansion)));
  content.innerHTML=`<h2 class="dialog-heading">扩展与双方阵容</h2><p class="dialog-intro">选择启用的扩展和组军方式。相同兵种、原兵种与替代版本不能同时入选。</p>
   <div class="expansion-options">${Object.entries(meta.expansions).map(([id,name])=>`<label><input type="checkbox" data-expansion="${id}" ${selected.has(id)?'checked':''}>${name}</label>`).join('')}</div>
   <p class="setup-note">基础版可取消勾选；BP 至少需要 10 种兵种，其他组军方式至少需要 8 种。贵族包含法令；攻城包含堡垒；夜幕包含中毒与诱饵；震慑战术包含替代兵种。</p>
   <label class="field"><span>组军方式</span><select id="setup-mode"><option value="bp" ${draft.mode==='bp'?'selected':''}>BP 禁选 · 默认模式</option><option value="custom" ${draft.mode==='custom'?'selected':''}>房主自由配置双方阵容</option><option value="random" ${draft.mode==='random'?'selected':''}>从启用扩展中随机分配</option></select></label>
   ${draft.mode==='bp'?'<p class="muted">随机抽取 10 种兵种并随机决定先手。先手 Ban 1 → 后手 Ban 1 → 先手 Pick 1 → 后手 Pick 2 → 先手 Pick 2 → 后手 Pick 2 → 先手 Pick 1。BP 先手也是对局先手。</p>':draft.mode==='random'?'<p class="muted">开局随机分配双方各四种，不会同时抽到原版与替代版。</p>':`<div class="roster-tabs">${[0,1].map(i=>`<button data-side="${i}" class="button ${i===side?'primary':''}">${i===0?'A 方 · 房主':'B 方 · 好友 / AI'} ${draft.armies[i].length}/4</button>`).join('')}</div><button class="text-button" id="clear-roster">清空当前方阵容</button><div class="roster-summary">${[0,1].map(i=>`<div><strong>${i===0?'A':'B'}</strong> ${draft.armies[i].map(u=>`<button data-remove="${i}:${u}">${meta.units[u].name} ×</button>`).join('')||'尚未选择'}</div>`).join('')}</div>
   <div class="setup-unit-grid">${Object.entries(meta.units).filter(([,u])=>selected.has(u.expansion)).map(([u,spec])=>{const own=draft.armies[side].includes(u),used=draft.armies.flat().some(v=>family(v)===family(u));return `<button class="setup-unit ${own?'selected':''}" data-pick="${u}" ${!own&&(used||draft.armies[side].length>=4)?'disabled':''}>${coinHTML(u)}<strong>${spec.name}</strong><small>${meta.expansions[spec.expansion]} · ${spec.coins} 枚</small><span>${spec.help}</span></button>`;}).join('')}</div>
   <label class="field"><span>首轮先手</span><select id="setup-initiative"><option value="0" ${draft.initiative===0?'selected':''}>A 方</option><option value="1" ${draft.initiative===1?'selected':''}>B 方</option></select></label>`}
   <div class="setup-save"><span id="setup-error" role="status"></span><button class="button primary" id="save-setup">保存配置</button></div>`;
  content.querySelectorAll('[data-expansion]').forEach(b=>b.onchange=()=>{b.checked?selected.add(b.dataset.expansion):selected.delete(b.dataset.expansion);draw();});
  content.querySelector('#setup-mode').onchange=e=>{draft.mode=e.target.value;draw();};
  content.querySelectorAll('[data-side]').forEach(b=>b.onclick=()=>{side=Number(b.dataset.side);draw();});
  const clear=content.querySelector('#clear-roster');if(clear)clear.onclick=()=>{draft.armies[side]=[];draw();};
  content.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{const[i,u]=b.dataset.remove.split(':');draft.armies[Number(i)]=draft.armies[Number(i)].filter(v=>v!==u);draw();});
  content.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>{const u=b.dataset.pick,a=draft.armies[side];draft.armies[side]=a.includes(u)?a.filter(v=>v!==u):[...a,u];draw();});
  const initiative=content.querySelector('#setup-initiative');if(initiative)initiative.onchange=e=>draft.initiative=Number(e.target.value);
  content.querySelector('#save-setup').onclick=()=>{const required=draft.mode==='bp'?10:8;const count=new Set(Object.keys(meta.units).filter(u=>selected.has(meta.units[u].expansion)).map(family)).size;if(count<required){content.querySelector('#setup-error').textContent=`当前仅有 ${count} 种不同兵种，${draft.mode==='bp'?'BP':'双方阵容'}至少需要 ${required} 种，请增加扩展或更换组军方式`;return;}if(draft.mode==='custom'&&draft.armies.some(a=>a.length!==4)){content.querySelector('#setup-error').textContent='请为 A、B 双方各选择四个兵种';return;}draft.expansions=[...selected];onSave(draft);dialog.close();};
 };
 draw();if(!dialog.open)dialog.showModal();
}
