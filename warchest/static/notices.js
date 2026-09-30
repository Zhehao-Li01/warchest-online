import {actionLabel} from './actions.js';

// Text is derived exclusively from the server's confirmed, public action feed.
export function noticeText(action, unitName, decrees) {
 const kind = action.effect === 'fort_attack' ? 'fort_attack' : action.effect === 'control' ? 'control' : action.kind;
 const title = {
  deploy:'对手部署', redeploy:'对手重新部署', move:'对手移动', attack:'对手攻击',
  fort_attack:'对手拆除堡垒', control:'对手控制据点', tactic:'对手发动战术', bolster:'对手增强',
  recruit:'对手招募', initiative:'对手抢先', pass:'对手跳过行动',
  proclaim:'对手颁布法令', finish:'对手结束追加行动',
 }[kind] || `对手${actionLabel(action)}`;
 let detail = action.coin ? unitName(action.coin) : '';
 if (kind === 'recruit') detail = unitName(action.recruit);
 if (kind === 'proclaim') detail = decrees[action.effect]?.[0] || '颁布法令';
 if (kind === 'initiative') detail = '夺取下一轮先手';
 if (kind === 'pass') detail = '暗弃一枚指令币';
 if (kind === 'finish') detail = '';
 return {title, detail};
}

export class OpponentNotices {
 constructor(element, unitName, decrees) {
  this.element=element;this.unitName=unitName;this.decrees=decrees;
  this.queue=[];this.timer=null;this.active=false;
 }
 clear() {
  clearTimeout(this.timer);this.timer=null;this.queue=[];this.active=false;
  this.element.classList.remove('visible');
  this.element.querySelector('strong').textContent='';
  this.element.querySelector('span').textContent='';
 }
 update(before, after, player) {
  if(!before || before.room!==after.room || before.game!==after.game){this.clear();return;}
  for(const item of after.activity || []) {
   if(item.revision>before.revision && item.action.player!==player) {
    this.queue.push(noticeText(item.action,this.unitName,this.decrees()));
   }
  }
  if(before.resigned===null && after.resigned===1-player) {
   this.queue.push({title:'对手认输',detail:'你赢得了这场战役'});
  }
  if(!this.active)this.next();
 }
 next() {
  const message=this.queue.shift();
  if(!message){this.active=false;return;}
  this.active=true;
  this.element.querySelector('strong').textContent=message.title;
  this.element.querySelector('span').textContent=message.detail;
  this.element.classList.add('visible');
  this.timer=setTimeout(()=>{
   this.element.classList.remove('visible');
   this.timer=setTimeout(()=>{
    this.element.querySelector('strong').textContent='';
    this.element.querySelector('span').textContent='';
    this.next();
   },240);
  },2200);
 }
}
