const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const out='captures';
fs.mkdirSync(out,{recursive:true});
const chapters=[];
const started=Date.now();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const time=()=>+(Date.now()-started)/1000;
async function main(){
  const chrome=process.env.CHROME_PATH||'/usr/bin/google-chrome';
  const browser=await chromium.launch({headless:true,executablePath:chrome,args:['--no-sandbox','--disable-dev-shm-usage']});
  const context=await browser.newContext({viewport:{width:1440,height:900},deviceScaleFactor:1,recordVideo:{dir:out,size:{width:1440,height:900}}});
  const page=await context.newPage();
  page.on('console',msg=>{if(msg.type()==='error')console.log('BROWSER:',msg.text().slice(0,220));});
  const shot=async(name,desc,hold=3600)=>{
    chapters.push({t:time(),name,desc});
    await page.screenshot({path:path.join(out,String(chapters.length).padStart(2,'0')+'_'+name+'.png'),animations:'disabled'});
    console.log('SCENE',chapters.length,desc);
    await sleep(hold);
  };
  const move=async loc=>{
    await loc.scrollIntoViewIfNeeded({timeout:10000});
    const b=await loc.boundingBox();
    if(b)await page.mouse.move(b.x+b.width/2,b.y+Math.min(b.height/2,35),{steps:18});
    await sleep(750);
  };
  const click=async(loc)=>{await move(loc);await loc.click({timeout:10000});await sleep(700);};
  try{
    const url='https://dodam-heo.github.io/policy-domino-next/';
    console.log('visit',url);
    const response=await page.goto(url,{waitUntil:'domcontentloaded',timeout:60000});
    console.log('HTTP',response?.status());
    await page.waitForSelector('#items .item',{timeout:25000});
    await page.evaluate(()=>{
      const d=document.createElement('div');d.id='demo-pointer';
      Object.assign(d.style,{position:'fixed',width:'18px',height:'18px',border:'3px solid #e64f36',background:'#ffffffbb',boxShadow:'0 0 0 5px #e64f3628',borderRadius:'50%',zIndex:'999999',pointerEvents:'none',left:'50%',top:'50%',transition:'left .18s, top .18s'});
      document.body.append(d);
      document.addEventListener('mousemove',e=>{d.style.left=(e.clientX-9)+'px';d.style.top=(e.clientY-9)+'px';});
    });
    await shot('home','메인 화면 · 정책 변경 목록과 지표',4800);
    await click(page.locator('#mode-all'));
    await shot('all','전체 정책 변경 목록',3700);
    await click(page.locator('#mode-impact'));
    await shot('impact','영향도 큼 기본 필터',3900);
    const search=page.locator('#search');
    await move(search); await search.fill('');await search.type('상호저축은행',{delay:130});
    await shot('search','법령·정책명 검색: 상호저축은행',4500);
    const result=page.locator('#items .item').filter({hasText:'상호저축은행법 시행령'}).first();
    if(!await result.count())throw new Error('검색 결과가 나오지 않습니다');
    await click(result);
    await page.locator('#detail .detail-head h2').waitFor({timeout:15000});
    await shot('event','상호저축은행법 시행령 · 개정 사건 상세',5200);
    const core=page.locator('#detail .core').first();
    await move(core.locator('h3').first());
    await shot('summary','이번 개정 핵심 요약·소관기관',4500);
    const diff=page.locator('#detail .highlight details.highlight-detail').filter({hasText:'실제 달라진 부분 보기'}).first();
    if(await diff.count()){
      await click(diff.locator('summary'));
      await shot('diff','조문 변경 전·후 비교: 신문 공고 → 홈페이지 공고',6600);
    }
    const institution=page.locator('#detail .institution-layout').first();
    if(await institution.count()){
      await move(institution);
      await shot('institutions','기관별 변경·사업 검토사항',6100);
      const agency=page.locator('#detail .agency-filter-button[data-institution="예금보험공사"]').first();
      if(await agency.count()){
        await click(agency);
        await shot('kdic','기관 필터: 예금보험공사 · 후속 업무 검토',6700);
        const proof=page.locator('#detail .agency-group[open] .review-card details.proof summary').first();
        if(await proof.count()){await click(proof);await shot('proof','기관별 검토사항의 공식 변경 근거',6000);}
      }
    }
    const ai=page.locator('#detail .detail-section').filter({hasText:'AI 보조분석'}).first();
    if(await ai.count()){
      await move(ai.locator('h3').first());
      const draw=ai.locator('details.evidence-panel summary').first();
      if(await draw.count()) await click(draw);
      await shot('ai','AI 보조분석 · 담당자 추가 검토 질문',6800);
    }
    const evidence=page.locator('#detail .evidence-archive').first();
    if(await evidence.count()){
      await click(evidence.locator('summary').first());
      await shot('source','공식 신구대비와 변경 조문 근거',5900);
    }
    await click(page.locator('a.site-brand'));
    await shot('return','상단 로고로 첫 화면 복귀',3800);
    await click(page.locator('#mode-all'));
    await page.locator('#search').fill('적극행정 운영규정');
    const second=page.locator('#items .item').filter({hasText:'적극행정 운영규정'}).first();
    await click(second);
    await page.locator('#detail .detail-head h2').waitFor({timeout:15000});
    await shot('second','두 번째 사례: 적극행정 운영규정',4800);
    const otherAI=page.locator('#detail .detail-section').filter({hasText:'AI 보조분석'}).first();
    if(await otherAI.count()){
      await move(otherAI.locator('h3').first());
      const d=otherAI.locator('details.evidence-panel summary').first();
      if(await d.count())await click(d);
      await shot('second_ai','AI가 생성한 검토 질문과 조문 인용',7900);
    }
    await click(page.locator('a.site-brand'));
    await shot('ending','POLICY DOMINO · 정책 변경에서 기관별 후속조치까지',4500);
  }catch(error){
    console.error('CAPTURE ERROR',error.stack||String(error));
    chapters.push({t:time(),name:'error',desc:String(error)});
  }finally{
    fs.writeFileSync(path.join(out,'chapters.json'),JSON.stringify({url:page.url(),chapters},null,2));
    const video=page.video();
    await context.close();
    if(video)await video.saveAs(path.join(out,'live-next.webm'));
    await browser.close();
  }
}
main().catch(e=>{console.error(e.stack);process.exitCode=1});