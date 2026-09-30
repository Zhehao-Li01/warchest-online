// Disposable SVG overlays; animations never mutate game state or block input.
const NS = 'http://www.w3.org/2000/svg';
const PROFILES = {
 commander:['thrust','#edce83'],dragoon:['charge','#d1d9dd'],marksman:['arrow','#e8bd87'],ranger:['charge','#a3c6e3'],
 alchemist:['holy','#bb9ed7'],apprentice:['holy','#b6d7c9'],emissary:['thrust','#ebd7a9'],overlord:['heavy','#c79fb8'],
 pirate:['slash','#7ed3d5'],longboat:['heavy','#90b4cc'],corsair:['double','#d4b793'],admiral:['thrust','#9baedb'],
 bannerman:['slash','#eac29e'],bishop:['holy','#e2c7f5'],earl:['heavy','#e9c86b'],herald:['thrust','#b1dca8'],
 sapper:['heavy','#bdceaf'],siege_tower:['heavy','#c4c4bb'],trebuchet:['bolt','#e2b477'],war_wagon:['charge','#a7bcd3'],
 assassin:['thrust','#cf8eb9'],saboteur:['holy','#bbc67c'],infiltrator:['slash','#b6bdcf'],skirmisher:['charge','#a7cbbd'],
 rearguard:['heavy','#a5bedb'],raider:['double','#e7a278'],pitch_thrower:['holy','#f5a361'],war_drummer:['heavy','#c9ae86'],
 heavy_cavalry:['charge','#d8bd97'],vanguard:['thrust','#b9c9df'],warlord:['heavy','#e2b58e'],
 swordsman:['slash','#fff0be'], pikeman:['thrust','#dfc780'], crossbowman:['bolt','#f2ce97'],
 light_cavalry:['charge','#ead09a'], archer:['arrow','#a8dec0'], cavalry:['charge','#f1bd85'],
 lancer:['lance','#e9dbab'], scout:['slash','#9dcfdf'], berserker:['double','#f4a583'],
 ensign:['slash','#cee49b'], footman:['thrust','#b6d9cf'], knight:['heavy','#b2d6eb'],
 marshall:['heavy','#e9b488'], mercenary:['slash','#e3a1a4'], royal_guard:['heavy','#e5b7c5'],
 warrior_priest:['holy','#d6c1f6'],
};
export const combatProfile = unit => PROFILES[unit] || ['slash','#f1d395'];
const el=(tag,attrs={},text)=>{const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));

