export const GROUPS = [
 {id:'deploy', label:'部署', symbol:'♜', hint:'将单位放入战场', kinds:['deploy','redeploy']},
 {id:'maneuver', label:'调遣', symbol:'↗', hint:'移动、攻击或控制据点', kinds:['move','attack','control']},
 {id:'tactic', label:'战术', symbol:'✦', hint:'使用兵种专属能力', kinds:['tactic']},
 {id:'recruit', label:'招募', symbol:'+', hint:'从供应获得一枚币', kinds:['recruit']},
 {id:'bolster', label:'增强', symbol:'⇧', hint:'增强已部署的单位', kinds:['bolster','supply_bolster','recruit_bolster']},
 {id:'initiative', label:'抢先', symbol:'♛', hint:'夺取下一轮先手', kinds:['initiative']},
 {id:'pass', label:'跳过', symbol:'—', hint:'弃置这枚指令币', kinds:['pass']},
 {id:'defend_supply', label:'移除供应', symbol:'◇', hint:'保留战场上的卫队', kinds:['defend_supply']},
 {id:'defend_unit', label:'承受攻击', symbol:'↓', hint:'移除战场上的一层', kinds:['defend_unit']},
 {id:'proclaim',label:'法令',symbol:'令',hint:'颁布本局法令',kinds:['proclaim']},
 {id:'cure',label:'解毒',symbol:'✚',hint:'清除对应兵种的毒药',kinds:['cure']},
 {id:'return_decoy',label:'归还诱饵',symbol:'↩',hint:'将诱饵归还所属卡牌',kinds:['return_decoy']},
 {id:'defend_decoy',label:'诱饵抵挡',symbol:'◇',hint:'把诱饵交给对手弃牌',kinds:['defend_decoy']},
 {id:'defend_wagon',label:'战车代伤',symbol:'▣',hint:'由相邻战车承受损失',kinds:['defend_wagon']},
 {id:'build',label:'修建堡垒',symbol:'▥',hint:'保护当前据点',kinds:['build']},
 {id:'deceive',label:'诱骗',symbol:'◈',hint:'把诱饵交给对手弃牌',kinds:['deceive']},
 {id:'displace',label:'驱离敌军',symbol:'↗',hint:'选择敌军移动目的地',kinds:['displace']},
 {id:'drum',label:'指定下次抽币',symbol:'♬',hint:'从供应放一枚币到袋顶',kinds:['drum']},
 {id:'cull',label:'移除敌方供应',symbol:'−',hint:'移除中毒敌军供应币',kinds:['cull']},
 {id:'reinforce',label:'补充供应',symbol:'+',hint:'将已移除币放回供应',kinds:['reinforce']},
 {id:'spy',label:'查看手牌',symbol:'◉',hint:'查看对手当前手牌',kinds:['spy']},
 {id:'spy_discard',label:'弃置对手手牌',symbol:'↓',hint:'选择一枚，对手补抽',kinds:['spy_discard']},
 {id:'resolve',label:'选择技能顺序',symbol:'⇄',hint:'先结算哪项效果',kinds:['resolve']},
 {id:'finish', label:'结束追加', symbol:'✓', hint:'不再执行追加行动', kinds:['finish']},
];
export const key = p => p.join(',');
export const actionLabel = a => ({move:'移动',attack:'攻击',control:'控制'})[a.kind]
 || GROUPS.find(g=>g.kinds.includes(a.kind))?.label || '行动';
export function groupActions(actions) {return GROUPS.map(g=>({...g, actions:actions.filter(a=>g.kinds.includes(a.kind))})).filter(g=>g.actions.length);}
export function candidates(actions, view, groupId) {
 const sources = new Set(actions.map(a=>a.source ? key(a.source) : ''));
 return actions.map(action=>{
  const steps=[];
  const control = action.kind==='control' || action.effect==='control';
  const source = action.source || view?.board.find(s=>s.owner===view.player&&s.unit===action.coin)?.pos;
  // In maneuver mode, clicking one's occupied control point must control it,
  // rather than getting consumed as a generic Footman source-selection step.
  if(groupId!=='maneuver' && action.source && sources.size>1)steps.push({pos:action.source,role:'source'});
  for(const pos of action.path)steps.push({pos,role:'move'});
  if(action.target)steps.push({pos:action.target,role:['deploy','redeploy'].includes(action.kind)?'deploy':['command','supply_bolster','wagon_push'].includes(action.effect)||action.kind==='defend_wagon'?'source':'attack'});
  if(control && source && (!steps.length || key(steps.at(-1).pos)!==key(source)))steps.push({pos:source,role:'control'});
  if(action.after)steps.push({pos:action.after,role:'after'});
  if(groupId==='maneuver' && !control && action.source && sources.size>1)steps.push({pos:action.source,role:'source'});
  return {action,steps};
 });
}
export function advance(list, pos) {return list.filter(c=>c.steps.length && key(c.steps[0].pos)===key(pos)).map(c=>({...c,steps:c.steps.slice(1)}));}