export class CombatEffects {
 constructor(board, geometry){this.board=board;this.geometry=geometry;this.generation=0;this.chain=Promise.resolve();}
 clear(){this.generation++;this.board.querySelectorAll('.combat-layer').forEach(n=>n.remove());this.chain=Promise.resolve();}
 play(batches){const generation=this.generation;for(const batch of batches.slice(-6)){this.chain=this.chain.then(()=>generation===this.generation?this.run(batch.items,generation):undefined).catch(()=>{});}}
 async run(items,generation){
  if(!items.length)return;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const layer=el('g',{'class':'combat-layer','aria-hidden':'true'});this.board.append(layer);
  const animations=[];
  const animate=(node,frames,options)=>{if(!reduced)animations.push(node.animate(frames,{fill:'both',...options}));};
  for(const item of items){
   const [style,color]=combatProfile(item.unit);
   if(item.kind==='attack'){
    const [sx,sy]=this.geometry(item.source),[tx,ty]=this.geometry(item.target);
    const length=Math.hypot(tx-sx,ty-sy)||1,ux=(tx-sx)/length,uy=(ty-sy)/length;
    const wrapper=el('g',{'class':`attack-fx ${style}`,'data-unit':item.unit,'color':color});layer.append(wrapper);
    if(reduced){wrapper.append(el('line',{x1:sx,y1:sy,x2:tx,y2:ty,stroke:color,'stroke-width':2,'opacity':.7}));continue;}
    const origin=this.board.querySelector(`[data-pos="${item.source.join(',')}"] .unit-token`);
    if(origin)animate(origin,[{transform:'translate(0,0)'},{transform:`translate(${ux*8}px,${uy*8}px)`},{transform:'translate(0,0)'}],{duration:380});
    if(['arrow','bolt'].includes(style)){
     const trail=el('line',{x1:sx,y1:sy,x2:tx,y2:ty,stroke:color,'stroke-width':style==='bolt'?3:1.5,'stroke-dasharray':length,'stroke-dashoffset':length,opacity:.6});wrapper.append(trail);
     animate(trail,[{strokeDashoffset:length,opacity:.1},{strokeDashoffset:0,opacity:.8},{strokeDashoffset:0,opacity:0}],{duration:470});
     const arrow=el('g');arrow.append(el('path',{d:'M-19 0H7 M1-5 8 0 1 5 M-15-4-11 0-15 4',fill:'none',stroke:color,'stroke-width':2.5,'stroke-linecap':'round'}));wrapper.append(arrow);
     const angle=Math.atan2(ty-sy,tx-sx)*180/Math.PI;
     animate(arrow,[{transform:`translate(${sx}px,${sy}px) rotate(${angle}deg)`,opacity:0},{offset:.12,opacity:1},{transform:`translate(${tx}px,${ty}px) rotate(${angle}deg)`,opacity:1},{offset:1,opacity:0}],{duration:430});
    }else{
     if(['charge','lance'].includes(style)){
      const points=[item.origin,...(item.path||[]),item.target].map(p=>this.geometry(p).join(',')).join(' ');
      const trail=el('polyline',{points,fill:'none',stroke:color,'stroke-width':style==='lance'?5:9,'stroke-linecap':'round','stroke-linejoin':'round','stroke-dasharray':'12 9'});wrapper.append(trail);
      animate(trail,[{opacity:0,strokeDashoffset:35},{opacity:.85,strokeDashoffset:0},{opacity:0,strokeDashoffset:-30}],{duration:540});
     }
     const burst=el('g',{transform:`translate(${tx} ${ty})`});wrapper.append(burst);
     if(style==='holy'){
      burst.append(el('path',{d:'M-25 0H25M0-25V25M-16-16 16 16M16-16-16 16',stroke:color,'stroke-width':3}));
      burst.append(el('circle',{r:25,fill:'none',stroke:color,'stroke-width':2}));
     }else if(style==='thrust'||style==='lance'){
      burst.append(el('path',{d:`M${-ux*30} ${-uy*30}L${ux*20} ${uy*20}`,stroke:color,'stroke-width':4,'stroke-linecap':'round'}));
      burst.append(el('path',{d:'m-8-8 16 16m0-16-16 16',stroke:color,'stroke-width':2}));
     }else{
      burst.append(el('path',{d:'M-24 19Q-5-9 25-21',fill:'none',stroke:color,'stroke-width':style==='heavy'?7:4,'stroke-linecap':'round'}));
      if(style==='double')burst.append(el('path',{d:'M-23-20Q6-4 24 20',fill:'none',stroke:color,'stroke-width':4,'stroke-linecap':'round'}));
     }
     animate(burst,[{opacity:0},{offset:.3,opacity:1},{offset:.65,opacity:1},{opacity:0}],{duration:600});
    }
   }else if(item.kind==='hit'||item.kind==='shield'){
    const [x,y]=this.geometry(item.pos),shield=item.kind==='shield';
    const group=el('g',{'class':shield?'shield-fx':'hit-fx','data-unit':item.unit,transform:`translate(${x} ${y})`});layer.append(group);
    group.append(el('circle',{r:32,fill:shield?'#91ccea33':'#ff93783d',stroke:shield?'#aeddec':color,'stroke-width':3}));
    const label=el('text',{x:0,y:-17,'text-anchor':'middle','class':'damage-number'},item.label||(shield?'抵挡':item.remaining===0?'−1 · 击溃':'−1'));group.append(label);
    if(!reduced){
     const target=this.board.querySelector(`[data-pos="${item.pos.join(',')}"] .unit-token`);
     if(target)animate(target,[{transform:'translateX(0)',filter:'brightness(1)'},{transform:'translateX(-5px)',filter:'brightness(1.8)'},{transform:'translateX(5px)'},{transform:'translateX(-3px)'},{transform:'translateX(0)',filter:'brightness(1)'}],{duration:410,delay:170});
     animate(group,[{opacity:0},{offset:.25,opacity:1},{offset:.65,opacity:.8},{opacity:0}],{duration:750});
     animate(label,[{transform:'translateY(0)'},{transform:'translateY(-23px)'}],{duration:750});
    }
   }
  }
  await wait(reduced?220:790);
  animations.forEach(a=>a.cancel());layer.remove();
 }
}
